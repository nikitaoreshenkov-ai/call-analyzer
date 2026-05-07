from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


ANALYSIS_VERSION = "v1-beta"


class MeetingType(str, Enum):
    NONE = "none"
    ONSITE = "onsite"
    ONLINE = "online"
    BOTH = "both"


class CallStatus(str, Enum):
    IN_FUNNEL = "in_funnel"
    OUT_OF_FUNNEL_INTERRUPTED = "out_of_funnel_interrupted"
    OUT_OF_FUNNEL_INTERRUPTED_AFTER_DIALOG = "out_of_funnel_interrupted_after_dialog"
    OUT_OF_FUNNEL_CALLBACK_LATER_NO_DIALOG = "out_of_funnel_callback_later_no_dialog"
    OUT_OF_FUNNEL_NON_TARGET = "out_of_funnel_non_target"


class EvidenceQuote(BaseModel):
    text: str = ""
    speaker: Optional[str] = None
    timestamp: Optional[str] = None


class CriterionSignal(BaseModel):
    value: Optional[bool] = None
    evidence: list[EvidenceQuote] = Field(default_factory=list)
    note: Optional[str] = None


class ResidentialComplexMatch(BaseModel):
    raw_name: Optional[str] = None
    normalized_name: str = "Не определён"
    confidence: float = 0.0
    review_required: bool = False


class ClientPolicy(BaseModel):
    valid_meeting_types: set[MeetingType] = Field(
        default_factory=lambda: {MeetingType.ONSITE, MeetingType.ONLINE, MeetingType.BOTH}
    )
    callback_later_without_dialog_out_of_funnel: bool = True
    interrupted_without_dialog_out_of_funnel: bool = True
    interrupted_after_dialog_out_of_funnel: bool = True
    non_target_out_of_funnel: bool = True
    callback_later_with_dialog_allows_followup_without_meeting: bool = True
    existing_appointment_service_calls_non_target: bool = True


class ExtractedCallFacts(BaseModel):
    call_id: str
    manager_name: str = "Менеджер"
    call_summary: str = ""
    residential_complex_raw: Optional[str] = None

    manager_named: CriterionSignal = Field(default_factory=CriterionSignal)
    company_named: CriterionSignal = Field(default_factory=CriterionSignal)
    client_name_used: CriterionSignal = Field(default_factory=CriterionSignal)

    need_housing_type: CriterionSignal = Field(default_factory=CriterionSignal)
    need_area: CriterionSignal = Field(default_factory=CriterionSignal)
    need_project_or_area: CriterionSignal = Field(default_factory=CriterionSignal)
    need_purchase_goal: CriterionSignal = Field(default_factory=CriterionSignal)
    need_family_composition: CriterionSignal = Field(default_factory=CriterionSignal)

    budget_discussed: CriterionSignal = Field(default_factory=CriterionSignal)
    payment_method_discussed: CriterionSignal = Field(default_factory=CriterionSignal)
    mortgage_discussed: CriterionSignal = Field(default_factory=CriterionSignal)
    installment_discussed: CriterionSignal = Field(default_factory=CriterionSignal)
    cash_discussed: CriterionSignal = Field(default_factory=CriterionSignal)
    down_payment_discussed: CriterionSignal = Field(default_factory=CriterionSignal)

    project_or_complex_discussed: CriterionSignal = Field(default_factory=CriterionSignal)
    concrete_object_presented: CriterionSignal = Field(default_factory=CriterionSignal)
    price_named: CriterionSignal = Field(default_factory=CriterionSignal)
    benefits_named: CriterionSignal = Field(default_factory=CriterionSignal)
    linked_offer_to_need: CriterionSignal = Field(default_factory=CriterionSignal)

    objection_present: CriterionSignal = Field(default_factory=CriterionSignal)
    objection_handled: CriterionSignal = Field(default_factory=CriterionSignal)
    passive_material_send: CriterionSignal = Field(default_factory=CriterionSignal)

    alternative_offered: CriterionSignal = Field(default_factory=CriterionSignal)

    meeting_offered: CriterionSignal = Field(default_factory=CriterionSignal)
    onsite_meeting_offered: CriterionSignal = Field(default_factory=CriterionSignal)
    online_meeting_offered: CriterionSignal = Field(default_factory=CriterionSignal)
    meeting_value_explained: CriterionSignal = Field(default_factory=CriterionSignal)
    meeting_agreed: CriterionSignal = Field(default_factory=CriterionSignal)

    next_step_discussed: CriterionSignal = Field(default_factory=CriterionSignal)
    follow_up_fixed: CriterionSignal = Field(default_factory=CriterionSignal)
    contact_confirmed: CriterionSignal = Field(default_factory=CriterionSignal)
    polite_goodbye: CriterionSignal = Field(default_factory=CriterionSignal)

    callback_later_requested: CriterionSignal = Field(default_factory=CriterionSignal)
    interrupted_not_manager_fault: CriterionSignal = Field(default_factory=CriterionSignal)
    non_target_request: CriterionSignal = Field(default_factory=CriterionSignal)
    existing_appointment_context: CriterionSignal = Field(default_factory=CriterionSignal)
    service_follow_up_question: CriterionSignal = Field(default_factory=CriterionSignal)

    price_above_budget: CriterionSignal = Field(default_factory=CriterionSignal)
    long_term_buyer: CriterionSignal = Field(default_factory=CriterionSignal)

    client_budget: Optional[str] = None
    offered_price: Optional[str] = None
    callback_comment: Optional[str] = None
    interruption_comment: Optional[str] = None
    non_target_comment: Optional[str] = None
    price_comment: Optional[str] = None
    long_term_comment: Optional[str] = None
    meeting_comment: Optional[str] = None


class StageEvaluation(BaseModel):
    stage_name: str
    completed: bool
    score: int
    what_was_done: str = ""
    what_was_missed: str = ""
    quote: str = ""
    recommendation: str = ""


class ReportFlags(BaseModel):
    call_interrupted: bool = False
    interrupted_comment: Optional[str] = None
    passive_sale: bool = False
    passive_sale_comment: Optional[str] = None
    price_mismatch: bool = False
    client_budget: Optional[str] = None
    offered_price: Optional[str] = None
    price_diff_percent: Optional[float] = None
    price_mismatch_comment: Optional[str] = None
    long_term_buyer: bool = False
    long_term_comment: Optional[str] = None
    non_target: bool = False
    non_target_comment: Optional[str] = None
    meeting_required_not_done: bool = False
    meeting_comment: Optional[str] = None
    meeting_proposed: bool = False
    meeting_agreed: bool = False
    meeting_operationally_confirmed: bool = False
    meeting_confirmation_comment: Optional[str] = None
    client_not_ready: bool = False
    client_not_ready_comment: Optional[str] = None
    meeting_result_comment: Optional[str] = None


class ScoredCallReport(BaseModel):
    analysis_version: str = ANALYSIS_VERSION
    call_id: str
    manager_name: str = "Менеджер"
    n_chunks: int = 1
    overall_score: int
    score_applicable: bool = True
    call_summary: str
    residential_complex: str = "Не определён"
    residential_complex_raw: Optional[str] = None
    substantive_dialog: bool = False
    call_status: CallStatus = CallStatus.IN_FUNNEL
    in_funnel: bool = True
    review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    stages: list[StageEvaluation] = Field(default_factory=list)
    critical_misses: list[str] = Field(default_factory=list)
    top_strengths: list[str] = Field(default_factory=list)
    priority_improvements: list[str] = Field(default_factory=list)
    report_flags: ReportFlags = Field(default_factory=ReportFlags)
