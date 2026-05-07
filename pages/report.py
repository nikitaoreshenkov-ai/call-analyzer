import re
from datetime import datetime

import pandas as pd
import streamlit as st
from client_paths import DEFAULT_CLIENT_ID, list_available_client_ids, normalize_client_id
from constants import REVIEW_LABEL, call_status_label
from expert_overrides import apply_expert_overrides_to_result
from jk_catalog import load_reference_jk_aliases
from report_text import normalize_missed_text
from storage import load_all_results

st.set_page_config(page_title="Отчёт для застройщика", page_icon="📄", layout="wide")

CALL_REVIEW_SECTION_TITLE = "Экспертная оценка обработки звонков"

st.title("📄 Отчёт для застройщика")
st.markdown("Сводный анализ по всем обработанным звонкам.")
st.divider()


known_client_ids = list_available_client_ids()
default_client_id = st.session_state.get("client_id", DEFAULT_CLIENT_ID)

with st.sidebar:
    st.markdown("### Клиент")
    raw_client_id = st.text_input("ID клиента", value=default_client_id, key="report_client_id")
    client_id = normalize_client_id(raw_client_id)
    st.session_state["client_id"] = client_id
    if known_client_ids:
        st.caption("Доступные ID: " + ", ".join(known_client_ids))
    st.caption(f"Показан отчёт клиента: `{client_id}`")


@st.cache_data(ttl=60)
def _cached_results(client_id: str) -> list[dict]:
    return [apply_expert_overrides_to_result(r, client_id=client_id) for r in load_all_results(client_id=client_id)]


@st.cache_data(ttl=300)
def _cached_jk_aliases(client_id: str) -> dict[str, list[str]]:
    return load_reference_jk_aliases(client_id=client_id)


results = _cached_results(client_id)
flagged = [r for r in results if r.get("analysis", {}).get("report_flags")]

if not flagged:
    st.info("Нет данных для отчёта. Загрузите звонки на главной странице — после обработки здесь появится сводка.")
    st.stop()

# ── Фильтр по дате ────────────────────────────────────────────────────────────

dates = sorted({r.get("analyzed_at", "")[:10] for r in flagged}, reverse=True)
selected_dates = st.multiselect("Период (по дате анализа)", dates, default=dates)
data_all = [r for r in flagged if r.get("analyzed_at", "")[:10] in selected_dates]

if not data_all:
    st.warning("Нет звонков за выбранный период.")
    st.stop()

not_in_funnel = [r for r in data_all if not r.get("analysis", {}).get("in_funnel", True)]
review_required_rows = [r for r in data_all if r.get("analysis", {}).get("review_required")]
data = [r for r in data_all if r.get("analysis", {}).get("in_funnel", True)]
total = len(data)


def _truncate_at_sentence(text: str, max_len: int = 250) -> str:
    if len(text) <= max_len:
        return text
    chunk = text[:max_len]
    for sep in (". ", "! ", "? "):
        pos = chunk.rfind(sep)
        if pos > max_len // 2:
            return chunk[:pos + 1]
    return chunk.rstrip() + "…"


def expert_note(row: dict) -> str:
    return row.get("analysis", {}).get("expert_note", "")


def flag_rows(flag_key: str) -> list:
    return [r for r in data if r["analysis"]["report_flags"].get(flag_key)]


def pct(n: int) -> str:
    return f"{(n / total * 100) if total else 0:.1f}%"


def pct_of_all(n: int) -> str:
    return f"{(n / len(data_all) * 100) if data_all else 0:.1f}%"


def _call_review_group(row: dict) -> tuple[int, float]:
    analysis = row.get("analysis", {})
    flags = analysis.get("report_flags", {})
    score = analysis.get("overall_score", 0)
    score_applicable = analysis.get("score_applicable", analysis.get("in_funnel", True))
    review_required = analysis.get("review_required", False)

    if score_applicable and (
        review_required
        or flags.get("meeting_required_not_done")
        or flags.get("passive_sale")
        or flags.get("price_mismatch")
        or score < 60
    ):
        return (0, score)

    if score_applicable and (
        flags.get("meeting_agreed")
        or (score >= 80 and not review_required)
    ):
        return (1, -score)

    return (2, score if score_applicable else -score)


def _ordered_call_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=_call_review_group)


def _call_count_text(n: int) -> str:
    if n == 1:
        return "1 звонке"
    if 2 <= n % 100 <= 4 or (n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)):
        return f"{n} звонках"
    return f"{n} звонках"


