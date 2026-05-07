from __future__ import annotations

from math import ceil

from models_v1 import (
    ANALYSIS_VERSION,
    CallStatus,
    ClientPolicy,
    CriterionSignal,
    ExtractedCallFacts,
    MeetingType,
    ReportFlags,
    ResidentialComplexMatch,
    ScoredCallReport,
    StageEvaluation,
)


DEFAULT_POLICY = ClientPolicy()


def _is_true(signal: CriterionSignal) -> bool:
    return signal.value is True


def _first_quote(*signals: CriterionSignal) -> str:
    for signal in signals:
        if signal.evidence:
            return signal.evidence[0].text
    return ""


def _stage_from_criteria(name: str, criteria: list[tuple[str, bool]], recommendation: str, quote: str = "") -> StageEvaluation:
    total = len(criteria)
    met = [label for label, ok in criteria if ok]
    missed = [label for label, ok in criteria if not ok]
    score = int(round((len(met) / total) * 10)) if total else 10
    completed = score >= 6
    return StageEvaluation(
        stage_name=name,
        completed=completed,
        score=score,
        what_was_done="; ".join(met) if met else "",
        what_was_missed="; ".join(missed) if missed else "",
        quote=quote,
        recommendation=recommendation if missed else "",
    )


def _not_applicable_stage(name: str, reason: str) -> StageEvaluation:
    return StageEvaluation(
        stage_name=name,
        completed=True,
        score=10,
        what_was_done=reason,
        what_was_missed="",
        quote="",
        recommendation="",
    )


def _not_applicable_stage_with_score(name: str, reason: str, score: int = 8) -> StageEvaluation:
    return StageEvaluation(
        stage_name=name,
        completed=True,
        score=score,
        what_was_done=reason,
        what_was_missed="",
        quote="",
        recommendation="",
    )


def substantive_dialog(facts: ExtractedCallFacts) -> bool:
    blocks = [
        _is_true(facts.need_housing_type)
        or _is_true(facts.need_area)
        or _is_true(facts.need_project_or_area)
        or _is_true(facts.need_purchase_goal)
        or _is_true(facts.need_family_composition),
        _is_true(facts.budget_discussed),
        _is_true(facts.payment_method_discussed)
        or _is_true(facts.mortgage_discussed)
        or _is_true(facts.installment_discussed)
        or _is_true(facts.cash_discussed),
        _is_true(facts.project_or_complex_discussed) or _is_true(facts.concrete_object_presented),
        _is_true(facts.next_step_discussed) or _is_true(facts.meeting_offered),
    ]
    return sum(1 for block in blocks if block) >= 2


def resolve_meeting_type(facts: ExtractedCallFacts) -> MeetingType:
    onsite = _is_true(facts.onsite_meeting_offered)
    online = _is_true(facts.online_meeting_offered)
    if onsite and online:
        return MeetingType.BOTH
    if onsite:
        return MeetingType.ONSITE
    if online:
        return MeetingType.ONLINE
    return MeetingType.NONE


def _meeting_type_variants(meeting_type: MeetingType) -> set[MeetingType]:
    if meeting_type == MeetingType.BOTH:
        return {MeetingType.ONSITE, MeetingType.ONLINE}
    if meeting_type in {MeetingType.ONSITE, MeetingType.ONLINE}:
        return {meeting_type}
    return set()


def _meeting_type_allowed(policy: ClientPolicy, meeting_type: MeetingType) -> bool:
    offered_variants = _meeting_type_variants(meeting_type)
    if not offered_variants:
        return False

    allowed_variants: set[MeetingType] = set()
    for allowed_type in policy.valid_meeting_types:
        allowed_variants.update(_meeting_type_variants(allowed_type))

    return bool(offered_variants & allowed_variants)


