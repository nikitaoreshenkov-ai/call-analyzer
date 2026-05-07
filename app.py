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
from storage import save_result, already_processed


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

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".mp4"}

st.title("Анализ звонков")
st.divider()

# ── Список ЖК (общий для обеих вкладок) ──────────────────────────────────────
with st.expander("⚙️ Настройки: названия ЖК для этого батча", expanded=False):
    st.caption("Укажите точные названия жилых комплексов — по одному на строке. Claude и Whisper будут использовать их при распознавании.")
    jk_input = st.text_area(
        "Названия ЖК",
        placeholder="А101 Лаголово\nА101 Всеволожск",
        height=100,
        label_visibility="collapsed",
    )

jk_names = [line.strip() for line in jk_input.splitlines() if line.strip()] if jk_input else []

tab_upload, tab_folder = st.tabs(["📁 Загрузить файлы", "🗂 Папка на диске"])


def _process_files(file_entries: list[tuple[str, str]]):
    """file_entries: list of (display_name, absolute_path)"""
    total = len(file_entries)
    overall_bar = st.progress(0, text=f"Обработано 0 / {total}")
    st.markdown("---")

    for idx, (display_name, file_path) in enumerate(file_entries):
        phone = _phone_from_filename(display_name)
        st.markdown(f"### 📞 {phone}  `({idx + 1}/{total})`")

        if already_processed(phone):
            st.info("⏭ Уже обработан — пропускаем.")
            overall_bar.progress((idx + 1) / total, text=f"Обработано {idx + 1} / {total}")
            continue

        try:
            with st.spinner("Транскрибирую через Groq..."):
                from analyzer import transcribe_audio
                transcript = transcribe_audio(file_path, jk_names=jk_names or None)

            with st.spinner("Анализирую через Claude..."):
                result, was_truncated = analyze_call(transcript, phone, jk_names=jk_names or None)

            save_result(phone, display_name, result, was_truncated)

            score = result["overall_score"]
            label = "🟢 ХОРОШО" if score >= 80 else "🟡 СРЕДНЕ" if score >= 60 else "🔴 НУЖНА РАБОТА"
            st.success(f"Оценка: **{score}/100** — {label}")

            with st.expander("Подробный отчёт", expanded=False):
                render_report(result, was_truncated)

        except Exception as e:
            st.error(f"Ошибка при обработке {display_name}: {e}")

        overall_bar.progress((idx + 1) / total, text=f"Обработано {idx + 1} / {total}")

    st.balloons()
    st.success(f"✅ Готово! Обработано {total} звонков. Перейдите на страницу **История** для сводной таблицы.")


# ── Вкладка 1: загрузка через браузер ────────────────────────────────────────

with tab_upload:
    st.markdown("Загрузите один или несколько аудиофайлов.")
    audio_files = st.file_uploader(
        "Аудиозаписи звонков",
        type=["mp3", "m4a", "wav", "ogg", "mp4"],
        accept_multiple_files=True,
    )

    run = st.button("▶ Анализировать", type="primary", use_container_width=True,
                    disabled=not audio_files, key="btn_upload")

    if run and audio_files:
        tmp_paths = []
        entries = []
        for audio_file in audio_files:
            ext = audio_file.name.rsplit(".", 1)[-1]
            with tempfile.NamedTemporaryFile(delete=False, suffix="." + ext) as tmp:
                tmp.write(audio_file.read())
                tmp_paths.append(tmp.name)
                entries.append((audio_file.name, tmp.name))
        try:
            _process_files(entries)
        finally:
            for p in tmp_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass


# ── Вкладка 2: обработка из папки на диске ───────────────────────────────────

with tab_folder:
    st.markdown("Укажите путь к папке — файлы читаются прямо с диска, без загрузки через браузер.")

    folder_path = st.text_input(
        "Путь к папке",
        placeholder="/Users/nikitaoreshenkov/Downloads/Записи...",
        help="Скопируйте путь к папке и вставьте сюда",
    )

    found_files: list[tuple[str, str]] = []
    if folder_path:
        folder_path = folder_path.strip()
        if not os.path.isdir(folder_path):
            st.error("❌ Папка не найдена. Проверьте путь.")
        else:
            found_files = sorted([
                (f, os.path.join(folder_path, f))
                for f in os.listdir(folder_path)
                if os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS
            ])
            if found_files:
                st.success(f"✅ Найдено аудиофайлов: **{len(found_files)}**")
                with st.expander("Показать список файлов"):
                    for name, _ in found_files:
                        st.text(name)
            else:
                st.warning("⚠️ В папке нет аудиофайлов (mp3, m4a, wav, ogg, mp4).")

    run_folder = st.button("▶ Анализировать папку", type="primary", use_container_width=True,
                           disabled=not found_files, key="btn_folder")

    if run_folder and found_files:
        _process_files(found_files)