def _humanize_underperformance_line(soft_count: int, hard_count: int) -> str:
    total_count = soft_count + hard_count
    if total_count == 0:
        return "Явный недожим менеджера не выявлен."

    if soft_count == total_count and total_count == 1:
        return "Явный недожим менеджера выявлен в 1 звонке: встреча была предложена, но клиент не согласился."

    if hard_count == total_count and total_count == 1:
        return "Явный недожим менеджера выявлен в 1 звонке: менеджер не перевёл разговор к встрече."

    parts = []
    if soft_count:
        parts.append(f"в {_call_count_text(soft_count)} встреча была предложена, но клиент не согласился")
    if hard_count:
        parts.append(f"в {_call_count_text(hard_count)} менеджер не перевёл разговор к встрече")

    total_label = "звонке" if total_count == 1 else "звонках"
    return f"Явный недожим менеджера выявлен в {total_count} {total_label}: " + "; ".join(parts) + "."


def _normalize_complex_names_in_text(text: str) -> str:
    normalized = text
    aliases = _cached_jk_aliases(client_id)
    for canonical, alias_values in aliases.items():
        for alias in sorted(alias_values, key=len, reverse=True):
            if not alias:
                continue
            normalized = re.sub(
                re.escape(alias),
                canonical,
                normalized,
                flags=re.IGNORECASE,
            )
    return normalized


