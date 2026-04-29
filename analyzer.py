import os
import json
import subprocess
import tempfile
from dotenv import load_dotenv
import anthropic
from groq import Groq

load_dotenv()

from stages import SALES_STAGES

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TRANSCRIPT_CHARS = 12000

# Подсказки для Whisper — правильное написание брендов и проектов
TRANSCRIPTION_PROMPT = (
    "Разговор менеджера по продажам недвижимости с клиентом. "
    "Названия проектов и застройщиков: А101, Брусника, ПИК, Самолёт, Эталон, "
    "Донстрой, MR Group, Страна Девелопмент, Инград, Гранель, Sminex, ФСК, "
    "Баркли, Колди, Центр-Инвест, Горячесть, ЖК, апартаменты, ипотека, эскроу."
)

GROQ_SIZE_LIMIT = 24 * 1024 * 1024  # 24 МБ — запас до лимита 25 МБ


def _compress_to_mp3(audio_path: str) -> str:
    """Сжимает аудио в MP3 128kbps через ffmpeg. Возвращает путь к временному файлу."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    tmp.close()
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", "-b:a", "128k", tmp.name],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return tmp.name


def transcribe_audio(audio_file_path: str) -> str:
    print(f"Транскрибирую аудио: {audio_file_path}")

    compressed_path = None
    send_path = audio_file_path

    if os.path.getsize(audio_file_path) > GROQ_SIZE_LIMIT:
        print("Файл большой — сжимаю в MP3...")
        compressed_path = _compress_to_mp3(audio_file_path)
        send_path = compressed_path
        print(f"Сжато: {os.path.getsize(compressed_path) / 1024 / 1024:.1f} МБ")

    try:
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        with open(send_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(os.path.basename(send_path), f),
                model="whisper-large-v3-turbo",
                language="ru",
                prompt=TRANSCRIPTION_PROMPT,
            )
    finally:
        if compressed_path:
            os.unlink(compressed_path)

    text = result.text.strip()
    print(f"Транскрипция готова! Длина текста: {len(text)} символов")
    return text


def _build_stages_text() -> str:
    stages_text = ""
    for i, stage in enumerate(SALES_STAGES, 1):
        stages_text += f"\n{i}. {stage['name']}:\n"
        for criterion in stage["criteria"]:
            stages_text += f"   - {criterion}\n"
    return stages_text


def analyze_call(transcript: str, manager_name: str = "Менеджер") -> tuple[dict, bool]:
    """Возвращает (анализ, был_ли_обрезан_транскрипт)."""
    print("\nАнализирую звонок с помощью Claude...")

    was_truncated = len(transcript) > MAX_TRANSCRIPT_CHARS
    if was_truncated:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n...[транскрипт обрезан]"

    claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    stages_text = _build_stages_text()

    system_prompt = (
        "Ты эксперт по продажам недвижимости и тренер менеджеров по продажам.\n\n"
        "ЭТАПЫ ПРОДАЖИ, которые нужно оценить:\n"
        + stages_text
    )

    user_prompt = (
        f"Проанализируй транскрипт звонка менеджера по имени {manager_name}.\n\n"
        "ТРАНСКРИПТ ЗВОНКА:\n"
        + transcript
        + "\n\nВерни анализ строго в формате JSON:\n"
        "{\n"
        f'  "manager_name": "{manager_name}",\n'
        '  "overall_score": число от 0 до 100,\n'
        '  "call_summary": "краткое описание звонка в 2-3 предложениях",\n'
        '  "residential_complex": "название ЖК — строго одно из: А101 Лаголово, А101 Всеволожск. Определи по контексту. Если ЖК не упомянут — Не определён",\n'
        '  "stages": [\n'
        '    {\n'
        '      "stage_name": "название этапа",\n'
        '      "completed": true или false,\n'
        '      "score": число от 0 до 10,\n'
        '      "what_was_done": "что менеджер сделал правильно",\n'
        '      "what_was_missed": "что не сделал или сделал плохо",\n'
        '      "quote": "цитата из звонка как пример",\n'
        '      "recommendation": "конкретный совет как улучшить"\n'
        '    }\n'
        '  ],\n'
        '  "critical_misses": ["список критичных пропусков"],\n'
        '  "top_strengths": ["список сильных сторон"],\n'
        '  "priority_improvements": ["топ-3 приоритета для улучшения"],\n'
        '  "report_flags": {\n'
        '    "call_interrupted": true если звонок прервался не по вине менеджера (обрыв связи, техническая помеха) до завершения разговора — иначе false,\n'
        '    "interrupted_comment": "одно предложение — о чём успели поговорить до обрыва, или null если не прерывался",\n'
        '    "passive_sale": true если менеджер завершил разговор пассивно — не пригласил на встречу или показ — иначе false,\n'
        '    "passive_sale_comment": "одно предложение — чем завершился разговор вместо приглашения",\n'
        '    "price_mismatch": true если менеджер предложил объект дороже бюджета клиента более чем на 10% — иначе false,\n'
        '    "client_budget": "бюджет клиента цифрой и валютой, например 5000000 руб., или null если не назван",\n'
        '    "offered_price": "цена предложенного объекта цифрой и валютой, или null если не названа",\n'
        '    "price_diff_percent": число — превышение в процентах если price_mismatch true, иначе null,\n'
        '    "price_mismatch_comment": "одно предложение — что искал клиент и что предложил менеджер",\n'
        '    "long_term_buyer": true если клиент планирует покупку через 6 и более месяцев — иначе false,\n'
        '    "long_term_comment": "одно предложение — что клиент сказал о сроках",\n'
        '    "non_target": true если звонок нецелевой (не покупка: документы, приёмка, другой вопрос) — иначе false,\n'
        '    "non_target_comment": "одно предложение — с каким вопросом позвонил клиент",\n'
        '    "meeting_required_not_done": true если встреча была уместна но менеджер не предложил — иначе false,\n'
        '    "meeting_comment": "одно предложение — почему встреча была уместна и что произошло вместо",\n'
        '    "meeting_proposed": true если менеджер предложил встречу или показ — иначе false,\n'
        '    "meeting_agreed": true если клиент согласился на встречу или показ — иначе false,\n'
        '    "meeting_result_comment": "одно предложение — чем завершилось обсуждение встречи: договорились, клиент отказался, перенесли и т.д."\n'
        '  }\n'
        '}\n\n'
        "Отвечай строго в JSON формате, без дополнительного текста. "
        "Все поля на русском языке. "
        "Будь конкретным — приводи примеры из разговора. "
        "Для report_flags будь строгим: ставь true только при явных признаках в тексте. "
        "Если call_interrupted=true — не снижай overall_score за незавершённые этапы, оцени только то что успело произойти. "
        "В транскрипте могут быть ошибки распознавания речи — исправляй их по контексту: "
        "неправильные названия ЖК, бессмысленные слова, искажённые цифры. "
        "Названия ЖК — только А101 Лаголово или А101 Всеволожск, любые искажения (Севоложск, лагуна, девушек и т.п.) исправляй на правильное по контексту. "
        "В цитатах используй исправленный вариант."
    )

    response = claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8000,
        temperature=0,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"}
        }],
        messages=[{"role": "user", "content": user_prompt}]
    )

    text = response.content[0].text
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        analysis = json.loads(text.strip())
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude вернул некорректный JSON: {e}\n\nНачало ответа:\n{text[:300]}"
        )

    print("Анализ получен!")
    return analysis, was_truncated


def print_report(analysis: dict):
    print("\n" + "=" * 60)
    print(f"АНАЛИЗ ЗВОНКА: {analysis['manager_name']}")
    print("=" * 60)

    score = analysis["overall_score"]
    level = "ХОРОШО" if score >= 80 else "СРЕДНЕ" if score >= 60 else "НУЖНА РАБОТА"

    print(f"\nОБЩАЯ ОЦЕНКА: {score}/100 [{level}]")
    print(f"\nРезюме:\n   {analysis['call_summary']}")

    print("\n" + "-" * 60)
    print("ОЦЕНКА ПО ЭТАПАМ:")
    print("-" * 60)

    for stage in analysis["stages"]:
        status = "[+]" if stage["completed"] else "[-]"
        print(f"\n{status} {stage['stage_name']} — {stage['score']}/10")
        if stage.get("what_was_done"):
            print(f"   Хорошо: {stage['what_was_done']}")
        if stage.get("what_was_missed"):
            print(f"   Пропущено: {stage['what_was_missed']}")
        if stage.get("quote"):
            print(f"   Цитата: \"{stage['quote']}\"")
        if stage.get("recommendation"):
            print(f"   Совет: {stage['recommendation']}")

    print("\n" + "-" * 60)
    print("КРИТИЧНЫЕ ПРОПУСКИ:")
    for miss in analysis.get("critical_misses", []):
        print(f"   * {miss}")

    print("\nСИЛЬНЫЕ СТОРОНЫ:")
    for strength in analysis.get("top_strengths", []):
        print(f"   + {strength}")

    print("\nПРИОРИТЕТЫ ДЛЯ УЛУЧШЕНИЯ:")
    for i, improvement in enumerate(analysis.get("priority_improvements", []), 1):
        print(f"   {i}. {improvement}")

    print("\n" + "=" * 60)


def save_report(analysis: dict, output_path: str):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"\nОтчёт сохранён: {output_path}")


def analyze_call_file(audio_path: str, manager_name: str = "Менеджер"):
    print(f"\n{'=' * 60}")
    print("ЗАПУСК АНАЛИЗА ЗВОНКА")
    print(f"   Файл: {audio_path}")
    print(f"   Менеджер: {manager_name}")
    print(f"{'=' * 60}")

    transcript = transcribe_audio(audio_path)

    analysis, was_truncated = analyze_call(transcript, manager_name)
    if was_truncated:
        print(f"⚠️  Транскрипт длиннее {MAX_TRANSCRIPT_CHARS} символов — анализ по первой части.")

    print_report(analysis)

    output_file = audio_path.rsplit(".", 1)[0] + "_report.json"
    save_report(analysis, output_file)
    return analysis


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("\nУкажите путь к аудиофайлу:")
        print("   python3 analyzer.py /путь/к/звонку.mp3")
        print("   python3 analyzer.py /путь/к/звонку.mp3 'Имя Менеджера'")
        sys.exit(1)

    audio_file = sys.argv[1]
    manager = sys.argv[2] if len(sys.argv) > 2 else "Менеджер"

    if not os.path.exists(audio_file):
        print(f"\nФайл не найден: {audio_file}")
        sys.exit(1)

    analyze_call_file(audio_file, manager)
