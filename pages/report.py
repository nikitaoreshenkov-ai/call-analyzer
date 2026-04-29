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

# Прерванные звонки — выделяем отдельно, в статистику не включаем
interrupted = [r for r in data if r["analysis"].get("report_flags", {}).get("call_interrupted")]
data = [r for r in data if not r["analysis"].get("report_flags", {}).get("call_interrupted")]

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

passive         = flag_rows("passive_sale")
price_miss      = flag_rows("price_mismatch")
long_term       = flag_rows("long_term_buyer")
non_target      = flag_rows("non_target")
no_meeting      = flag_rows("meeting_required_not_done")
meeting_done    = flag_rows("meeting_proposed")
meeting_agreed  = flag_rows("meeting_agreed")

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"- **Встреча предложена:** {pct(len(meeting_done))} звонков — менеджер пригласил на встречу или показ.")
    st.markdown(f"- **Клиент согласился на встречу:** {pct(len(meeting_agreed))} звонков — договорились о встрече.")
    st.markdown(f"- **Пассивные продажи:** {pct(len(passive))} звонков завершились без активного приглашения клиента.")
    st.markdown(f"- **Расхождение в цене больше 10%:** {pct(len(price_miss))} обращений сопровождались предложением с завышением цены относительно бюджета клиента.")
with col2:
    st.markdown(f"- **Планирование покупки на срок более 6 месяцев:** {pct(len(long_term))} клиентов планируют покупку более чем через 6 месяцев.")
    st.markdown(f"- **Нецелевые звонки:** {pct(len(non_target))} звонков не связаны с покупкой.")
    st.markdown(f"- **Встреча была уместна, но не предложена:** {pct(len(no_meeting))} случаев.")

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
    "Пассивные продажи",
    passive,
    [("Чем завершился разговор", lambda f, r: f.get("passive_sale_comment") or "—")],
)

# ── Встреча не предложена ─────────────────────────────────────────────────────

render_category(
    "Приглашение на встречу требовалось, но не предложили",
    no_meeting,
    [("Комментарий", lambda f, r: f.get("meeting_comment") or "—")],
)

# ── Результат по встречам ─────────────────────────────────────────────────────

render_category(
    "Менеджер предложил встречу",
    meeting_done,
    [
        ("Клиент согласился", lambda f, r: "✅ Да" if f.get("meeting_agreed") else "❌ Нет"),
        ("Итог", lambda f, r: f.get("meeting_result_comment") or "—"),
    ],
)

# ── Прерванные звонки ─────────────────────────────────────────────────────────

st.subheader("Прерванные звонки")
st.caption("Звонки прервались по техническим причинам — не по вине менеджера. В общую статистику не включены.")
if interrupted:
    import pandas as pd
    rows_int = []
    for r in interrupted:
        f = r["analysis"].get("report_flags", {})
        rows_int.append({
            "ЖК": r["analysis"].get("residential_complex", "Не определён"),
            "Телефон": r.get("phone", "—"),
            "О чём успели поговорить": f.get("interrupted_comment") or "—",
        })
    st.dataframe(pd.DataFrame(rows_int), use_container_width=True, hide_index=True)
else:
    st.success("Прерванных звонков не выявлено.")

st.divider()

# ── Сводные показатели ────────────────────────────────────────────────────────

st.subheader("📊 Сводные показатели")

scores = [r["analysis"].get("overall_score", 0) for r in data]
avg_score = sum(scores) / len(scores) if scores else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Средний балл", f"{avg_score:.0f} / 100")
c2.metric("Встреча предложена", pct(len(meeting_done)))
c3.metric("Договорились о встрече", pct(len(meeting_agreed)))
c4.metric("Пассивные продажи", pct(len(passive)))

c5, c6, c7, c8 = st.columns(4)
c5.metric("Нецелевые звонки", pct(len(non_target)))
c6.metric("Расхождение цены >10%", pct(len(price_miss)))
c7.metric("Долгосрочные покупатели", pct(len(long_term)))
c8.metric("Встреча не предложена", pct(len(no_meeting)))

# Рекомендации — только если показатель превышает порог
recs = []
p = lambda rows: len(rows) / total * 100
if p(passive) > 20:
    recs.append(f"**Пассивные продажи {pct(len(passive))}** — ввести обязательный скрипт приглашения на показ в каждом целевом звонке.")
if p(no_meeting) > 15:
    recs.append(f"**Встреча не предложена {pct(len(no_meeting))}** — контролировать, чтобы менеджер предлагал встречу при наличии интереса.")
if p(price_miss) > 10:
    recs.append(f"**Расхождение цены {pct(len(price_miss))}** — менеджеры предлагают объекты выше бюджета клиента, усилить квалификацию перед презентацией.")
