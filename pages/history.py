import streamlit as st
import pandas as pd
from storage import load_all_results

st.set_page_config(page_title="История звонков", page_icon="📋", layout="wide")

st.title("📋 История звонков")
st.markdown("Все проанализированные звонки — от последнего к первому.")
st.divider()

results = load_all_results()

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
    rows.append({
        "Телефон": r.get("phone", "—"),
        "Дата": r.get("analyzed_at", "")[:10],
        "Оценка": score,
        "Статус": "🟢 Хорошо" if score >= 80 else "🟡 Средне" if score >= 60 else "🔴 Слабо",
        "Провальные этапы": ", ".join(failed) if failed else "—",
        "Топ-проблема": analysis.get("priority_improvements", ["—"])[0],
        "Обрезан": "⚠️ Да" if r.get("was_truncated") else "Нет",
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

mask = (df["Оценка"] >= min_score) & (df["Оценка"] <= max_score) & (df["Дата"].isin(selected_dates))
df_filtered = df[mask]

# ── Метрики сверху ────────────────────────────────────────────────────────────

m1, m2, m3, m4 = st.columns(4)
m1.metric("Всего звонков", len(df_filtered))
m2.metric("Средняя оценка", f"{df_filtered['Оценка'].mean():.1f}" if len(df_filtered) else "—")
m3.metric("Хороших (≥80)", int((df_filtered["Оценка"] >= 80).sum()))
m4.metric("Слабых (<60)", int((df_filtered["Оценка"] < 60).sum()))

st.markdown("---")

# ── Таблица ───────────────────────────────────────────────────────────────────

display_cols = ["Телефон", "Дата", "Оценка", "Статус", "Провальные этапы", "Топ-проблема", "Обрезан"]
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
        label = "🟢 ХОРОШО" if score >= 80 else "🟡 СРЕДНЕ" if score >= 60 else "🔴 НУЖНА РАБОТА"
        st.markdown(f"**Оценка: {score}/100 — {label}**")
        st.info(analysis.get("call_summary", ""))

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
                if stage.get("recommendation"):
                    st.info("Совет: " + stage["recommendation"])
