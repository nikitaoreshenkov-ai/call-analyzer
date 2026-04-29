import streamlit as st
import pandas as pd
from datetime import datetime
from storage import load_all_results

st.set_page_config(page_title="Отчёт для застройщика", page_icon="📄", layout="wide")

st.title("📄 Отчёт для застройщика")
st.markdown("Сводный анализ по всем обработанным звонкам.")
st.divider()

results = load_all_results()
flagged = [r for r in results if r.get("analysis", {}).get("report_flags")]

if not flagged:
    st.info("Нет данных для отчёта. Загрузите звонки на главной странице — после обработки здесь появится сводка.")
    st.stop()

# ── Фильтр по дате ────────────────────────────────────────────────────────────

dates = sorted({r.get("analyzed_at", "")[:10] for r in flagged}, reverse=True)
selected_dates = st.multiselect("Период (по дате анализа)", dates, default=dates)
data = [r for r in flagged if r.get("analyzed_at", "")[:10] in selected_dates]

if not data:
    st.warning("Нет звонков за выбранный период.")
    st.stop()

# Прерванные — отдельно, в статистику не включаем
interrupted = [r for r in data if r["analysis"].get("report_flags", {}).get("call_interrupted")]
data = [r for r in data if not r["analysis"].get("report_flags", {}).get("call_interrupted")]

if not data:
    st.warning("Все звонки в выбранном периоде прерваны — нет данных для статистики.")
    st.stop()

total = len(data)


def flag_rows(flag_key: str) -> list:
    return [r for r in data if r["analysis"]["report_flags"].get(flag_key)]


def pct(n: int) -> str:
    return f"{n / total * 100:.1f}%"


passive        = flag_rows("passive_sale")
price_miss     = flag_rows("price_mismatch")
long_term      = flag_rows("long_term_buyer")
non_target     = flag_rows("non_target")
no_meeting     = flag_rows("meeting_required_not_done")
meeting_done   = flag_rows("meeting_proposed")
meeting_agreed = flag_rows("meeting_agreed")

scores    = [r["analysis"].get("overall_score", 0) for r in data]
avg_score = sum(scores) / len(scores) if scores else 0

# Рекомендации (вычисляем заранее — нужны и в Streamlit, и в HTML)
recs = []
p = lambda rows: len(rows) / total * 100
if p(passive) > 20:
    recs.append(f"**Пассивные продажи {pct(len(passive))}** — ввести скрипт приглашения на показ в каждом целевом звонке.")
if p(no_meeting) > 15:
    recs.append(f"**Встреча не предложена {pct(len(no_meeting))}** — контролировать приглашение при наличии интереса.")
if p(price_miss) > 10:
    recs.append(f"**Расхождение цены {pct(len(price_miss))}** — усилить квалификацию бюджета перед презентацией.")
if p(long_term) > 20:
    recs.append(f"**Долгосрочные клиенты {pct(len(long_term))}** — настроить CRM-напоминания, не терять отложенный спрос.")
if p(non_target) > 15:
    recs.append(f"**Нецелевые звонки {pct(len(non_target))}** — перенаправить нецелевые обращения, разгрузить менеджеров.")

# ── 1. СТАТИСТИКА ─────────────────────────────────────────────────────────────

st.subheader(f"Статистика — {total} звонков")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Средний балл",         f"{avg_score:.0f} / 100")
c2.metric("Встреча предложена",   pct(len(meeting_done)))
c3.metric("Договорились",         pct(len(meeting_agreed)))
c4.metric("Пассивные продажи",    pct(len(passive)))

c5, c6, c7, c8 = st.columns(4)
c5.metric("Нецелевые звонки",     pct(len(non_target)))
c6.metric("Расхождение цены >10%",pct(len(price_miss)))
c7.metric("Долгосрочные клиенты", pct(len(long_term)))
c8.metric("Встреча не предложена",pct(len(no_meeting)))

st.divider()

# ── 2. ДЕТАЛИЗАЦИЯ ────────────────────────────────────────────────────────────

st.subheader("Детализация по категориям")


