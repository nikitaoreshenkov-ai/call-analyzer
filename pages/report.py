import streamlit as st
from datetime import datetime
from storage import load_all_results

st.set_page_config(page_title="Отчёт для застройщика", page_icon="📄", layout="wide")

st.title("📄 Отчёт для застройщика")
st.markdown("Сводный анализ по всем обработанным звонкам.")
st.divider()

results = load_all_results()

# Оставляем только записи с флагами (новый формат)
flagged = [r for r in results if r.get("analysis", {}).get("report_flags")]

if not flagged:
    st.info(
        "Нет данных для отчёта. Загрузите звонки на главной странице — "
        "после обработки здесь появится сводка."
    )
    st.stop()

# ── Фильтр по дате ────────────────────────────────────────────────────────────

dates = sorted({r.get("analyzed_at", "")[:10] for r in flagged}, reverse=True)
selected_dates = st.multiselect("Период (по дате анализа)", dates, default=dates)
data = [r for r in flagged if r.get("analyzed_at", "")[:10] in selected_dates]

if not data:
    st.warning("Нет звонков за выбранный период.")
    st.stop()

total = len(data)

# ── Вспомогательная функция ───────────────────────────────────────────────────

def flag_rows(flag_key: str) -> list[dict]:
    rows = []
    for r in data:
        f = r["analysis"]["report_flags"]
        if f.get(flag_key):
            rows.append(r)
    return rows


def pct(n: int) -> str:
    return f"{n / total * 100:.2f}%"


# ── Шапка с цифрами ───────────────────────────────────────────────────────────

st.subheader(f"Всего номеров: {total} шт.")

passive       = flag_rows("passive_sale")
price_miss    = flag_rows("price_mismatch")
long_term     = flag_rows("long_term_buyer")
non_target    = flag_rows("non_target")
no_meeting    = flag_rows("meeting_required_not_done")

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"- **Пассивные продажи:** В {pct(len(passive))} случаев менеджеры не пригласили на встречу, ограничившись перепиской.")
    st.markdown(f"- **Расхождение в цене больше 10%:** {pct(len(price_miss))} обращений сопровождались предложением с завышением цены относительно бюджета клиента.")
with col2:
    st.markdown(f"- **Планирование покупки на срок более 6 месяцев:** {pct(len(long_term))} клиентов планируют покупку более чем через 6 месяцев.")
    st.markdown(f"- **Нецелевые звонки:** {pct(len(non_target))} звонков не связаны с покупкой.")

st.divider()


# ── Блок-шаблон для каждой категории ─────────────────────────────────────────