def _effective_meeting_offered(facts: ExtractedCallFacts, meeting_type: MeetingType) -> bool:
    if not _is_true(facts.meeting_offered):
        return False
    if meeting_type != MeetingType.NONE:
        return True

    evidence_text = " ".join(ev.text for ev in facts.meeting_offered.evidence).casefold()
    note_text = " ".join(
        part for part in ((facts.meeting_offered.note or "").casefold(), (facts.meeting_comment or "").casefold()) if part
    )

    callback_only_markers = (
        "обратный звонок",
        "обращайся в отдел продаж",
        "обратиться в отдел продаж",
        "менеджера отдела продаж",
        "подробной консультации",
    )
    explicit_meeting_markers = (
        "встреч",
        "показ",
        "офис",
        "онлайн",
        "zoom",
        "видеозвон",
        "созвон",
        "приезж",
    )

    negative_markers = (
        "не конкретная встреча",
        "конкретная встреча не назначена",
    )

    if any(marker in note_text for marker in negative_markers):
        return False
    if any(marker in evidence_text for marker in callback_only_markers) and not any(
        marker in evidence_text for marker in explicit_meeting_markers
    ):
        return False
    return True


def _service_existing_appointment_context(facts: ExtractedCallFacts) -> bool:
    if _is_true(facts.existing_appointment_context) and _is_true(facts.service_follow_up_question):
        return True

    summary = (facts.call_summary or "").casefold()
    cues = [
        "записан на просмотр",
        "записана на просмотр",
        "ранее записанная на просмотр",
        "уже записали на просмотр",
        "хотела уточнить",
        "уточнить планировку",
    ]
    return any(cue in summary for cue in cues)


def _graceful_callback_after_dialog(facts: ExtractedCallFacts) -> bool:
    return (
        _is_true(facts.callback_later_requested)
        and (_is_true(facts.next_step_discussed) or _is_true(facts.follow_up_fixed))
        and _is_true(facts.polite_goodbye)
    )


def _meeting_operationally_confirmed(
    facts: ExtractedCallFacts,
    meeting_type: MeetingType,
    meeting_offered: bool,
    meeting_agreed: bool,
) -> bool:
    if not meeting_offered or not meeting_agreed:
        return False

    if not _is_true(facts.follow_up_fixed):
        return False

    if meeting_type == MeetingType.ONLINE:
        return _is_true(facts.contact_confirmed)

    if meeting_type == MeetingType.NONE:
        return False

    return True


def _client_not_ready_for_meeting(
    facts: ExtractedCallFacts,
    call_status: CallStatus,
    meeting_offered: bool,
    meeting_agreed: bool,
) -> bool:
    if call_status != CallStatus.IN_FUNNEL:
        return False
    if not meeting_offered or meeting_agreed:
        return False

    readiness_signals = [
        _is_true(facts.long_term_buyer),
        _is_true(facts.callback_later_requested),
        _is_true(facts.follow_up_fixed),
        _is_true(facts.passive_material_send),
    ]
    if not any(readiness_signals):
        return False

    return True


def _synchronous_next_step_secured(facts: ExtractedCallFacts) -> bool:
    meeting_type = resolve_meeting_type(facts)
    return _effective_meeting_offered(facts, meeting_type) and _is_true(facts.meeting_agreed)


def _empty_contact_after_greeting(facts: ExtractedCallFacts, has_dialog: bool) -> bool:
    if has_dialog:
        return False

    greeting_present = any(
        signal.evidence
        for signal in (facts.manager_named, facts.company_named, facts.client_name_used)
    )
    if not greeting_present:
        return False

    engagement_signals = [
        facts.need_housing_type,
        facts.need_area,
        facts.need_project_or_area,
        facts.need_purchase_goal,
        facts.need_family_composition,
        facts.budget_discussed,
        facts.payment_method_discussed,
        facts.mortgage_discussed,
        facts.installment_discussed,
        facts.cash_discussed,
        facts.project_or_complex_discussed,
        facts.concrete_object_presented,
        facts.meeting_offered,
        facts.next_step_discussed,
        facts.callback_later_requested,
        facts.non_target_request,
        facts.existing_appointment_context,
        facts.service_follow_up_question,
    ]
    return not any(_is_true(signal) for signal in engagement_signals)


