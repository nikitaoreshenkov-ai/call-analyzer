import streamlit as st
import pandas as pd
from client_paths import DEFAULT_CLIENT_ID, list_available_client_ids, normalize_client_id
from constants import REVIEW_LABEL, call_status_label
from expert_overrides import apply_expert_overrides_to_result
from storage import load_all_results

st.set_page_config(page_title="История звонков", page_icon="📋", layout="wide")

st.title("📋 История звонков")
st.markdown("Все проанализированные звонки — от последнего к первому.")
st.divider()


known_client_ids = list_available_client_ids()
default_client_id = st.session_state.get("client_id", DEFAULT_CLIENT_ID)

with st.sidebar:
    st.markdown("### Клиент")
    raw_client_id = st.text_input("ID клиента", value=default_client_id, key="history_client_id")
    client_id = normalize_client_id(raw_client_id)
    st.session_state["client_id"] = client_id
    if known_client_ids:
        st.caption("Доступные ID: " + ", ".join(known_client_ids))
    st.caption(f"Показаны звонки клиента: `{client_id}`")


@st.cache_data(ttl=60)
def _cached_results(client_id: str) -> list[dict]:
    return [apply_expert_overrides_to_result(r, client_id=client_id) for r in load_all_results(client_id=client_id)]


results = _cached_results(client_id)

if not results:
    st.info("Пока нет ни одного проанализированного звонка. Вернитесь на главную страницу и загрузите аудиофайлы.")
    st.stop()

# ── Формируем таблицу ─────────────────────────────────────────────────────────

rows = []
for r in results:
    analysis = r.get("analysis", {})
    stages = analysis.get("stages", [])
    failed = [s["stage_name"] for s in stages if not s.get("completed")]
    score = analysis.get("overall_score", 0)
    call_status = analysis.get("call_status", "in_funnel")
    review_required = analysis.get("review_required", False)
    score_applicable = analysis.get("score_applicable", analysis.get("in_funnel", True))
    status_label = call_status_label(call_status)
    n_chunks = analysis.get("n_chunks") or r.get("n_chunks") or 1
    rows.append({
        "Телефон": r.get("phone", "—"),
        "Дата": r.get("analyzed_at", "")[:10],
        "Оценка": score if score_applicable else None,
        "Статус": ("🟢 Хорошо" if score >= 80 else "🟡 Средне" if score >= 60 else "🔴 Слабо") if score_applicable else "⚪ Не оценивается",
        "Воронка": status_label,
        "Проверка": "⚠️ Да" if review_required else "Нет",
        "Провальные этапы": ", ".join(failed) if failed else "—",
        "Топ-проблема": analysis.get("priority_improvements", ["—"])[0],
        "Части": n_chunks,
        "_raw": r,
    })

df = pd.DataFrame(rows)

# ── Фильтры ───────────────────────────────────────────────────────────────────

col1, col2 = st.columns(2)
with col1:
    min_score, max_score = st.slider("Фильтр по оценке", 0, 100, (0, 100))
with col2:
    dates = sorted(df["Дата"].unique().tolist(), reverse=True)
    selected_dates = st.multiselect("Фильтр по дате", dates, default=dates)

funnel_statuses = sorted(df["Воронка"].unique().tolist())
selected_statuses = st.multiselect("Фильтр по статусу воронки", funnel_statuses, default=funnel_statuses)

score_series = df["Оценка"].fillna(-1)
mask = (
    ((df["Оценка"].isna()) | ((score_series >= min_score) & (score_series <= max_score)))
    & (df["Дата"].isin(selected_dates))
    & (df["Воронка"].isin(selected_statuses))
)
df_filtered = df[mask]

# ── Метрики сверху ────────────────────────────────────────────────────────────

m1, m2, m3, m4 = st.columns(4)
m1.metric("Всего звонков", len(df_filtered))
m2.metric("Средняя оценка", f"{df_filtered['Оценка'].dropna().mean():.1f}" if len(df_filtered['Оценка'].dropna()) else "—")
m3.metric("В воронке", int((df_filtered["Воронка"] == "В воронке").sum()))
m4.metric("Требует верификации", int((df_filtered["Проверка"] == "⚠️ Да").sum()))

