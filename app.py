import streamlit as st
import os
import json
import tempfile
from dotenv import load_dotenv
import anthropic
import whisper

load_dotenv()

st.set_page_config(
    page_title="Анализ звонков",
    page_icon="📞",
    layout="wide"
)

from stages import SALES_STAGES


@st.cache_resource
def load_whisper_model():
    return whisper.load_model("small")


def transcribe(audio_path: str) -> str:
    model = load_whisper_model()
    result = model.transcribe(audio_path, language="ru", verbose=False)
    return result["text"].strip()


def analyze(transcript: str, manager_name: str) -> dict:
    claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    if len(transcript) > 12000:
        transcript = transcript[:12000] + "\n...[обрезано]"

    stages_text = ""
    for i, stage in enumerate(SALES_STAGES, 1):
        stages_text += f"\n{i}. {stage['name']}:\n"
        for c in stage["criteria"]:
            stages_text += f"   - {c}\n"

    prompt = (
        "Ты эксперт по продажам недвижимости и тренер менеджеров по продажам.\n\n"
        f"Проанализируй транскрипт звонка менеджера по имени {manager_name}.\n\n"
        "ЭТАПЫ ПРОДАЖИ, которые нужно оценить:\n"
        + stages_text
        + "\nТРАНСКРИПТ ЗВОНКА:\n"
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
        model="claude-opus-4-6",
        max_tokens=8000,
        temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        text = text.strip()
        if not text.endswith("}"):
            text += ']}}'
        return json.loads(text)


def render_report(data: dict):
    score = data["overall_score"]

    if score >= 80:
        label = "ХОРОШО"
    elif score >= 60:
        label = "СРЕДНЕ"
    else:
        label = "НУЖНА РАБОТА"

    st.divider()
    st.subheader("Результат анализа звонка — " + data["manager_name"])

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.metric(label="Общая оценка", value=str(score) + "/100", delta=label)

    st.markdown("**Резюме звонка:**")
    st.info(data["call_summary"])

    st.markdown("---")
    st.subheader("Оценка по этапам")

    for stage in data["stages"]:
        sc = stage["score"]
        icon = "✅" if stage["completed"] else "❌"
        status = "Выполнен" if stage["completed"] else "Не выполнен"
        title = icon + " " + stage["stage_name"] + " — " + str(sc) + "/10  |  " + status

        with st.expander(title, expanded=True):
            st.progress(sc / 10)

            if stage.get("what_was_done"):
                st.success("Хорошо: " + stage["what_was_done"])

            if stage.get("what_was_missed"):
                st.error("Плохо: " + stage["what_was_missed"])

            if stage.get("quote"):
                st.warning("Цитата: " + stage["quote"])

            if stage.get("recommendation"):
                st.info("Совет: " + stage["recommendation"])

    st.markdown("---")
    st.subheader("Итоги")

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.markdown("#### Критичные пропуски")
        for m in data.get("critical_misses", []):
            st.error(m)

    with col_b:
        st.markdown("#### Сильные стороны")
        for s in data.get("top_strengths", []):
            st.success(s)

    with col_c:
        st.markdown("#### Приоритеты улучшения")
        for i, imp in enumerate(data.get("priority_improvements", []), 1):
            st.info(str(i) + ". " + imp)

    st.markdown("---")
    st.download_button(
        label="Скачать отчёт (JSON)",
        data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name="report_" + data["manager_name"].replace(" ", "_") + ".json",
        mime="application/json"
    )


# Главная страница

st.title("Анализ звонков менеджеров")
st.markdown("Загрузите запись звонка — получите детальный разбор по каждому этапу продажи.")
st.divider()

col_left, col_right = st.columns(2)

with col_left:
    manager_name = st.text_input("Имя менеджера", placeholder="Например: Алексей Петров")

with col_right:
    audio_file = st.file_uploader(
        "Аудиозапись звонка",
        type=["mp3", "m4a", "wav", "ogg", "mp4"]
    )

st.markdown("")
run = st.button("Анализировать звонок", type="primary", use_container_width=True)

if run:
    if not audio_file:
        st.error("Загрузите аудиофайл")
    elif not manager_name.strip():
        st.error("Введите имя менеджера")
    else:
        ext = audio_file.name.rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix="." + ext) as tmp:
            tmp.write(audio_file.read())
            tmp_path = tmp.name

        try:
            progress = st.progress(0, text="Шаг 1/2 — Транскрибирую аудио...")
            transcript = transcribe(tmp_path)
            progress.progress(50, text="Шаг 2/2 — Анализирую с помощью Claude...")
            result = analyze(transcript, manager_name.strip())
            progress.progress(100, text="Готово!")
            render_report(result)
        except Exception as e:
            st.error("Ошибка: " + str(e))
        finally:
            os.unlink(tmp_path)
