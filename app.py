import streamlit as st
import os
import json
import tempfile
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Анализ звонков",
    page_icon="📞",
    layout="wide"
)

if not os.getenv("ANTHROPIC_API_KEY"):
    st.error("Не задан ANTHROPIC_API_KEY. Добавьте его в файл .env и перезапустите приложение.")
    st.stop()

from analyzer import (
    get_whisper_model,
    transcribe_audio,
    analyze_call,
    WHISPER_MODEL_SIZE,
    MAX_TRANSCRIPT_CHARS,
)


@st.cache_resource
def load_model():
    return get_whisper_model()


def render_report(data: dict, was_truncated: bool = False):
    score = data["overall_score"]
    label = "ХОРОШО" if score >= 80 else "СРЕДНЕ" if score >= 60 else "НУЖНА РАБОТА"

    st.divider()
    st.subheader("Результат анализа звонка — " + data["manager_name"])

    if was_truncated:
        st.warning(
            f"⚠️ Звонок длиннее {MAX_TRANSCRIPT_CHARS} символов транскрипта. "
            "Анализ выполнен по первой части — конец разговора не учитывался."
        )

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
        title = f"{icon} {stage['stage_name']} — {sc}/10  |  {status}"

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
            st.info(f"{i}. {imp}")

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
            model = load_model()
            transcript = transcribe_audio(tmp_path, model=model)

            progress.progress(50, text="Шаг 2/2 — Анализирую с помощью Claude...")
            result, was_truncated = analyze_call(transcript, manager_name.strip())

            progress.progress(100, text="Готово!")
            render_report(result, was_truncated)
        except ValueError as e:
            st.error(str(e))
        except Exception as e:
            st.error("Ошибка: " + str(e))
        finally:
            os.unlink(tmp_path)
