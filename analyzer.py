import os
import json
from dotenv import load_dotenv
import anthropic
from groq import Groq

load_dotenv()

from stages import SALES_STAGES

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TRANSCRIPT_CHARS = 12000

def transcribe_audio(audio_file_path: str) -> str:
    print(f"Транскрибирую аудио: {audio_file_path}")
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    with open(audio_file_path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(os.path.basename(audio_file_path), f),
            model="whisper-large-v3-turbo",
            language="ru",
        )
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
        '  "priority_improvements": ["топ-3 приоритета для улучшения"]\n'
        '}\n\n'
        "Отвечай строго в JSON формате, без дополнительного текста. "
        "Все поля на русском языке. "
        "Будь конкретным — приводи примеры из разговора."
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