def resolve_call_status(facts: ExtractedCallFacts, policy: ClientPolicy) -> CallStatus:
    has_dialog = substantive_dialog(facts)
    graceful_callback_after_dialog = _graceful_callback_after_dialog(facts)
    synchronous_next_step_secured = _synchronous_next_step_secured(facts)
    empty_contact_after_greeting = _empty_contact_after_greeting(facts, has_dialog)
    service_existing_appointment = (
        policy.existing_appointment_service_calls_non_target
        and _service_existing_appointment_context(facts)
        and not _is_true(facts.budget_discussed)
        and not _is_true(facts.concrete_object_presented)
        and not _is_true(facts.meeting_offered)
    )

    if policy.non_target_out_of_funnel and (_is_true(facts.non_target_request) or service_existing_appointment):
        return CallStatus.OUT_OF_FUNNEL_NON_TARGET

    if (
        policy.interrupted_without_dialog_out_of_funnel
        and (_is_true(facts.interrupted_not_manager_fault) or empty_contact_after_greeting)
        and not has_dialog
    ):
        return CallStatus.OUT_OF_FUNNEL_INTERRUPTED

    if (
        policy.interrupted_after_dialog_out_of_funnel
        and _is_true(facts.interrupted_not_manager_fault)
        and has_dialog
        and not graceful_callback_after_dialog
        and not synchronous_next_step_secured
    ):
        return CallStatus.OUT_OF_FUNNEL_INTERRUPTED_AFTER_DIALOG

    if (
        policy.callback_later_without_dialog_out_of_funnel
        and _is_true(facts.callback_later_requested)
        and not has_dialog
    ):
        return CallStatus.OUT_OF_FUNNEL_CALLBACK_LATER_NO_DIALOG

    return CallStatus.IN_FUNNEL