st.markdown("---")

# ── Таблица ───────────────────────────────────────────────────────────────────

display_cols = ["Телефон", "Дата", "Оценка", "Статус", "Воронка", "Проверка", "Провальные этапы", "Топ-проблема", "Части"]
st.dataframe(
    df_filtered[display_cols].sort_values("Оценка", ascending=True),
    use_container_width=True,
    hide_index=True,
)

# ── Экспорт ───────────────────────────────────────────────────────────────────

csv = df_filtered[display_cols].to_csv(index=False).encode("utf-8-sig")
st.download_button(
    label="Скачать таблицу (CSV)",
    data=csv,
    file_name="calls_history.csv",
    mime="text/csv",
)

# ── Детальный отчёт по клику ──────────────────────────────────────────────────

st.markdown("---")
st.subheader("Детальный отчёт")

phones = df_filtered["Телефон"].tolist()
if phones:
    selected = st.selectbox("Выберите звонок для просмотра", phones)
    row = next((r for r in results if r.get("phone") == selected), None)
    if row:
        analysis = row["analysis"]
        score = analysis["overall_score"]
        if analysis.get("score_applicable", analysis.get("in_funnel", True)):
            label = "🟢 ХОРОШО" if score >= 80 else "🟡 СРЕДНЕ" if score >= 60 else "🔴 НУЖНА РАБОТА"
            st.markdown(f"**Оценка: {score}/100 — {label}**")
        else:
            st.markdown("**Звонок не оценивается по воронке**")
        st.info(analysis.get("call_summary", ""))
        raw_status = analysis.get("call_status", "in_funnel")
        st.caption(f"Статус воронки: {call_status_label(raw_status)}")
        n_chunks = analysis.get("n_chunks") or row.get("n_chunks") or 1
        if n_chunks > 1:
            st.caption(f"Транскрипт был обработан по {n_chunks} частям.")
        flags = analysis.get("report_flags", {})
        if flags.get("meeting_agreed"):
            if flags.get("meeting_operationally_confirmed"):
                st.success("Встреча согласована по разговору и операционно подтверждена.")
            else:
                st.warning("Встреча согласована по разговору, но операционное подтверждение требует проверки.")
            if flags.get("meeting_confirmation_comment"):
                st.caption(flags["meeting_confirmation_comment"])
        elif flags.get("client_not_ready"):
            st.info("Клиент пока не готов к встрече в этом разговоре — сценарий учитывается отдельно, но требует дальнейшего follow-up и не снимает ответственность за продолжение работы.")
            if flags.get("client_not_ready_comment"):
                st.caption(flags["client_not_ready_comment"])
        elif flags.get("meeting_proposed") and not flags.get("meeting_agreed"):
            st.warning("Встреча предложена, но не согласована.")
            if flags.get("meeting_comment"):
                st.caption(flags["meeting_comment"])
        elif flags.get("meeting_required_not_done"):
            st.error("Встреча была уместна, но менеджер её не предложил.")
            if flags.get("meeting_comment"):
                st.caption(flags["meeting_comment"])
        if analysis.get("review_required"):
            reasons = analysis.get("review_reasons", [])
            st.warning(REVIEW_LABEL + (": " + " | ".join(reasons) if reasons else "."))
        if analysis.get("expert_note"):
            st.info("Экспертная пометка: " + analysis["expert_note"])

        for stage in analysis.get("stages", []):
            sc = stage["score"]
            icon = "✅" if stage["completed"] else "❌"
            with st.expander(f"{icon} {stage['stage_name']} — {sc}/10", expanded=False):
                st.progress(sc / 10)
                if stage.get("what_was_done"):
                    st.success("Хорошо: " + stage["what_was_done"])
                if stage.get("what_was_missed"):
                    st.error("Плохо: " + stage["what_was_missed"])
                if stage.get("quote"):
                    st.warning("Цитата: " + stage["quote"])
                if stage.get("recommendation") and stage["score"] < 5:
                    st.info("Совет: " + stage["recommendation"])
