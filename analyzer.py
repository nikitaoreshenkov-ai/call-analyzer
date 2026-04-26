import os
import json
from dotenv import load_dotenv
import anthropic
import whisper

load_dotenv()

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

from stages import SALES_STAGES

WHISPER_MODEL_SIZE = "small"

print(f"Загружаю модель Whisper ({WHISPER_MODEL_SIZE})...")
whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
print(f"Модель загружена!\n")


def transcribe_audio(audio_file_path: str) -> str:
    print(f"Транскрибирую аудио: {audio_file_path}")
    print("   Это может занять несколько минут...")

    result = whisper_model.transcribe(
        audio_file_path,
        language="ru",
        verbose=False
    )

    text = result["text"].strip()
    print(f"Транскрипция готова! Длина текста: {len(text)} символов")
    return text


def analyze_call(transcript: str, manager_name: str = "Менеджер") -> dict:
    print(f"\nАнализирую звонок с помощью Claude...")

    # Обрезаем транскрипт если он слишком длинный (оставляем ~12000 символов)
    if len(transcript) > 12000:
        transcript = transcript[:12000] + "\n...[транскрипт обрезан для анализа]"

    stages_text = ""
    for i, stage in enumerate(SALES_STAGES, 1):
        stages_text += f"\n{i}. {stage['name']}:\n"
        for criterion in stage["criteria"]:
            stages_text += f"   - {criterion}\n"

    prompt = f"""Ты эксперт по продажам недвижимости и тренер менеджеров по продажам.

Проанализируй транскрипт звонка менеджера по имени {manager_name}.

ЭТАПЫ ПРОДАЖИ, которые нужно оценить:
{stages_text}

ТРАНСКРИПТ ЗВОНКА:
{transcript}

Верни анализ в формате JSON со следующей структурой:
{{
  "manager_name": "{manager_name}",
  "overall_score": число от 0 до 100,
  "call_summary": "краткое описание звонка в 2-3 предложениях",
  "stages": [
    {{
      "stage_name": "название этапа",
      "completed": true/false,
      "score": число от 0 до 10,
      "what_was_done": "что менеджер сделал правильно",
      "what_was_missed": "что не сделал или сделал плохо",
      "quote": "цитата из звонка как пример (если есть)",
      "recommendation": "конкретный совет как улучшить"
    }}
  ],
  "critical_misses": ["список критичных пропусков"],
  "top_strengths": ["список сильных сторон"],
  "priority_improvements": ["топ-3 вещи которые нужно улучшить в первую очередь"]
}}

Отвечай строго в JSON формате, без дополнительного текста.
Все поля должны быть на русском языке.
Будь конкретным: не пиши общие фразы, приводи примеры из разговора.
"""

    response = claude.messages.create(
        model="claude-opus-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = response.content[0].text

    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0]
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0]

    try:
        analysis = json.loads(response_text.strip())
    except json.JSONDecodeError:
        # Если JSON обрезан — пробуем починить добавив закрывающие скобки
        response_text = response_text.strip()
        if not response_text.endswith("}"):
            response_text += ']}}'
        analysis = json.loads(response_text)

    print("Анализ получен!")
    return analysis


def print_report(analysis: dict):
    print("\n" + "="*60)
    print(f"АНАЛИЗ ЗВОНКА: {analysis['manager_name']}")
    print("="*60)

    score = analysis["overall_score"]
    if score >= 80:
        level = "ХОРОШО"
    elif score >= 60:
        level = "СРЕДНЕ"
    else:
        level = "НУЖНА РАБОТА"

    print(f"\nОБЩАЯ ОЦЕНКА: {score}/100 [{level}]")
    print(f"\nРезюме:\n   {analysis['call_summary']}")

    print("\n" + "-"*60)
    print("ОЦЕНКА ПО ЭТАПАМ:")
    print("-"*60)

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

    print("\n" + "-"*60)
    print("КРИТИЧНЫЕ ПРОПУСКИ:")
    for miss in analysis.get("critical_misses", []):
        print(f"   * {miss}")

    print("\nСИЛЬНЫЕ СТОРОНЫ:")
    for strength in analysis.get("top_strengths", []):
        print(f"   + {strength}")

    print("\nПРИОРИТЕТЫ ДЛЯ УЛУЧШЕНИЯ:")
    for i, improvement in enumerate(analysis.get("priority_improvements", []), 1):
        print(f"   {i}. {improvement}")

    print("\n" + "="*60)


def save_report(analysis: dict, output_path: str):
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"\nОтчёт сохранён: {output_path}")


def analyze_call_file(audio_path: str, manager_name: str = "Менеджер"):
    print(f"\n{'='*60}")
    print(f"ЗАПУСК АНАЛИЗА ЗВОНКА")
    print(f"   Файл: {audio_path}")
    print(f"   Менеджер: {manager_name}")
    print(f"{'='*60}")

    transcript = transcribe_audio(audio_path)

    transcript_file = audio_path.rsplit(".", 1)[0] + "_transcript.txt"
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write(transcript)
    print(f"   Транскрипция сохранена: {transcript_file}")

    analysis = analyze_call(transcript, manager_name)
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