def _build_stages(
    facts: ExtractedCallFacts,
    call_status: CallStatus,
    meeting_type: MeetingType,
    policy: ClientPolicy,
) -> list[StageEvaluation]:
    if call_status != CallStatus.IN_FUNNEL:
        reason = "Этап не влияет на оценку: звонок исключён из основной воронки."
        return [
            _not_applicable_stage("Приветствие", reason),
            _not_applicable_stage("Выявление потребности", reason),
            _not_applicable_stage("Выявление бюджета", reason),
            _not_applicable_stage("Презентация объекта", reason),
            _not_applicable_stage("Работа с возражениями", reason),
            _not_applicable_stage("Предложение альтернативы", reason),
            _not_applicable_stage("Приглашение на встречу или показ", reason),
            _not_applicable_stage("Закрытие и следующий шаг", reason),
        ]

    payment_specific = (
        _is_true(facts.payment_method_discussed)
        or _is_true(facts.mortgage_discussed)
        or _is_true(facts.installment_discussed)
        or _is_true(facts.cash_discussed)
    )
    effective_meeting_offered = _effective_meeting_offered(facts, meeting_type)
    valid_meeting_offered = effective_meeting_offered and _meeting_type_allowed(policy, meeting_type)

    greeting = _stage_from_criteria(
        "Приветствие",
        [
            ("Менеджер назвал себя", _is_true(facts.manager_named)),
            ("Менеджер назвал компанию", _is_true(facts.company_named)),
            ("Менеджер корректно использовал имя клиента", _is_true(facts.client_name_used)),
        ],
        recommendation="В начале разговора менеджер должен представиться, обозначить компанию и обратиться к клиенту по имени.",
        quote=_first_quote(facts.manager_named, facts.company_named, facts.client_name_used),
    )

    needs = _stage_from_criteria(
        "Выявление потребности",
        [
            ("Уточнён тип жилья", _is_true(facts.need_housing_type)),
            ("Уточнена площадь", _is_true(facts.need_area)),
            ("Уточнены район или ЖК", _is_true(facts.need_project_or_area)),
            ("Выяснена цель покупки", _is_true(facts.need_purchase_goal)),
            ("Уточнён состав семьи или контекст проживания", _is_true(facts.need_family_composition)),
        ],
        recommendation="Нужно системно проходить по потребности: тип жилья, площадь, район, цель покупки и семейный контекст.",
        quote=_first_quote(
            facts.need_housing_type,
            facts.need_area,
            facts.need_project_or_area,
            facts.need_purchase_goal,
            facts.need_family_composition,
        ),
    )

    budget = _stage_from_criteria(
        "Выявление бюджета",
        [
            ("Обсуждён бюджет", _is_true(facts.budget_discussed)),
            ("Обсуждён способ оплаты", payment_specific),
            ("Уточнён первоначальный взнос", _is_true(facts.down_payment_discussed)),
        ],
        recommendation="Перед презентацией нужно выяснить бюджет, способ оплаты и, если есть ипотека, первоначальный взнос.",
        quote=_first_quote(
            facts.budget_discussed,
            facts.payment_method_discussed,
            facts.mortgage_discussed,
            facts.installment_discussed,
            facts.cash_discussed,
            facts.down_payment_discussed,
        ),
    )

    presentation = _stage_from_criteria(
        "Презентация объекта",
        [
            ("Предложен конкретный объект или вариант", _is_true(facts.concrete_object_presented)),
            ("Озвучены преимущества объекта", _is_true(facts.benefits_named)),
            ("Названа цена", _is_true(facts.price_named)),
            ("Презентация связана с потребностью клиента", _is_true(facts.linked_offer_to_need)),
        ],
        recommendation="Презентация должна содержать конкретный объект, цену, преимущества и прямую привязку к запросу клиента.",
        quote=_first_quote(
            facts.concrete_object_presented,
            facts.price_named,
            facts.benefits_named,
            facts.linked_offer_to_need,
        ),
    )

    callback_followup = _is_true(facts.callback_later_requested) and (
        _is_true(facts.next_step_discussed) or _is_true(facts.follow_up_fixed)
    )
    meeting_deferred_after_callback = callback_followup and not _is_true(facts.concrete_object_presented)

    if not _is_true(facts.objection_present):
        objections = _not_applicable_stage(
            "Работа с возражениями",
            "Явных возражений клиента не было, этап не требует отдельного штрафа.",
        )
    else:
        objections = _stage_from_criteria(
            "Работа с возражениями",
            [
                (
                    "Возражение переведено в согласованный следующий шаг",
                    _is_true(facts.objection_handled) or callback_followup,
                ),
                ("Менеджер не ушёл в пассивную отправку материалов", not _is_true(facts.passive_material_send)),
            ],
            recommendation="На возражение нужно отвечать аргументом и не завершать разговор пассивной отправкой материалов без следующего шага.",
            quote=_first_quote(facts.objection_handled, facts.passive_material_send),
        )

    if _is_true(facts.concrete_object_presented) and (_is_true(facts.objection_present) or _is_true(facts.price_above_budget)):
        alternatives = _stage_from_criteria(
            "Предложение альтернативы",
            [("Предложена альтернатива", _is_true(facts.alternative_offered))],
            recommendation="Если первый вариант вызывает сомнение или выходит за бюджет, менеджер должен предлагать альтернативу.",
            quote=_first_quote(facts.alternative_offered),
        )
    else:
        alternatives = _not_applicable_stage_with_score(
            "Предложение альтернативы",
            "До конкретной презентации или явного отказа от первого варианта этап альтернативы не обязателен.",
        )

    if meeting_deferred_after_callback:
        meeting = _not_applicable_stage_with_score(
            "Приглашение на встречу или показ",
            "Клиент перенёс разговор после предметной квалификации; менеджер согласовал повторный контакт до перехода к встрече.",
        )
    else:
        meeting = _stage_from_criteria(
            "Приглашение на встречу или показ",
            [
                ("Предложена встреча или показ", valid_meeting_offered),
                ("Объяснена ценность встречи", _is_true(facts.meeting_value_explained)),
            ],
            recommendation="Нужен явный синхронный следующий шаг: встреча или показ с объяснением пользы для клиента.",
            quote=_first_quote(facts.meeting_offered, facts.meeting_value_explained),
        )

    closing = _stage_from_criteria(
        "Закрытие и следующий шаг",
        [
            ("Зафиксирован следующий шаг", _is_true(facts.next_step_discussed)),
            ("Зафиксированы дата или время следующего контакта", _is_true(facts.follow_up_fixed)),
            ("Подтверждён контакт клиента", _is_true(facts.contact_confirmed)),
            ("Разговор завершён корректно", _is_true(facts.polite_goodbye)),
        ],
        recommendation="Завершение звонка должно фиксировать следующий шаг, время контакта и подтверждение канала связи.",
        quote=_first_quote(
            facts.next_step_discussed,
            facts.follow_up_fixed,
            facts.contact_confirmed,
            facts.polite_goodbye,
        ),
    )

    return [greeting, needs, budget, presentation, objections, alternatives, meeting, closing]