def _sanitize_summary_text(summary: str, canonical_complex: str) -> str:
    if not summary:
        return ""

    text = summary
    text = _normalize_complex_names_in_text(text)

    text = re.sub(
        r"\bМенеджер\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?",
        "Менеджер",
        text,
    )
    text = re.sub(r"\s*\(компания [^)]+\)", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\bклиент(?:у|ка|ке|ом|а)?\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?",
        lambda m: re.sub(r"\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?$", "", m.group(0)),
        text,
    )
    text = re.sub(
        r"\bМеня зовут\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?",
        "Меня зовут менеджер",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sanitize_client_text(text: str, canonical_complex: str = "Не определён") -> str:
    if not isinstance(text, str) or not text:
        return text
    return _sanitize_summary_text(text, canonical_complex)


passive = flag_rows("passive_sale")
price_miss = flag_rows("price_mismatch")
long_term = flag_rows("long_term_buyer")
no_meeting = flag_rows("meeting_required_not_done")
meeting_proposed = flag_rows("meeting_proposed")
meeting_agreed = flag_rows("meeting_agreed")
meeting_operationally_confirmed = flag_rows("meeting_operationally_confirmed")
client_not_ready_rows = flag_rows("client_not_ready")
meeting_agreed_not_operational = [
    r for r in meeting_agreed
    if not r["analysis"]["report_flags"].get("meeting_operationally_confirmed")
]
meeting_proposed_not_agreed = [
    r for r in meeting_proposed
    if not r["analysis"]["report_flags"].get("meeting_agreed")
]
soft_reserve_rows = [
    r for r in meeting_proposed_not_agreed
    if not r["analysis"]["report_flags"].get("client_not_ready")
]
hard_reserve_rows = list(no_meeting)
hard_reserve_ids = {r.get("phone") for r in hard_reserve_rows}
passive_display_rows = [r for r in passive if r.get("phone") not in hard_reserve_ids]
non_target = [
    r for r in not_in_funnel
    if r["analysis"].get("call_status") == "out_of_funnel_non_target"
]
interrupted_after_dialog = [
    r for r in not_in_funnel
    if r["analysis"].get("call_status") == "out_of_funnel_interrupted_after_dialog"
]
callback_no_dialog = [
    r for r in not_in_funnel
    if r["analysis"].get("call_status") == "out_of_funnel_callback_later_no_dialog"
]
interrupted_before_dialog = [
    r for r in not_in_funnel
    if r["analysis"].get("call_status") == "out_of_funnel_interrupted"
]

scores    = [r["analysis"].get("overall_score", 0) for r in data]
avg_score = sum(scores) / len(scores) if scores else 0

n_agreed = len(meeting_agreed)
n_operational = len(meeting_operationally_confirmed)
n_agreed_not_operational = len(meeting_agreed_not_operational)
n_proposed = len(meeting_proposed)
n_proposed_not_agreed = len(meeting_proposed_not_agreed)
n_soft_reserve = len(soft_reserve_rows)
n_hard_reserve = len(hard_reserve_rows)
n_client_not_ready = len(client_not_ready_rows)
n_missed = len(no_meeting)
n_non_target_share = (len(non_target) / len(data_all) * 100) if data_all else 0
n_lost_potential = n_soft_reserve + n_hard_reserve
n_follow_up = n_client_not_ready

summary_lines = [
    f"Всего проанализировано {len(data_all)} звонков: в оценку продажной работы вошло {total}, исключено из оценки {len(not_in_funnel)}.",
    f"По основной воронке встреча согласована в {n_agreed} звонках, из них подтверждены {n_operational}.",
    f"Дальнейшей работы с клиентом требуют {n_follow_up} звонков: клиент заинтересован, но не был готов зафиксировать встречу в первом разговоре.",
    _humanize_underperformance_line(n_soft_reserve, n_hard_reserve),
    f"Из оценки исключены {len(not_in_funnel)} звонков: {len(non_target)} нецелевых, {len(interrupted_after_dialog)} с внешним обрывом после диалога, {len(interrupted_before_dialog)} прерванных до диалога и {len(callback_no_dialog)} с просьбой перезвонить без предметного разговора.",
]

# Рекомендации (вычисляем заранее — нужны и в Streamlit, и в HTML)
recs = []
p = lambda rows: (len(rows) / total * 100) if total else 0
if p(passive_display_rows) > 20:
    recs.append(f"**Пассивные продажи {pct(len(passive_display_rows))}** — ввести скрипт приглашения на показ в каждом целевом звонке.")
if p(hard_reserve_rows) > 15:
    recs.append(f"**Встреча не предложена {pct(len(hard_reserve_rows))}** — контролировать обязательное приглашение на встречу, когда диалог уже доведён до подходящего контекста.")
if p(soft_reserve_rows) > 20:
    recs.append(f"**Клиент не согласился на предложенную встречу {pct(len(soft_reserve_rows))}** — усилить аргументацию ценности встречи и фиксацию времени следующего шага.")
if p(meeting_agreed_not_operational) > 10:
    recs.append(
        f"**Следующий шаг согласован, но не подтверждён {pct(len(meeting_agreed_not_operational))}** "
        "— фиксировать рабочий канал связи и финальное подтверждение встречи."
    )
if p(client_not_ready_rows) > 20:
    recs.append(
        f"**Требуется повторная работа {pct(len(client_not_ready_rows))}** — усиливать повторный контакт: отправку материалов, контроль перезвона и возврат клиента к встрече или другому целевому действию."
    )
if p(price_miss) > 10:
    recs.append(f"**Расхождение цены {pct(len(price_miss))}** — усилить квалификацию бюджета перед презентацией.")
if p(long_term) > 20:
    recs.append(f"**Долгосрочные клиенты {pct(len(long_term))}** — настроить CRM-напоминания, не терять отложенный спрос.")
if n_non_target_share > 15:
    recs.append(
        f"**Нецелевые звонки {n_non_target_share:.1f}%** "
        "— вынести их в отдельный контур маршрутизации, чтобы не загружать отдел продаж."
    )
recs = recs[:3]

# ── 1. СТАТИСТИКА ─────────────────────────────────────────────────────────────

st.subheader(f"Статистика — {total} звонков")

st.info("\n".join(f"• {line}" for line in summary_lines))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Всего звонков",          f"{len(data_all)} шт.")
c2.metric("Оценивались как продажи",    f"{total} шт.")
c3.metric("Исключены из оценки", f"{len(not_in_funnel)} шт.")
c4.metric("Средний балл",    f"{avg_score:.0f} / 100")

c5, c6, c7, c8 = st.columns(4)
c5.metric("Согласована по разговору", f"{n_agreed} шт. ({pct(n_agreed)})")
c6.metric("Подтверждена",    f"{n_operational} шт. ({pct(n_operational)})")
c7.metric("Требуют повторной работы", f"{n_client_not_ready} шт. ({pct(n_client_not_ready)})")
c8.metric("Не подтверждена после согласия",      f"{n_agreed_not_operational} шт. ({pct(n_agreed_not_operational)})")

c9, c10, c11, c12 = st.columns(4)
c9.metric("Встреча предложена, но клиент не согласился",     f"{n_soft_reserve} шт. ({pct(n_soft_reserve)})")
c10.metric("Встреча не предложена",     f"{len(no_meeting)} шт. ({pct(len(no_meeting))})")
c11.metric("Нецелевые",      f"{len(non_target)} шт.")
c12.metric("Обрыв после диалога",      f"{len(interrupted_after_dialog)} шт.")

st.divider()

# ── 2. КОНВЕРСИЯ В ВСТРЕЧИ ────────────────────────────────────────────────────

st.subheader("Итог по встречам и следующим действиям")

show_potential = st.checkbox("Показать потенциальную конверсию", value=False)


def _bar_html(label: str, count: int, denom: int, color: str, note: str = "") -> str:
    pct_val = count / denom * 100 if denom else 0
    fill = min(pct_val, 100)
    return f"""
    <div style="margin:10px 0 20px">
      <div style="display:flex;justify-content:space-between;font-size:14px;margin-bottom:6px">
        <span style="font-weight:600">{label}</span>
        <span style="color:#444"><b>{count}</b> из <b>{denom}</b> звонков &nbsp;&mdash;&nbsp;
          <b style="font-size:16px">{pct_val:.1f}%</b>{note}</span>
      </div>
      <div style="background:#e9ecef;border-radius:8px;height:34px;overflow:hidden">
        <div style="background:{color};width:{fill}%;height:100%;border-radius:8px;
                    display:flex;align-items:center;padding-left:12px;
                    color:white;font-size:14px;font-weight:bold;white-space:nowrap;overflow:hidden">
          {pct_val:.1f}%
        </div>
      </div>
    </div>"""


bars = _bar_html("Встреча предложена", n_proposed, total, "#1f78ff")
bars += _bar_html("Встреча согласована по разговору", n_agreed, total, "#27ae60")
bars += _bar_html("Встреча подтверждена", n_operational, total, "#0f9d58")
bars += _bar_html(
    "Требуют повторной работы с клиентом",
    n_follow_up, total, "#8e44ad",
)
bars += _bar_html(
    "Встреча предложена, но клиент не согласился",
    n_soft_reserve, total, "#f39c12",
)
bars += _bar_html(
    "Встреча не предложена",
    n_hard_reserve, total, "#e67e22",
)
if show_potential:
    bars += _bar_html(
        "Потенциал роста конверсии",
        n_agreed + n_lost_potential, total, "#3498db",
        note=f" &nbsp;&nbsp;<span style='color:#888;font-size:12px'>(+{n_lost_potential} звонков, где менеджер мог сильнее вывести разговор к встрече)</span>",
    )

st.markdown(bars, unsafe_allow_html=True)

# «Не попали в воронку» — отдельный блок с потенциалом
nif_total  = len(not_in_funnel)
nif_missed = sum(
    1 for r in not_in_funnel
    if r["analysis"].get("report_flags", {}).get("meeting_required_not_done")
)

label_nif = f"Не попали в воронку — {nif_total} шт. (исключены по статусу звонка)"
with st.expander(label_nif, expanded=bool(not_in_funnel)):
    if nif_total and nif_missed:
        nif_pct = nif_missed / nif_total * 100
        st.markdown(
            f"""<div style="background:#fff3cd;border-left:4px solid #f0ad4e;
                            border-radius:4px;padding:10px 16px;margin-bottom:12px;font-size:13px">
              В этой группе менеджер мог предложить встречу, но не предложил:
              <b>{nif_missed} из {nif_total} звонков ({nif_pct:.1f}%)</b>.
            </div>""",
            unsafe_allow_html=True,
        )
    if not_in_funnel:
        rows_nif = [{
            "Балл":    r["analysis"].get("overall_score", 0),
            "Причина": call_status_label(r["analysis"].get("call_status"), style="report"),
            "ЖК":      r["analysis"].get("residential_complex", "Не определён"),
            "Телефон": r.get("phone", "—"),
            "Резюме":  _truncate_at_sentence(
                _sanitize_client_text(
                    r["analysis"].get("call_summary", "—"),
                    r["analysis"].get("residential_complex", "Не определён"),
                )
            ),
        } for r in sorted(not_in_funnel, key=lambda x: x["analysis"].get("overall_score", 0))]
        st.dataframe(pd.DataFrame(rows_nif), use_container_width=True, hide_index=True)
    else:
        st.success("Таких звонков не выявлено.")

st.divider()

# ── 3. ДЕТАЛИЗАЦИЯ ────────────────────────────────────────────────────────────

st.subheader("Детализация по категориям")


def render_category(title: str, rows: list, columns: list):
    if not rows:
        return
    label = f"{title} — {len(rows)} шт. ({pct(len(rows))})"
    with st.expander(label, expanded=True):
        table_rows = []
        for r in rows:
            flags = r["analysis"]["report_flags"]
            canonical_complex = r["analysis"].get("residential_complex", "Не определён")
            row = {
                "ЖК":      canonical_complex,
                "Телефон": r.get("phone", "—"),
            }
            for header, fn in columns:
                value = fn(flags, r)
                row[header] = _sanitize_client_text(value, canonical_complex) if isinstance(value, str) else value
            table_rows.append(row)
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)