def render_category(title: str, rows: list[dict], columns: list[tuple]):
    """columns: list of (header, extractor_fn)"""
    st.subheader(title)
    st.markdown(f"**{len(rows)} шт. из {total} шт. ({pct(len(rows))})**")

    if not rows:
        st.success("Случаев не выявлено.")
        return

    table_rows = []
    for r in rows:
        analysis = r["analysis"]
        flags = analysis["report_flags"]
        row = {
            "ЖК": analysis.get("residential_complex", "Не определён"),
            "Телефон": r.get("phone", "—"),
        }
        for header, fn in columns:
            row[header] = fn(flags, r)
        table_rows.append(row)

    import pandas as pd
    st.dataframe(
        pd.DataFrame(table_rows),
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("")


# ── Расхождение в цене ────────────────────────────────────────────────────────

render_category(
    "Расхождение в цене больше, чем 10%",
    price_miss,
    [
        ("Бюджет клиента",   lambda f, r: f.get("client_budget") or "—"),
        ("Предложенная цена", lambda f, r: f.get("offered_price") or "—"),
        ("Разница в %",      lambda f, r: f"+{f['price_diff_percent']:.1f}%" if f.get("price_diff_percent") else "—"),
        ("Комментарий",      lambda f, r: f.get("price_mismatch_comment") or "—"),
    ],
)

# ── Долгосрочные покупатели ───────────────────────────────────────────────────

render_category(
    "Планирование покупки на срок более 6 месяцев",
    long_term,
    [("Комментарий", lambda f, r: f.get("long_term_comment") or "—")],
)

# ── Нецелевые звонки ─────────────────────────────────────────────────────────

render_category(
    "Нецелевые звонки",
    non_target,
    [("Комментарий", lambda f, r: f.get("non_target_comment") or "—")],
)

# ── Пассивные продажи ─────────────────────────────────────────────────────────

render_category(
    "Пассивные продажи (WhatsApp вместо встречи)",
    passive,
    [("Чем завершился разговор", lambda f, r: f.get("passive_sale_comment") or "—")],
)

# ── Встреча не предложена ─────────────────────────────────────────────────────

render_category(
    "Приглашение на встречу требовалось, но не предложили",
    no_meeting,
    [("Комментарий", lambda f, r: f.get("meeting_comment") or "—")],
)

st.divider()

# ── Генерация HTML-отчёта ─────────────────────────────────────────────────────

def build_html_report() -> str:
    def table_html(rows: list[dict], cols: list[tuple]) -> str:
        if not rows:
            return "<p style='color:#27ae60'>Случаев не выявлено.</p>"
        headers = ["ЖК", "Телефон"] + [c[0] for c in cols]
        th = "".join(f"<th>{h}</th>" for h in headers)
        body = ""
        for r in rows:
            f = r["analysis"]["report_flags"]
            cells = [
                r["analysis"].get("residential_complex", "Не определён"),
                r.get("phone", "—"),
            ] + [fn(f, r) for _, fn in cols]
            body += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"

    def section(title: str, rows: list[dict], cols: list[tuple]) -> str:
        count = len(rows)
        return f"""
        <h2>{title}</h2>
        <p class="count">{count} шт. из {total} шт. ({pct(count)})</p>
        {table_html(rows, cols)}
        """

    price_cols = [
        ("Бюджет клиента",    lambda f, r: f.get("client_budget") or "—"),
        ("Предложенная цена", lambda f, r: f.get("offered_price") or "—"),
        ("Разница в %",       lambda f, r: f"+{f['price_diff_percent']:.1f}%" if f.get("price_diff_percent") else "—"),
        ("Комментарий",       lambda f, r: f.get("price_mismatch_comment") or "—"),
    ]

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    period = f"{min(selected_dates)} — {max(selected_dates)}" if selected_dates else "все даты"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Отчёт по звонкам</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 14px; color: #1a1a2e; margin: 40px; }}
  h1 {{ font-size: 24px; margin-bottom: 4px; }}
  h2 {{ font-size: 17px; margin-top: 36px; border-bottom: 2px solid #e74c3c; padding-bottom: 4px; color: #c0392b; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 32px; }}
  .count {{ font-size: 13px; color: #555; margin: 4px 0 10px; }}
  .summary {{ background: #f8f9fa; border-left: 4px solid #e74c3c; padding: 12px 16px; margin-bottom: 32px; }}
  .summary li {{ margin: 6px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 13px; }}
  th {{ background: #1a1a2e; color: white; padding: 8px 10px; text-align: left; }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #e0e0e0; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #f8f9fa; }}
  p {{ margin: 4px 0; }}
</style>
</head>
<body>
<h1>Анализ звонков</h1>
<div class="meta">Сформировано: {now} &nbsp;|&nbsp; Период: {period} &nbsp;|&nbsp; Всего номеров: {total} шт.</div>

<div class="summary">
  <ul>
    <li><b>Пассивные продажи:</b> В {pct(len(passive))} случаев менеджеры не пригласили на встречу, ограничившись перепиской.</li>
    <li><b>Расхождение в цене больше 10%:</b> {pct(len(price_miss))} обращений сопровождались предложением с завышением цены относительно бюджета клиента.</li>
    <li><b>Планирование покупки на срок более 6 месяцев:</b> {pct(len(long_term))} клиентов планируют покупку более чем через 6 месяцев.</li>
    <li><b>Нецелевые звонки:</b> {pct(len(non_target))} звонков не связаны с покупкой.</li>
    <li><b>Встреча не предложена:</b> {pct(len(no_meeting))} случаев, когда встреча была уместна, но менеджер её не предложил.</li>
  </ul>
</div>

{section("Расхождение в цене больше, чем 10%", price_miss, price_cols)}
{section("Планирование покупки на срок более 6 месяцев", long_term, [("Комментарий", lambda f, r: f.get("long_term_comment") or "—")])}
{section("Нецелевые звонки", non_target, [("Комментарий", lambda f, r: f.get("non_target_comment") or "—")])}
{section("Пассивные продажи (WhatsApp вместо встречи)", passive, [("Чем завершился разговор", lambda f, r: f.get("passive_sale_comment") or "—")])}
{section("Приглашение на встречу требовалось, но не предложили", no_meeting, [("Комментарий", lambda f, r: f.get("meeting_comment") or "—")])}

</body>
</html>"""


html = build_html_report()
st.download_button(
    label="⬇️ Скачать отчёт (HTML → открой в браузере → распечатай в PDF)",
    data=html.encode("utf-8"),
    file_name=f"report_{datetime.now().strftime('%Y%m%d')}.html",
    mime="text/html",
)