def _build_report_flags(
    facts: ExtractedCallFacts,
    call_status: CallStatus,
    has_dialog: bool,
    meeting_type: MeetingType,
    policy: ClientPolicy,
) -> ReportFlags:
    effective_meeting_offered = _effective_meeting_offered(facts, meeting_type)
    meeting_offered = effective_meeting_offered and _meeting_type_allowed(policy, meeting_type)
    meeting_agreed = meeting_offered and _is_true(facts.meeting_agreed)
    meeting_operationally_confirmed = _meeting_operationally_confirmed(
        facts,
        meeting_type,
        meeting_offered,
        meeting_agreed,
    )
    client_not_ready = _client_not_ready_for_meeting(
        facts,
        call_status,
        meeting_offered,
        meeting_agreed,
    )
    callback_followup = _is_true(facts.callback_later_requested) and (
        _is_true(facts.next_step_discussed) or _is_true(facts.follow_up_fixed)
    )
    meeting_context_ready = (
        _is_true(facts.concrete_object_presented)
        or _is_true(facts.price_named)
        or _is_true(facts.linked_offer_to_need)
        or _is_true(facts.alternative_offered)
    )
    passive_sale = (
        call_status == CallStatus.IN_FUNNEL
        and has_dialog
        and not meeting_offered
        and not callback_followup
    )
    meeting_required_not_done = (
        call_status == CallStatus.IN_FUNNEL
        and has_dialog
        and not meeting_offered
        and meeting_context_ready
        and not (policy.callback_later_with_dialog_allows_followup_without_meeting and callback_followup)
    )

    if effective_meeting_offered and not meeting_offered:
        meeting_result_comment = "Менеджер предложил формат встречи, который не считается целевым для этого клиента."
    elif meeting_offered:
        meeting_result_comment = "Менеджер предложил следующий синхронный шаг."
        if meeting_agreed:
            meeting_result_comment = "Менеджер предложил встречу, клиент согласился."
    elif callback_followup:
        meeting_result_comment = "Менеджер зафиксировал повторный звонок вместо встречи."
    elif call_status == CallStatus.OUT_OF_FUNNEL_INTERRUPTED_AFTER_DIALOG:
        meeting_result_comment = "Разговор оборвался до перехода к встрече или следующему шагу."
    else:
        meeting_result_comment = "Менеджер не предложил встречу или показ."

    passive_sale_comment = None
    if passive_sale:
        passive_sale_comment = facts.meeting_comment or "Разговор завершился без приглашения на встречу или показ."

    meeting_confirmation_comment = None
    if meeting_agreed:
        if meeting_operationally_confirmed:
            if meeting_type == MeetingType.ONLINE:
                meeting_confirmation_comment = (
                    "Онлайн-встреча не только согласована по разговору, но и операционно подтверждена: "
                    "зафиксированы время и рабочий канал дальнейшей связи."
                )
            else:
                meeting_confirmation_comment = (
                    "Встреча операционно подтверждена: зафиксированы дата или время следующего синхронного шага."
                )
        elif meeting_type == MeetingType.ONLINE:
            meeting_confirmation_comment = (
                "Следующий шаг согласован по разговору, но операционное подтверждение онлайн-встречи остаётся неполным: "
                "не хватает надёжно подтверждённого канала или финальной фиксации."
            )
        else:
            meeting_confirmation_comment = (
                "Встреча согласована по разговору, но операционное подтверждение требует дополнительной проверки."
            )

    client_not_ready_comment = None
    if client_not_ready:
        if _is_true(facts.long_term_buyer):
            client_not_ready_comment = (
                "Клиент пока не готов к встрече в этом разговоре: интерес есть, но решение отложено, сначала нужен дополнительный самостоятельный анализ. Работа менеджера не заканчивается — нужен follow-up и возврат к фиксации следующего шага."
            )
        elif _is_true(facts.passive_material_send):
            client_not_ready_comment = (
                "Клиент попросил сначала прислать информацию для самостоятельного изучения и не был готов фиксировать встречу в этом разговоре. Это не закрытый кейс: менеджеру нужен дальнейший follow-up, перезвон и возврат к встрече или другому целевому действию."
            )
        elif callback_followup or _is_true(facts.follow_up_fixed):
            client_not_ready_comment = (
                "Клиент пока не готов фиксировать встречу, но согласован повторный контакт для продолжения работы. Ответственность менеджера сохраняется: следующий шаг нужно дожимать в follow-up."
            )
        else:
            client_not_ready_comment = "Клиент пока не готов к фиксации встречи в этом разговоре. Нужны дальнейшие касания и возврат к следующему целевому действию."

    return ReportFlags(
        call_interrupted=call_status in {CallStatus.OUT_OF_FUNNEL_INTERRUPTED, CallStatus.OUT_OF_FUNNEL_INTERRUPTED_AFTER_DIALOG},
        interrupted_comment=facts.interruption_comment,
        passive_sale=passive_sale,
        passive_sale_comment=passive_sale_comment,
        price_mismatch=_is_true(facts.price_above_budget),
        client_budget=facts.client_budget,
        offered_price=facts.offered_price,
        price_diff_percent=None,
        price_mismatch_comment=facts.price_comment,
        long_term_buyer=_is_true(facts.long_term_buyer),
        long_term_comment=facts.long_term_comment,
        non_target=call_status == CallStatus.OUT_OF_FUNNEL_NON_TARGET,
        non_target_comment=facts.non_target_comment or (
            "Сервисный звонок по уже назначенному просмотру или существующей записи."
            if _service_existing_appointment_context(facts)
            else None
        ),
        meeting_required_not_done=meeting_required_not_done,
        meeting_comment=facts.meeting_comment or ("Согласован повторный звонок вместо предложения встречи." if callback_followup else None),
        meeting_proposed=meeting_offered and meeting_type != MeetingType.NONE,
        meeting_agreed=meeting_agreed,
        meeting_operationally_confirmed=meeting_operationally_confirmed,
        meeting_confirmation_comment=meeting_confirmation_comment,
        client_not_ready=client_not_ready,
        client_not_ready_comment=client_not_ready_comment,
        meeting_result_comment=meeting_result_comment,
    )