def render_category(title: str, rows: list, columns: list):
    label = f"{title} — {len(rows)} шт. ({pct(len(rows))})"
    with st.expander(label, expanded=bool(rows)):
        if not rows:
            st.success("Случаев не выявлено.")
            return
        table_rows = []
        for r in rows:
            flags = r["analysis"]["report_flags"]
            row = {
                "ЖК":      r["analysis"].get("residential_complex", "Не определён"),
                "Телефон": r.get("phone", "—"),
            }
            for header, fn in columns:
                row[header] = fn(flags, r)
            table_rows.append(row)
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


render_category("Расхождение в цене >10%", price_miss, [
    ("Бюджет клиента",    lambda f, r: f.get("client_budget") or "—"),
    ("Предложенная цена", lambda f, r: f.get("offered_price") or "—"),
    ("Разница",           lambda f, r: f"+{f['price_diff_percent']:.1f}%" if f.get("price_diff_percent") else "—"),
    ("Комментарий",       lambda f, r: f.get("price_mismatch_comment") or "—"),
])

render_category("Планирование покупки более чем через 6 месяцев", long_term,
    [("Комментарий", lambda f, r: f.get("long_term_comment") or "—")])

render_category("Нецелевые звонки", non_target,
    [("Комментарий", lambda f, r: f.get("non_target_comment") or "—")])

render_category("Пассивные продажи", passive,
    [("Чем завершился разговор", lambda f, r: f.get("passive_sale_comment") or "—")])

render_category("Встреча уместна, но не предложена", no_meeting,
    [("Комментарий", lambda f, r: f.get("meeting_comment") or "—")])

render_category("Менеджер предложил встречу", meeting_done, [
    ("Клиент согласился", lambda f, r: "✅ Да" if f.get("meeting_agreed") else "❌ Нет"),
    ("Итог",              lambda f, r: f.get("meeting_result_comment") or "—"),
])

# Прерванные звонки
label_int = f"Прерванные звонки — {len(interrupted)} шт. (не включены в статистику)"
with st.expander(label_int, expanded=bool(interrupted)):
    if interrupted:
        rows_int = [{
            "ЖК":      r["analysis"].get("residential_complex", "Не определён"),
            "Телефон": r.get("phone", "—"),
            "О чём успели поговорить": r["analysis"].get("report_flags", {}).get("interrupted_comment") or "—",
        } for r in interrupted]
        st.dataframe(pd.DataFrame(rows_int), use_container_width=True, hide_index=True)
    else:
        st.success("Прерванных звонков не выявлено.")

st.divider()

# ── 3. ВЫВОДЫ ─────────────────────────────────────────────────────────────────

st.subheader("Выводы и рекомендации")
if recs:
    for i, rec in enumerate(recs, 1):
        st.warning(f"{i}. {rec}")
else:
    st.success("Критичных проблем не выявлено.")

st.divider()

# ── HTML-отчёт ────────────────────────────────────────────────────────────────