render_category("Расхождение в цене >10% (возможно, объектов дешевле нет у застройщика)", price_miss, [
    ("Бюджет клиента",    lambda f, r: f.get("client_budget") or "—"),
    ("Предложенная цена", lambda f, r: f.get("offered_price") or "—"),
    ("Разница",           lambda f, r: f"+{f['price_diff_percent']:.1f}%" if f.get("price_diff_percent") else "—"),
    ("Комментарий",       lambda f, r: f.get("price_mismatch_comment") or "—"),
])

render_category("Планирование покупки более чем через 6 месяцев", long_term,
    [("Комментарий", lambda f, r: f.get("long_term_comment") or "—")])

render_category("Нецелевые звонки", non_target,
    [("Комментарий", lambda f, r: f.get("non_target_comment") or "—")])

render_category("Обрыв после предметного диалога", interrupted_after_dialog, [
    ("Комментарий", lambda f, r: f.get("interrupted_comment") or "—"),
])

render_category("Пассивные продажи", passive_display_rows,
    [("Чем завершился разговор", lambda f, r: f.get("passive_sale_comment") or "—")])

render_category("Менеджер не перевёл разговор к встрече", no_meeting,
    [("Комментарий", lambda f, r: f.get("meeting_comment") or "—")])

render_category("Встреча предложена, но клиент не согласился", soft_reserve_rows, [
    ("Итог", lambda f, r: f.get("meeting_result_comment") or "—"),
    ("Комментарий", lambda f, r: f.get("meeting_comment") or "—"),
])