def _review_reasons(
    facts: ExtractedCallFacts,
    complex_match: ResidentialComplexMatch,
    meeting_type: MeetingType,
    call_status: CallStatus,
) -> list[str]:
    reasons = []
    effective_meeting_offered = _effective_meeting_offered(facts, meeting_type)
    if complex_match.review_required and complex_match.raw_name:
        reasons.append("Название ЖК распознано неуверенно, нужна ручная проверка.")
    if effective_meeting_offered and meeting_type == MeetingType.NONE:
        reasons.append("Встреча упомянута, но тип встречи не удалось определить.")
    if call_status == CallStatus.IN_FUNNEL and facts.meeting_offered.value is None:
        reasons.append("Нужна ручная проверка факта приглашения на встречу.")
    if facts.non_target_request.value is None and facts.interrupted_not_manager_fault.value is None:
        reasons.append("Не удалось надёжно классифицировать исключения из воронки.")
    return reasons


def _overall_score(stages: list[StageEvaluation]) -> int:
    if not stages:
        return 0
    return int(round(sum(stage.score for stage in stages) / len(stages) * 10))


def _build_summary(
    facts: ExtractedCallFacts,
    call_status: CallStatus,
    has_dialog: bool,
    meeting_type: MeetingType,
    policy: ClientPolicy,
) -> str:
    if facts.call_summary:
        return facts.call_summary

    rc = facts.residential_complex_raw or "неопределённому проекту"
    if call_status == CallStatus.OUT_OF_FUNNEL_INTERRUPTED:
        return "Звонок был прерван не по вине менеджера до предметного диалога и исключён из основной воронки."
    if call_status == CallStatus.OUT_OF_FUNNEL_INTERRUPTED_AFTER_DIALOG:
        return "Предметный диалог начался, но звонок оборвался не по вине менеджера до завершения сценария продажи."
    if call_status == CallStatus.OUT_OF_FUNNEL_CALLBACK_LATER_NO_DIALOG:
        return "Клиент попросил вернуться к разговору позже до предметного обсуждения, звонок исключён из основной воронки."
    if call_status == CallStatus.OUT_OF_FUNNEL_NON_TARGET:
        return "Звонок классифицирован как нецелевой и исключён из основной воронки."

    parts = [f"Звонок по проекту {rc}."]
    effective_meeting_offered = _effective_meeting_offered(facts, meeting_type)
    valid_meeting_offered = effective_meeting_offered and _meeting_type_allowed(policy, meeting_type)
    if has_dialog:
        parts.append("Предметный диалог состоялся.")
    if effective_meeting_offered and not valid_meeting_offered:
        parts.append("Менеджер предложил формат встречи, который не считается целевым для этого клиента.")
    elif effective_meeting_offered:
        meeting_text = "Менеджер предложил встречу."
        if meeting_type == MeetingType.ONLINE:
            meeting_text = "Менеджер предложил онлайн-встречу."
        elif meeting_type == MeetingType.ONSITE:
            meeting_text = "Менеджер предложил очную встречу или показ."
        elif meeting_type == MeetingType.BOTH:
            meeting_text = "Менеджер предложил очную и онлайн-встречу."
        parts.append(meeting_text)
        if _is_true(facts.meeting_agreed):
            parts.append("Клиент согласился.")
    else:
        parts.append("Менеджер не предложил синхронный следующий шаг.")
    return " ".join(parts)