def build_html_report() -> str:
    now    = datetime.now().strftime("%d.%m.%Y %H:%M")
    period = f"{min(selected_dates)} — {max(selected_dates)}" if selected_dates else "все даты"

    def tbl(rows: list, cols: list) -> str:
        if not rows:
            return "<p class='ok'>Случаев не выявлено.</p>"
        headers = ["ЖК", "Телефон"] + [c[0] for c in cols]
        th   = "".join(f"<th>{h}</th>" for h in headers)
        body = ""
        for r in rows:
            f = r["analysis"]["report_flags"]
            cells = [r["analysis"].get("residential_complex", "Не определён"), r.get("phone", "—")] \
                    + [fn(f, r) for _, fn in cols]
            body += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"

    def sec(title: str, rows: list, cols: list) -> str:
        count = len(rows)
        return f"""
        <details open>
          <summary class="sec-title">{title} <span class="sec-count">{count} шт. из {total} ({pct(count)})</span></summary>
          <div class="sec-body">{tbl(rows, cols)}</div>
        </details>"""

    price_cols = [
        ("Бюджет клиента",    lambda f, r: f.get("client_budget") or "—"),
        ("Предложенная цена", lambda f, r: f.get("offered_price") or "—"),
        ("Разница",           lambda f, r: f"+{f['price_diff_percent']:.1f}%" if f.get("price_diff_percent") else "—"),
        ("Комментарий",       lambda f, r: f.get("price_mismatch_comment") or "—"),
    ]

    # История звонков
    all_results  = load_all_results()
    all_for_html = [r for r in all_results
                    if r.get("analyzed_at", "")[:10] in selected_dates
                    and r.get("analysis", {}).get("report_flags")
                    and not r["analysis"]["report_flags"].get("call_interrupted")]

    def score_color(s):
        return "#27ae60" if s >= 80 else "#f39c12" if s >= 60 else "#e74c3c"

    def call_cards() -> str:
        cards = ""
        for r in sorted(all_for_html, key=lambda x: x["analysis"].get("overall_score", 0)):
            a     = r["analysis"]
            score = a.get("overall_score", 0)
            color = score_color(score)
            stages_rows = ""
            for st_item in a.get("stages", []):
                icon = "✅" if st_item.get("completed") else "❌"
                stages_rows += (
                    f"<tr><td>{icon} {st_item.get('stage_name','')}</td>"
                    f"<td style='text-align:center'>{st_item.get('score',0)}/10</td>"
                    f"<td>{st_item.get('what_was_missed') or '—'}</td>"
                    f"<td>{st_item.get('recommendation') or '—'}</td></tr>"
                )
            summary_line = (
                f"📞 {r.get('phone','—')} &nbsp;|&nbsp; "
                f"<span style='color:{color};font-weight:bold'>{score}/100</span> &nbsp;|&nbsp; "
                f"{a.get('residential_complex','')}"
            )
            cards += f"""
            <details>
              <summary class="card-summary">{summary_line}</summary>
              <div class="card-body">
                <p class="summary-text">{a.get('call_summary','')}</p>
                <table>
                  <thead><tr><th>Этап</th><th>Балл</th><th>Что пропущено</th><th>Рекомендация</th></tr></thead>
                  <tbody>{stages_rows}</tbody>
                </table>
              </div>
            </details>"""
        return cards

    # Прерванные в HTML
    interrupted_html = ""
    if interrupted:
        int_rows = "".join(
            f"<tr><td>{r['analysis'].get('residential_complex','—')}</td>"
            f"<td>{r.get('phone','—')}</td>"
            f"<td>{r['analysis'].get('report_flags',{}).get('interrupted_comment','—')}</td></tr>"
            for r in interrupted
        )
        interrupted_html = f"""
        <details>
          <summary class="sec-title">Прерванные звонки <span class="sec-count">{len(interrupted)} шт. — не включены в статистику</span></summary>
          <div class="sec-body">
            <table><thead><tr><th>ЖК</th><th>Телефон</th><th>О чём успели поговорить</th></tr></thead>
            <tbody>{int_rows}</tbody></table>
          </div>
        </details>"""

    recs_html = ("<ol>" + "".join(f"<li>{rec.replace('**','')}</li>" for rec in recs) + "</ol>") if recs \
                else "<p class='ok'>Критичных проблем не выявлено.</p>"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Анализ звонков</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: Arial, sans-serif; font-size: 13px; color: #1a1a2e; margin: 0; padding: 0; }}
  .page {{ max-width: 1100px; margin: 0 auto; padding: 40px 32px; }}
  h1 {{ font-size: 26px; margin-bottom: 4px; }}
  h2 {{ font-size: 16px; margin-top: 36px; color: #1a1a2e; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  .meta {{ color: #888; font-size: 12px; margin-bottom: 24px; }}
  .ok {{ color: #27ae60; margin: 0; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 12px 0 24px; }}
  .kpi {{ background: #f8f9fa; border-radius: 6px; padding: 12px 14px; }}
  .kpi-label {{ font-size: 11px; color: #888; margin-bottom: 4px; }}
  .kpi-value {{ font-size: 20px; font-weight: bold; }}
  details {{ margin: 8px 0; border: 1px solid #e0e0e0; border-radius: 6px; overflow: hidden; }}
  details[open] {{ border-color: #c0392b; }}
  summary {{ cursor: pointer; padding: 10px 14px; background: #f8f9fa; font-weight: 600; list-style: none; user-select: none; }}
  summary::-webkit-details-marker {{ display: none; }}
  summary::before {{ content: "▶ "; font-size: 10px; color: #c0392b; }}
  details[open] summary::before {{ content: "▼ "; }}
  .sec-title {{ font-size: 14px; color: #1a1a2e; }}
  .sec-count {{ font-size: 12px; color: #888; font-weight: normal; margin-left: 8px; }}
  .sec-body {{ padding: 12px 14px; }}
  .card-summary {{ font-size: 13px; }}
  .card-body {{ padding: 12px 14px; }}
  .summary-text {{ color: #555; margin: 0 0 10px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 6px; font-size: 12px; }}
  th {{ background: #1a1a2e; color: white; padding: 7px 10px; text-align: left; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #eee; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  ol {{ margin: 8px 0; padding-left: 20px; }}
  ol li {{ margin: 6px 0; }}
  .section-break {{ page-break-before: always; margin-top: 0; }}
</style>
</head>
<body>
<div class="page">

<h1>Анализ звонков</h1>
<div class="meta">Сформировано: {now} &nbsp;|&nbsp; Период: {period} &nbsp;|&nbsp; Звонков: {total} шт.</div>

<h2>Статистика</h2>
<div class="kpi-grid">
  <div class="kpi"><div class="kpi-label">Средний балл</div><div class="kpi-value">{avg_score:.0f}/100</div></div>
  <div class="kpi"><div class="kpi-label">Встреча предложена</div><div class="kpi-value">{pct(len(meeting_done))}</div></div>
  <div class="kpi"><div class="kpi-label">Договорились</div><div class="kpi-value">{pct(len(meeting_agreed))}</div></div>
  <div class="kpi"><div class="kpi-label">Пассивные продажи</div><div class="kpi-value">{pct(len(passive))}</div></div>
  <div class="kpi"><div class="kpi-label">Нецелевые звонки</div><div class="kpi-value">{pct(len(non_target))}</div></div>
  <div class="kpi"><div class="kpi-label">Расхождение цены &gt;10%</div><div class="kpi-value">{pct(len(price_miss))}</div></div>
  <div class="kpi"><div class="kpi-label">Долгосрочные клиенты</div><div class="kpi-value">{pct(len(long_term))}</div></div>
  <div class="kpi"><div class="kpi-label">Встреча не предложена</div><div class="kpi-value">{pct(len(no_meeting))}</div></div>
</div>

<h2 class="section-break">Детализация по категориям</h2>
{sec("Расхождение в цене >10%", price_miss, price_cols)}
{sec("Планирование покупки более чем через 6 месяцев", long_term, [("Комментарий", lambda f, r: f.get("long_term_comment") or "—")])}
{sec("Нецелевые звонки", non_target, [("Комментарий", lambda f, r: f.get("non_target_comment") or "—")])}
{sec("Пассивные продажи", passive, [("Чем завершился разговор", lambda f, r: f.get("passive_sale_comment") or "—")])}
{sec("Встреча уместна, но не предложена", no_meeting, [("Комментарий", lambda f, r: f.get("meeting_comment") or "—")])}
{sec("Менеджер предложил встречу", meeting_done, [
    ("Клиент согласился", lambda f, r: "Да" if f.get("meeting_agreed") else "Нет"),
    ("Итог", lambda f, r: f.get("meeting_result_comment") or "—"),
])}
{interrupted_html}

<h2>Выводы и рекомендации</h2>
{recs_html}

<h2 class="section-break">История звонков — детальный разбор</h2>
{call_cards()}

</div>
</body>
</html>"""


html = build_html_report()
st.download_button(
    label="⬇️ Скачать полный отчёт (HTML → открой в браузере → распечатай в PDF)",
    data=html.encode("utf-8"),
    file_name=f"report_{datetime.now().strftime('%Y%m%d')}.html",
    mime="text/html",
)
