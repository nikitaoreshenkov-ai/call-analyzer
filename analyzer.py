from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

import anthropic
from dotenv import load_dotenv
from openai import OpenAI

from jk_catalog import HousingComplexCatalog, load_reference_jk_aliases
from models_v1 import ClientPolicy, CriterionSignal, EvidenceQuote, ExtractedCallFacts
from rule_engine import DEFAULT_POLICY, score_call
from client_paths import DEFAULT_CLIENT_ID

load_dotenv()

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TRANSCRIPT_CHARS = 18000
CHUNK_OVERLAP_CHARS = 1500

_TRANSCRIPTION_BASE = (
    "Разговор менеджера по продажам недвижимости с клиентом. "
    "Термины: ЖК, апартаменты, ипотека, рассрочка, застройщик, показ, встреча."
)

OPENAI_SIZE_LIMIT = 24 * 1024 * 1024


def _build_transcription_prompt(jk_names: list[str]) -> str:
    if jk_names:
        return _TRANSCRIPTION_BASE + " Названия проектов: " + ", ".join(jk_names) + "."
    return _TRANSCRIPTION_BASE


def _compress_to_mp3(audio_path: str) -> str:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.close()
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", "-b:a", "128k", tmp.name],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return tmp.name


def transcribe_audio(audio_file_path: str, jk_names: list[str] | None = None) -> str:
    compressed_path = None
    send_path = audio_file_path

    if os.path.getsize(audio_file_path) > OPENAI_SIZE_LIMIT:
        compressed_path = _compress_to_mp3(audio_file_path)
        send_path = compressed_path

    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        with open(send_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=f,
                model="gpt-4o-mini-transcribe",
                language="ru",
                prompt=_build_transcription_prompt(jk_names or []),
            )
    finally:
        if compressed_path:
            os.unlink(compressed_path)

    return result.text.strip()


def _chunk_transcript(transcript: str, max_chars: int = MAX_TRANSCRIPT_CHARS) -> list[str]:
    if len(transcript) <= max_chars:
        return [transcript]

    separators = re_split_candidates(transcript)
    if not separators:
        separators = [transcript[i : i + max_chars] for i in range(0, len(transcript), max_chars)]

    chunks = []
    current = ""
    for piece in separators:
        piece = piece.strip()
        if not piece:
            continue
        candidate = f"{current}\n{piece}".strip() if current else piece
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = piece
        while len(current) > max_chars:
            chunks.append(current[:max_chars])
            current = current[max_chars - CHUNK_OVERLAP_CHARS :]
    if current:
        chunks.append(current)

    return _apply_overlap(chunks, max_chars=max_chars, overlap_chars=CHUNK_OVERLAP_CHARS)


def re_split_candidates(transcript: str) -> list[str]:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    if len(lines) > 3:
        return lines

    pieces = []
    buf = ""
    for part in transcript.replace("! ", "!\n").replace("? ", "?\n").replace(". ", ".\n").splitlines():
        part = part.strip()
        if not part:
            continue
        pieces.append(part)
    return pieces


def _apply_overlap(chunks: list[str], max_chars: int, overlap_chars: int) -> list[str]:
    if len(chunks) <= 1:
        return chunks

    merged = []
    for idx, chunk in enumerate(chunks):
        if idx == 0:
            merged.append(chunk)
            continue
        prev_tail = chunks[idx - 1][-overlap_chars:]
        candidate = prev_tail + "\n" + chunk
        merged.append(candidate[-max_chars:])
    return merged


def _extraction_schema_text() -> str:
    schema = ExtractedCallFacts.model_json_schema()
    return json.dumps(schema, ensure_ascii=False, indent=2)


def _extract_json_block(text: str) -> str:
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0]
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0]
    return text


def _build_extraction_prompt(transcript: str, call_id: str, manager_name: str, jk_names: list[str]) -> str:
    jk_hint = ""
    if jk_names:
        jk_hint = (
            "Список допустимых ЖК для сверки: "
            + ", ".join(jk_names)
            + ". Если название в речи искажено, верни сырой вариант как услышал/понял."
        )

    return (
        "Извлеки факты из транскрипта звонка менеджера по продажам недвижимости. "
        "Не оценивай менеджера свободным текстом и не придумывай рекомендации. "
        "Твоя задача — вернуть только подтверждаемые признаки разговора.\n\n"
        f"ID звонка: {call_id}\n"
        f"Имя менеджера по умолчанию: {manager_name}\n"
        f"{jk_hint}\n\n"
        "Правила извлечения:\n"
        "- true ставь только если признак явно подтверждён в тексте\n"
        "- false ставь только если по смыслу видно, что признак не был выполнен\n"
        "- null ставь, если из транскрипта нельзя надёжно сделать вывод\n"
        "- в evidence приводи короткие точные цитаты\n"
        "- если имя клиента менеджеру уже известно и он обращается по имени, это считается корректным использованием имени\n"
        "- способ оплаты включает ипотеку, рассрочку и наличные\n"
        "- callback_later_requested=true только когда клиент просит вернуться к разговору позже\n"
        "- interrupted_not_manager_fault=true только при явном обрыве/невозможности говорить не по вине менеджера\n"
        "- non_target_request=true, если звонок не про покупку недвижимости ИЛИ если это некорректный перевод / явный product mismatch: запрос клиента не соответствует продукту застройщика и разговор не может перейти в нормальную продажную работу\n"
        "- existing_appointment_context=true, если клиент уже записан на просмотр/встречу/консультацию ранее и текущий звонок идёт как сопровождение этой записи\n"
        "- service_follow_up_question=true, если звонок про уточняющий сервисный вопрос по уже существующей записи или процессу, а не про новую продажную квалификацию\n"
        "- meeting_offered=true только при явном предложении синхронного следующего шага\n"
        "- onsite_meeting_offered и online_meeting_offered разделяй строго\n\n"
        "- passive_material_send=true, если разговор уходит в сценарий «пришлите информацию / я сам(а) изучу» вместо фиксации синхронного следующего шага\n"
        "Верни только JSON строго по этой схеме:\n"
        + _extraction_schema_text()
        + "\n\nТРАНСКРИПТ:\n"
        + transcript
    )