if p(long_term) > 20:
    recs.append(f"**Долгосрочные клиенты {pct(len(long_term))}** — настроить CRM-напоминания, не терять отложенный спрос.")
if p(non_target) > 15:
    recs.append(f"**Нецелевые звонки {pct(len(non_target))}** — разгрузить менеджеров, перенаправить нецелевые обращения.")

st.markdown("**Рекомендации:**")
if recs:
    for i, rec in enumerate(recs, 1):
        st.warning(f"{i}. {rec}")
else:
    st.success("Критичных проблем не выявлено.")

st.divider()

# ── Генерация объединённого HTML-отчёта ──────────────────────────────────────

def build_html_report() -> str:
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    period = f"{min(selected_dates)} — {max(selected_dates)}" if selected_dates else "все даты"

    def tbl(rows: list[dict], cols: list[tuple]) -> str:
        if not rows:
            return "<p class='ok'>Случаев не выявлено.</p>"
        headers = ["ЖК", "Телефон"] + [c[0] for c in cols]
        th = "".join(f"<th>{h}</th>" for h in headers)
        body = ""
        for r in rows:
            f = r["analysis"]["report_flags"]
            cells = [r["analysis"].get("residential_complex", "Не определён"), r.get("phone", "—")] + [fn(f, r) for _, fn in cols]
            body += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"

    def sec(title: str, rows: list[dict], cols: list[tuple]) -> str:
        return f"<h2>{title}</h2><p class='count'>{len(rows)} шт. из {total} шт. ({pct(len(rows))})</p>{tbl(rows, cols)}"

    price_cols = [
        ("Бюджет клиента",    lambda f, r: f.get("client_budget") or "—"),
        ("Предложенная цена", lambda f, r: f.get("offered_price") or "—"),
        ("Разница в %",       lambda f, r: f"+{f['price_diff_percent']:.1f}%" if f.get("price_diff_percent") else "—"),
        ("Комментарий",       lambda f, r: f.get("price_mismatch_comment") or "—"),
    ]

    # Часть 3 — история звонков
    all_results = load_all_results()
    all_for_html = [r for r in all_results if r.get("analyzed_at", "")[:10] in selected_dates
                    and r.get("analysis", {}).get("report_flags")
                    and not r["analysis"]["report_flags"].get("call_interrupted")]

    def score_color(s: int) -> str:
        return "#27ae60" if s >= 80 else "#f39c12" if s >= 60 else "#e74c3c"

    def call_cards() -> str:
        html_cards = ""
        for r in sorted(all_for_html, key=lambda x: x["analysis"].get("overall_score", 0)):
            a = r["analysis"]
            score = a.get("overall_score", 0)
            color = score_color(score)
            stages_html = ""
            for st in a.get("stages", []):
                icon = "✅" if st.get("completed") else "❌"
                stages_html += f"""
                <tr>
                  <td>{icon} {st.get('stage_name','')}</td>
                  <td style="text-align:center">{st.get('score',0)}/10</td>
                  <td>{st.get('what_was_missed') or '—'}</td>
                  <td>{st.get('recommendation') or '—'}</td>
                </tr>"""
            html_cards += f"""
            <div class="card">
              <div class="card-header">
                <span class="phone">{r.get('phone','—')}</span>
                <span class="score" style="color:{color}">{score}/100</span>
                <span class="jk">{a.get('residential_complex','')}</span>
              </div>
              <p class="summary-text">{a.get('call_summary','')}</p>
              <table>
                <thead><tr><th>Этап</th><th>Балл</th><th>Что пропущено</th><th>Рекомендация</th></tr></thead>
                <tbody>{stages_html}</tbody>
              </table>
            </div>"""
        return html_cards

    # Прерванные в HTML
    interrupted_tbl = ""
    if interrupted:
        rows_int = "".join(
            f"<tr><td>{r['analysis'].get('residential_complex','—')}</td>"
            f"<td>{r.get('phone','—')}</td>"
            f"<td>{r['analysis'].get('report_flags',{}).get('interrupted_comment','—')}</td></tr>"
            for r in interrupted
        )
        interrupted_tbl = f"""
        <h2>Прерванные звонки</h2>
        <p class="count">{len(interrupted)} шт. — не включены в статистику</p>
        <table><thead><tr><th>ЖК</th><th>Телефон</th><th>О чём успели поговорить</th></tr></thead>
        <tbody>{rows_int}</tbody></table>"""

    recs_html = ""
    if recs:
        items = "".join(f"<li>{rec.replace('**','')}</li>" for rec in recs)
        recs_html = f"<h2>Рекомендации</h2><ol>{items}</ol>"
    else:
        recs_html = "<p class='ok'>Критичных проблем не выявлено.</p>"

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
  h2 {{ font-size: 16px; margin-top: 40px; border-bottom: 2px solid #e74c3c; padding-bottom: 4px; color: #c0392b; page-break-after: avoid; }}
  h3 {{ font-size: 15px; margin-top: 32px; color: #1a1a2e; border-bottom: 1px solid #ddd; padding-bottom: 3px; }}
  .meta {{ color: #888; font-size: 12px; margin-bottom: 28px; }}
  .count {{ font-size: 12px; color: #666; margin: 4px 0 8px; }}
  .ok {{ color: #27ae60; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0 28px; }}
  .kpi {{ background: #f8f9fa; border-radius: 6px; padding: 12px 14px; }}
  .kpi-label {{ font-size: 11px; color: #888; margin-bottom: 4px; }}
  .kpi-value {{ font-size: 22px; font-weight: bold; color: #1a1a2e; }}
  .summary-box {{ background: #fff8f8; border-left: 4px solid #e74c3c; padding: 12px 16px; margin: 12px 0 28px; }}
  .summary-box li {{ margin: 5px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 12px; }}
  th {{ background: #1a1a2e; color: white; padding: 7px 10px; text-align: left; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #e8e8e8; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #fafafa; }}
  .section-break {{ page-break-before: always; }}
  .card {{ border: 1px solid #e0e0e0; border-radius: 6px; margin: 16px 0; padding: 16px; page-break-inside: avoid; }}
  .card-header {{ display: flex; align-items: baseline; gap: 16px; margin-bottom: 8px; }}
  .phone {{ font-size: 15px; font-weight: bold; }}
  .score {{ font-size: 18px; font-weight: bold; }}
  .jk {{ font-size: 12px; color: #888; }}
  .summary-text {{ color: #555; margin: 0 0 10px; font-size: 12px; }}
  ol li {{ margin: 6px 0; }}
</style>
</head>
<body>
<div class="page">

<h1>Анализ звонков</h1>
<div class="meta">Сформировано: {now} &nbsp;|&nbsp; Период: {period} &nbsp;|&nbsp; Звонков в выборке: {total} шт.</div>

<!-- ЧАСТЬ 1: СВОДНЫЕ ПОКАЗАТЕЛИ -->
<h3>Сводные показатели</h3>
<div class="kpi-grid">
  <div class="kpi"><div class="kpi-label">Средний балл</div><div class="kpi-value">{avg_score:.0f}/100</div></div>
  <div class="kpi"><div class="kpi-label">Встреча предложена</div><div class="kpi-value">{pct(len(meeting_done))}</div></div>
  <div class="kpi"><div class="kpi-label">Договорились о встрече</div><div class="kpi-value">{pct(len(meeting_agreed))}</div></div>
  <div class="kpi"><div class="kpi-label">Пассивные продажи</div><div class="kpi-value">{pct(len(passive))}</div></div>
  <div class="kpi"><div class="kpi-label">Нецелевые звонки</div><div class="kpi-value">{pct(len(non_target))}</div></div>
  <div class="kpi"><div class="kpi-label">Расхождение цены &gt;10%</div><div class="kpi-value">{pct(len(price_miss))}</div></div>
  <div class="kpi"><div class="kpi-label">Долгосрочные покупатели</div><div class="kpi-value">{pct(len(long_term))}</div></div>
  <div class="kpi"><div class="kpi-label">Встреча не предложена</div><div class="kpi-value">{pct(len(no_meeting))}</div></div>
</div>

{recs_html}

<!-- ЧАСТЬ 2: КАТЕГОРИИ ПРОБЛЕМ -->
<h3 class="section-break">Детализация по категориям</h3>

{sec("Расхождение в цене больше 10%", price_miss, price_cols)}
{sec("Планирование покупки более чем через 6 месяцев", long_term, [("Комментарий", lambda f, r: f.get("long_term_comment") or "—")])}
{sec("Нецелевые звонки", non_target, [("Комментарий", lambda f, r: f.get("non_target_comment") or "—")])}
{sec("Пассивные продажи", passive, [("Чем завершился разговор", lambda f, r: f.get("passive_sale_comment") or "—")])}
{sec("Встреча уместна, но не предложена", no_meeting, [("Комментарий", lambda f, r: f.get("meeting_comment") or "—")])}
{sec("Менеджер предложил встречу", meeting_done, [
    ("Клиент согласился", lambda f, r: "Да" if f.get("meeting_agreed") else "Нет"),
    ("Итог", lambda f, r: f.get("meeting_result_comment") or "—"),
])}
{interrupted_tbl}

<!-- ЧАСТЬ 3: ИСТОРИЯ ЗВОНКОВ -->
<h3 class="section-break">История звонков — детальный разбор</h3>
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