def score_call(
    facts: ExtractedCallFacts,
    complex_match: ResidentialComplexMatch,
    policy: ClientPolicy | None = None,
) -> ScoredCallReport:
    policy = policy or DEFAULT_POLICY
    has_dialog = substantive_dialog(facts)
    call_status = resolve_call_status(facts, policy)
    meeting_type = resolve_meeting_type(facts)
    stages = _build_stages(facts, call_status, meeting_type, policy)
    report_flags = _build_report_flags(facts, call_status, has_dialog, meeting_type, policy)
    review_reasons = _review_reasons(facts, complex_match, meeting_type, call_status)
    score_applicable = call_status == CallStatus.IN_FUNNEL

    low_scoring = [stage for stage in stages if stage.score < 6]
    high_scoring = [stage for stage in stages if stage.score >= 8]

    critical_misses = [f"{stage.stage_name}: {stage.what_was_missed}" for stage in low_scoring[:3] if stage.what_was_missed]
    top_strengths = [f"{stage.stage_name}: {stage.what_was_done}" for stage in high_scoring[:3] if stage.what_was_done]
    priority_improvements = [stage.recommendation for stage in low_scoring[:3] if stage.recommendation]

    return ScoredCallReport(
        analysis_version=ANALYSIS_VERSION,
        call_id=facts.call_id,
        manager_name=facts.manager_name,
        overall_score=_overall_score(stages),
        score_applicable=score_applicable,
        call_summary=_build_summary(facts, call_status, has_dialog, meeting_type, policy),
        residential_complex=complex_match.normalized_name,
        residential_complex_raw=complex_match.raw_name,
        substantive_dialog=has_dialog,
        call_status=call_status,
        in_funnel=score_applicable,
        review_required=bool(review_reasons),
        review_reasons=review_reasons,
        stages=stages,
        critical_misses=critical_misses,
        top_strengths=top_strengths,
        priority_improvements=priority_improvements,
        report_flags=report_flags,
    )
