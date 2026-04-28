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

if not os.getenv("GROQ_API_KEY"):
    st.error("Не задан GROQ_API_KEY. Добавьте его в файл .env и перезапустите приложение.")
    st.stop()

from analyzer import analyze_call, MAX_TRANSCRIPT_CHARS
from storage import save_result


def _phone_from_filename(name: str) -> str:
    return name.rsplit(".", 1)[0]


def render_report(data: dict, was_truncated: bool = False):
    score = data["overall_score"]
    label = "ХОРОШО" if score >= 80 else "СРЕДНЕ" if score >= 60 else "НУЖНА РАБОТА"

    if was_truncated:
        st.warning(
            f"⚠️ Транскрипт длиннее {MAX_TRANSCRIPT_CHARS} символов — "
            "анализ выполнен по первой части звонка."
        )

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.metric(label="Общая оценка", value=f"{score}/100", delta=label)

    st.markdown("**Резюме звонка:**")
    st.info(data["call_summary"])

    st.markdown("---")
    st.subheader("Оценка по этапам")

    for stage in data["stages"]:
        sc = stage["score"]
        icon = "✅" if stage["completed"] else "❌"
        status = "Выполнен" if stage["completed"] else "Не выполнен"
        with st.expander(f"{icon} {stage['stage_name']} — {sc}/10  |  {status}", expanded=False):
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

    st.download_button(
        label="Скачать отчёт (JSON)",
        data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name="report_" + data.get("manager_name", "call").replace(" ", "_") + ".json",
        mime="application/json",
        key=f"dl_{data.get('manager_name', '')}_{score}",
    )


# ── Главная страница ──────────────────────────────────────────────────────────

st.title("Анализ звонков")
st.markdown("Загрузите один или несколько аудиофайлов — получите разбор по каждому этапу продажи.")
st.divider()

audio_files = st.file_uploader(
    "Аудиозаписи звонков",
    type=["mp3", "m4a", "wav", "ogg", "mp4"],
    accept_multiple_files=True,
)

run = st.button("Анализировать", type="primary", use_container_width=True, disabled=not audio_files)

if run and audio_files:
    total = len(audio_files)
    overall_bar = st.progress(0, text=f"Обработано 0 / {total}")
    st.markdown("---")

    for idx, audio_file in enumerate(audio_files):
        phone = _phone_from_filename(audio_file.name)
        st.markdown(f"### 📞 {phone}  `({idx + 1}/{total})`")

        ext = audio_file.name.rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix="." + ext) as tmp:
            tmp.write(audio_file.read())
            tmp_path = tmp.name

        try:
            with st.spinner("Транскрибирую через Groq..."):
                from analyzer import transcribe_audio
                transcript = transcribe_audio(tmp_path)

            with st.spinner("Анализирую через Claude..."):
                result, was_truncated = analyze_call(transcript, phone)

            save_result(phone, audio_file.name, result, was_truncated)

            score = result["overall_score"]
            label = "🟢 ХОРОШО" if score >= 80 else "🟡 СРЕДНЕ" if score >= 60 else "🔴 НУЖНА РАБОТА"
            st.success(f"Оценка: **{score}/100** — {label}")

            with st.expander("Подробный отчёт", expanded=False):
                render_report(result, was_truncated)

        except Exception as e:
            st.error(f"Ошибка при обработке {audio_file.name}: {e}")
        finally:
            os.unlink(tmp_path)

        overall_bar.progress((idx + 1) / total, text=f"Обработано {idx + 1} / {total}")

    st.balloons()
    st.success(f"✅ Готово! Обработано {total} звонков. Перейдите на страницу **История** для сводной таблицы.")