render_category("Требуют повторной работы с клиентом", client_not_ready_rows, [
    ("Итог", lambda f, r: f.get("meeting_result_comment") or "—"),
    ("Комментарий", lambda f, r: f.get("client_not_ready_comment") or "—"),
])

render_category("Согласована по разговору, но не подтверждена", meeting_agreed_not_operational, [
    ("Комментарий", lambda f, r: f.get("meeting_confirmation_comment") or "—"),
])

st.divider()

# ── 4. ВЫВОДЫ ─────────────────────────────────────────────────────────────────

st.subheader("Выводы и рекомендации")
if recs:
    for i, rec in enumerate(recs, 1):
        st.warning(f"{i}. {rec}")
else:
    st.success("Критичных проблем не выявлено.")

st.divider()

# ── 5. ИТОГ ПО ВСТРЕЧАМ ───────────────────────────────────────────────────────

meeting_conversion = (n_operational / total * 100) if total else 0
meeting_agreed_conversion = (n_agreed / total * 100) if total else 0
not_closed_conversion = (n_proposed_not_agreed / total * 100) if total else 0
soft_reserve_conversion = (n_soft_reserve / total * 100) if total else 0
hard_reserve_conversion = (n_hard_reserve / total * 100) if total else 0
potential_total_conversion = ((n_agreed + n_lost_potential) / total * 100) if total else 0

st.markdown(
    f"""
    **Подтверждённые встречи:** {n_operational} из {total} звонков  
    Конверсия в подтверждённую встречу: **{meeting_conversion:.1f}%**
    """
)

st.markdown(
    f"""
    **Согласовано по разговору, но не подтверждено:** {n_agreed_not_operational} из {total} звонков  
    В этих кейсах клиент в разговоре согласился на следующий синхронный шаг, но рабочее подтверждение встречи ещё не зафиксировано. Доля: **{pct(n_agreed_not_operational)}**
    """
)

st.markdown(
    f"""
    **Требуют повторной работы:** {n_client_not_ready} из {total} звонков  
    В этих звонках клиент не был готов сразу зафиксировать встречу, попросил время, материалы или повторный контакт. Это не завершённые кейсы: по ним нужна дальнейшая работа менеджера, перезвон и возврат к следующему действию.
    """
)

st.markdown(
    f"""
    **Где менеджер не дожал клиента:** {n_lost_potential} из {total} звонков  
    Это суммарная зона недожима по встрече:
    - `Встреча предложена, но клиент не согласился` — {n_soft_reserve}
    - `Встреча не предложена` — {n_hard_reserve}
    """
)

st.markdown(
    f"""
    **Потенциал роста конверсии:** {n_lost_potential} звонков  
    Это зона, где менеджер мог сильнее перевести клиента в следующий шаг: либо дожать уже предложенную встречу, либо вообще вывести разговор к встрече.  
    При более сильной доработке этих звонков суммарная конверсия согласования по разговору могла бы приблизиться к **{potential_total_conversion:.1f}%**
    """
)

with st.expander("Методология отчёта", expanded=False):
    st.markdown(
        """
        - В основную воронку входят только звонки, где был предметный продажный диалог.
        - Нецелевые и прерванные не по вине менеджера звонки выносятся отдельно и не искажают KPI основной воронки.
        - Отдельно различаются:
          - встреча согласована по разговору
          - встреча подтверждена
          - клиент пока не готов к встрече в первом разговоре
        - Конверсия в подтверждённую встречу считается только по звонкам основной воронки.
        - `Потенциал роста конверсии` включает только звонки, где встречу можно было дожать или перевести в неё увереннее, и не включает случаи, где клиент пока не готов в первом разговоре.
        - Класс `клиент пока не готов` не снимает ответственность с менеджера: такие звонки требуют дальнейшей работы, повторного контакта и возврата к следующему действию.
        """
    )