def _merge_signal(signals: list[CriterionSignal]) -> CriterionSignal:
    evidences = []
    seen_quotes = set()
    values = [signal.value for signal in signals if signal is not None]
    notes = [signal.note for signal in signals if signal and signal.note]
    for signal in signals:
        if not signal:
            continue
        for ev in signal.evidence:
            key = (ev.text, ev.speaker, ev.timestamp)
            if key in seen_quotes:
                continue
            seen_quotes.add(key)
            evidences.append(ev)

    if any(value is True for value in values):
        final_value = True
    elif any(value is False for value in values):
        final_value = False
    else:
        final_value = None

    return CriterionSignal(
        value=final_value,
        evidence=evidences[:5],
        note="; ".join(dict.fromkeys(notes)) if notes else None,
    )


def _pick_longest(values: list[str | None]) -> str | None:
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned:
        return None
    return max(cleaned, key=len)


def merge_extracted_facts(chunks: list[ExtractedCallFacts]) -> ExtractedCallFacts:
    if len(chunks) == 1:
        return chunks[0]

    base = chunks[0].model_dump()
    merged = ExtractedCallFacts.model_validate(base)

    signal_fields = [
        name
        for name, field in ExtractedCallFacts.model_fields.items()
        if field.annotation is CriterionSignal
    ]
    scalar_text_fields = [
        "call_summary",
        "residential_complex_raw",
        "client_budget",
        "offered_price",
        "callback_comment",
        "interruption_comment",
        "non_target_comment",
        "price_comment",
        "long_term_comment",
        "meeting_comment",
    ]

    for field_name in signal_fields:
        merged_signal = _merge_signal([getattr(chunk, field_name) for chunk in chunks])
        setattr(merged, field_name, merged_signal)

    for field_name in scalar_text_fields:
        setattr(merged, field_name, _pick_longest([getattr(chunk, field_name) for chunk in chunks]))

    return merged


def _extract_call_facts_for_chunk(
    prepared_transcript: str,
    call_id: str,
    manager_name: str,
    jk_names: list[str] | None,
) -> ExtractedCallFacts:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8000,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": _build_extraction_prompt(
                    prepared_transcript,
                    call_id=call_id,
                    manager_name=manager_name,
                    jk_names=jk_names or [],
                ),
            }
        ],
    )

    text = _extract_json_block(response.content[0].text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude вернул некорректный JSON при извлечении фактов: {e}\n{text[:400]}")

    return ExtractedCallFacts.model_validate(parsed)


def extract_call_facts(
    transcript: str,
    call_id: str,
    manager_name: str = "Менеджер",
    jk_names: list[str] | None = None,
) -> tuple[ExtractedCallFacts, int]:
    chunks = _chunk_transcript(transcript)
    extracted = [
        _extract_call_facts_for_chunk(
            chunk,
            call_id=call_id,
            manager_name=manager_name,
            jk_names=jk_names,
        )
        for chunk in chunks
    ]
    return merge_extracted_facts(extracted), len(chunks)


def analyze_call(
    transcript: str,
    call_id: str,
    manager_name: str = "Менеджер",
    jk_names: list[str] | None = None,
    policy: ClientPolicy | None = None,
    client_id: str = DEFAULT_CLIENT_ID,
) -> tuple[dict, int, dict]:
    facts, n_chunks = extract_call_facts(
        transcript,
        call_id=call_id,
        manager_name=manager_name,
        jk_names=jk_names,
    )
    catalog = HousingComplexCatalog.from_names(
        jk_names or [],
        aliases=load_reference_jk_aliases(client_id=client_id),
    )
    complex_match = catalog.normalize(facts.residential_complex_raw)
    report = score_call(facts, complex_match, policy=policy or DEFAULT_POLICY).model_copy(update={"n_chunks": n_chunks})
    return report.model_dump(mode="json"), n_chunks, facts.model_dump(mode="json")


def analyze_call_file(
    audio_path: str,
    manager_name: str = "Менеджер",
    jk_names: list[str] | None = None,
    client_id: str = DEFAULT_CLIENT_ID,
):
    transcript = transcribe_audio(audio_path, jk_names=jk_names)
    report, n_chunks, facts = analyze_call(
        transcript,
        call_id=os.path.basename(audio_path).rsplit(".", 1)[0],
        manager_name=manager_name,
        jk_names=jk_names,
        client_id=client_id,
    )
    return {
        "report": report,
        "n_chunks": n_chunks,
        "facts": facts,
        "transcript": transcript,
    }