# ── HTML-отчёт ────────────────────────────────────────────────────────────────

ordered_for_html = _ordered_call_rows(data)


def build_html_report(all_for_html: list[dict]) -> str:
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
            canonical_complex = r["analysis"].get("residential_complex", "Не определён")
            values = [fn(f, r) for _, fn in cols]
            sanitized_values = [
                _sanitize_client_text(value, canonical_complex) if isinstance(value, str) else value
                for value in values
            ]
            cells = [canonical_complex, r.get("phone", "—")] + sanitized_values
            body += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"

    def sec(title: str, rows: list, cols: list) -> str:
        if not rows:
            return ""
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

    # История звонков — только звонки в основной воронке
    ordered_for_html = _ordered_call_rows(all_for_html)

    def score_color(s):
        return "#27ae60" if s >= 80 else "#f39c12" if s >= 60 else "#e74c3c"

    def call_cards() -> str:
        cards = ""
        for r in ordered_for_html:
            a     = r["analysis"]
            score = a.get("overall_score", 0)
            color = score_color(score)
            score_label = f"{score}/100" if a.get("score_applicable", a.get("in_funnel", True)) else "Не оценивается"
            summary_text = _sanitize_summary_text(
                a.get("call_summary", ""),
                a.get("residential_complex", "Не определён"),
            )
            stages_rows = ""
            for st_item in a.get("stages", []):
                icon = "✅" if st_item.get("completed") else "❌"
                stages_rows += (
                    f"<tr><td>{icon} {st_item.get('stage_name','')}</td>"
                    f"<td style='text-align:center'>{st_item.get('score',0)}/10</td>"
                    f"<td>{normalize_missed_text(st_item.get('what_was_missed') or '—')}</td></tr>"
                )
            summary_line = (
                f"📞 {r.get('phone','—')} &nbsp;|&nbsp; "
                f"<span style='color:{color};font-weight:bold'>{score_label}</span> &nbsp;|&nbsp; "
                f"{a.get('residential_complex','')}"
            )
            cards += f"""
            <details>
              <summary class="card-summary">{summary_line}</summary>
              <div class="card-body">
                <p class="summary-text">{summary_text}</p>
                <table>
                  <thead><tr><th>Этап</th><th>Балл</th><th>Что было пропущено</th></tr></thead>
                  <tbody>{stages_rows}</tbody>
                </table>
              </div>
            </details>"""
        return cards

    # Конверсия в HTML — обе полосы статично
    def _html_bar(label, count, denom, color, note=""):
        pct_val = count / denom * 100 if denom else 0
        fill = min(pct_val, 100)
        return f"""
        <div style="margin:8px 0 16px">
          <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:5px">
            <span style="font-weight:600">{label}</span>
            <span><b>{count}</b> из <b>{denom}</b> &mdash; <b>{pct_val:.1f}%</b>{note}</span>
          </div>
          <div style="background:#e9ecef;border-radius:6px;height:28px;overflow:hidden">
            <div style="background:{color};width:{fill}%;height:100%;border-radius:6px;
                        display:flex;align-items:center;padding-left:10px;
                        color:white;font-size:12px;font-weight:bold">
              {pct_val:.1f}%
            </div>
          </div>
        </div>"""

    conv_html = (
        _html_bar("Встреча предложена", n_proposed, total, "#1f78ff")
        + _html_bar("Встреча согласована по разговору", n_agreed, total, "#27ae60")
        + _html_bar("Встреча подтверждена", n_operational, total, "#0f9d58")
        + _html_bar("Требуют повторной работы с клиентом", n_follow_up, total, "#8e44ad")
        + _html_bar("Встреча предложена, но клиент не согласился", n_soft_reserve, total, "#f39c12")
        + _html_bar("Встреча не предложена", n_hard_reserve, total, "#e67e22")
        + _html_bar("Потенциал роста конверсии",
                    n_agreed + n_lost_potential, total, "#3498db",
                    note=f" &nbsp;<span style='color:#888;font-size:11px'>(+{n_lost_potential} звонков, где менеджер мог сильнее вывести разговор к встрече)</span>")
    )

    # «Не попали в воронку» в HTML
    nif_rows_html = "".join(
        f"<tr><td>{r['analysis'].get('overall_score', 0)}</td>"
        f"<td>{call_status_label(r['analysis'].get('call_status'), style='report')}</td>"
        f"<td>{r['analysis'].get('residential_complex', '—')}</td>"
        f"<td>{r.get('phone', '—')}</td>"
        f"<td>{_truncate_at_sentence(_sanitize_client_text(r['analysis'].get('call_summary', '—'), r['analysis'].get('residential_complex', 'Не определён')))}</td></tr>"
        for r in sorted(not_in_funnel, key=lambda x: x["analysis"].get("overall_score", 0))
    )
    nif_note_html = (
        f"<p style='color:#856404;background:#fff3cd;padding:8px 12px;"
        f"border-radius:4px;margin:0 0 10px;font-size:12px'>"
        f"Упущенных встреч в этой группе: <b>{nif_missed} из {nif_total} "
        f"({nif_missed / nif_total * 100:.1f}%)</b></p>"
        if nif_missed and nif_total else ""
    )
    not_in_funnel_html = f"""
    <details>
      <summary class="sec-title">Не попали в воронку
        <span class="sec-count">{nif_total} шт. (исключены по статусу звонка)</span>
      </summary>
      <div class="sec-body">
        {nif_note_html}
        <table><thead><tr><th>Балл</th><th>Причина</th><th>ЖК</th><th>Телефон</th><th>Резюме</th></tr></thead>
        <tbody>{nif_rows_html}</tbody></table>
      </div>
    </details>"""

    recs_html = ("<ol>" + "".join(f"<li>{rec.replace('**','')}</li>" for rec in recs) + "</ol>") if recs \
                else "<p class='ok'>Критичных проблем не выявлено.</p>"
    meeting_summary_html = f"""
    <p><b>Подтверждённые встречи:</b> {n_operational} из {total} звонков.<br>
    Конверсия в подтверждённую встречу: <b>{meeting_conversion:.1f}%</b>.</p>

    <p><b>Согласовано по разговору:</b> {n_agreed} из {total} звонков.<br>
    Это более широкий слой, чем подтверждённая встреча. Доля: <b>{meeting_agreed_conversion:.1f}%</b>.</p>

    <p><b>Согласовано по разговору, но не подтверждено:</b> {n_agreed_not_operational} из {total} звонков.<br>
    Это случаи, где клиент по разговору согласился на следующий синхронный шаг, но подтверждение встречи ещё не зафиксировано.</p>

    <p><b>Требуют повторной работы:</b> {n_client_not_ready} из {total} звонков.<br>
    Это звонки, где клиент не был готов зафиксировать встречу в первом разговоре и попросил время, материалы или повторный контакт. Эти кейсы не завершены: по ним нужна дальнейшая работа менеджера.</p>

    <p><b>Встреча предложена, но клиент не согласился:</b> {n_soft_reserve} из {total} звонков.<br>
    Это случаи, где менеджер предложил встречу, но не довёл клиента до согласования. Доля: <b>{soft_reserve_conversion:.1f}%</b>.</p>

    <p><b>Встреча не предложена:</b> {n_hard_reserve} из {total} звонков.<br>
    Это случаи, где предметный диалог уже позволял предложить встречу, но явного приглашения не прозвучало. Доля: <b>{hard_reserve_conversion:.1f}%</b>.</p>

    <p><b>Потенциал роста конверсии:</b> {n_lost_potential} звонков.<br>
    Это зона, где менеджер мог сильнее перевести клиента в следующий шаг: либо дожать уже предложенную встречу, либо вообще вывести разговор к встрече. При более сильной доработке этих звонков суммарная конверсия согласования по разговору могла бы приблизиться к <b>{potential_total_conversion:.1f}%</b>.</p>
    """
    methodology_html = """
    <ul>
      <li>В основную воронку входят только звонки с предметным продажным диалогом.</li>
      <li>Нецелевые и прерванные не по вине менеджера звонки показываются отдельно и не искажают KPI основной воронки.</li>
      <li>Отдельно различаются: встреча согласована по разговору и встреча подтверждена.</li>
      <li>Сценарий <b>клиент пока не готов</b> выделяется отдельно и не считается недожимом автоматически, но не завершает работу менеджера.</li>
      <li>Конверсия в подтверждённую встречу считается только по звонкам основной воронки.</li>
      <li><b>Потенциал роста конверсии</b> включает только звонки, где встречу можно было дожать или перевести в неё увереннее, и не включает кейсы, где клиент пока не готов в первом разговоре.</li>
      <li>Для кейсов <b>клиент пока не готов</b> управленческий акцент смещается на дисциплину повторной работы: повторный контакт, возврат к встрече и дожим до следующего действия.</li>
    </ul>
    """
    executive_summary_html = "".join(f"<li>{line}</li>" for line in summary_lines)

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
  .kpi-sub {{ font-size: 11px; color: #888; margin-top: 2px; }}
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
  <div class="meta">Сформировано: {now} &nbsp;|&nbsp; Период: {period} &nbsp;|&nbsp; Звонков в основной воронке: {total} шт. из {len(data_all)}</div>

<h2>Ключевой вывод периода</h2>
<ol>
  {executive_summary_html}
</ol>

<h2 class="section-break">Статистика</h2>
  <div class="kpi-grid">
  <div class="kpi"><div class="kpi-label">Всего звонков</div><div class="kpi-value">{len(data_all)}</div></div>
  <div class="kpi"><div class="kpi-label">Оценивались как продажи</div><div class="kpi-value">{total}</div><div class="kpi-sub">основная воронка</div></div>
  <div class="kpi"><div class="kpi-label">Исключены из оценки</div><div class="kpi-value">{len(not_in_funnel)}</div><div class="kpi-sub">не искажают KPI</div></div>
  <div class="kpi"><div class="kpi-label">Средний балл</div><div class="kpi-value">{avg_score:.0f}/100</div></div>
  <div class="kpi"><div class="kpi-label">Согласована по разговору</div><div class="kpi-value">{n_agreed}</div><div class="kpi-sub">{pct(n_agreed)}</div></div>
  <div class="kpi"><div class="kpi-label">Подтверждена</div><div class="kpi-value">{n_operational}</div><div class="kpi-sub">{pct(n_operational)}</div></div>
  <div class="kpi"><div class="kpi-label">Требуют повторной работы</div><div class="kpi-value">{n_client_not_ready}</div><div class="kpi-sub">{pct(n_client_not_ready)}</div></div>
  <div class="kpi"><div class="kpi-label">Не подтверждена после согласия</div><div class="kpi-value">{n_agreed_not_operational}</div><div class="kpi-sub">{pct(n_agreed_not_operational)}</div></div>
  <div class="kpi"><div class="kpi-label">Встреча предложена, но клиент не согласился</div><div class="kpi-value">{n_soft_reserve}</div><div class="kpi-sub">{pct(n_soft_reserve)}</div></div>
  <div class="kpi"><div class="kpi-label">Встреча не предложена</div><div class="kpi-value">{n_hard_reserve}</div><div class="kpi-sub">{pct(n_hard_reserve)}</div></div>
  <div class="kpi"><div class="kpi-label">Нецелевые</div><div class="kpi-value">{len(non_target)}</div><div class="kpi-sub">вне воронки</div></div>
  <div class="kpi"><div class="kpi-label">Обрыв после диалога</div><div class="kpi-value">{len(interrupted_after_dialog)}</div><div class="kpi-sub">вне воронки</div></div>
</div>

<h2>Итог по встречам и следующим действиям</h2>
{conv_html}

<h2>Детализация по категориям</h2>
{sec("Расхождение в цене >10% (возможно, объектов дешевле нет у застройщика)", price_miss, price_cols)}
{sec("Планирование покупки более чем через 6 месяцев", long_term, [("Комментарий", lambda f, r: f.get("long_term_comment") or "—")])}
{sec("Нецелевые звонки", non_target, [("Комментарий", lambda f, r: f.get("non_target_comment") or "—")])}
{sec("Обрыв после предметного диалога", interrupted_after_dialog, [("Комментарий", lambda f, r: f.get("interrupted_comment") or "—")])}
{sec("Пассивные продажи", passive_display_rows, [("Чем завершился разговор", lambda f, r: f.get("passive_sale_comment") or "—")])}
{sec("Менеджер не перевёл разговор к встрече", no_meeting, [("Комментарий", lambda f, r: f.get("meeting_comment") or "—")])}
{sec("Встреча предложена, но клиент не согласился", soft_reserve_rows, [
    ("Итог", lambda f, r: f.get("meeting_result_comment") or "—"),
    ("Комментарий", lambda f, r: f.get("meeting_comment") or "—"),
])}
{sec("Требуют повторной работы с клиентом", client_not_ready_rows, [
    ("Итог", lambda f, r: f.get("meeting_result_comment") or "—"),
    ("Комментарий", lambda f, r: f.get("client_not_ready_comment") or "—"),
])}
{sec("Согласована по разговору, но не подтверждена", meeting_agreed_not_operational, [
    ("Комментарий", lambda f, r: f.get("meeting_confirmation_comment") or "—"),
])}
{not_in_funnel_html}

<h2>Выводы и рекомендации</h2>
{recs_html}
{meeting_summary_html}

<h2>{CALL_REVIEW_SECTION_TITLE}</h2>
{call_cards()}

<h2>Методология отчёта</h2>
{methodology_html}

</div>
</body>
</html>"""


html = build_html_report(data)
st.download_button(
    label="⬇️ Скачать полный отчёт (HTML → открой в браузере → распечатай в PDF)",
    data=html.encode("utf-8"),
    file_name=f"report_{datetime.now().strftime('%Y%m%d')}.html",
    mime="text/html",
)
