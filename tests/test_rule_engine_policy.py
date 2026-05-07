from __future__ import annotations

import unittest

from models_v1 import (
    CallStatus,
    ClientPolicy,
    CriterionSignal,
    ExtractedCallFacts,
    MeetingType,
    ResidentialComplexMatch,
)
from rule_engine import score_call


def _true_signal() -> CriterionSignal:
    return CriterionSignal(value=True)


class RuleEngineMeetingPolicyTest(unittest.TestCase):
    def test_online_meeting_is_not_counted_when_client_accepts_only_onsite(self):
        facts = ExtractedCallFacts(
            call_id="policy-online-invalid",
            call_summary="",
            need_housing_type=_true_signal(),
            budget_discussed=_true_signal(),
            concrete_object_presented=_true_signal(),
            price_named=_true_signal(),
            linked_offer_to_need=_true_signal(),
            meeting_offered=_true_signal(),
            online_meeting_offered=_true_signal(),
            meeting_agreed=_true_signal(),
            meeting_value_explained=_true_signal(),
        )
        policy = ClientPolicy(valid_meeting_types={MeetingType.ONSITE})

        report = score_call(facts, ResidentialComplexMatch(), policy)

        self.assertEqual(report.call_status, CallStatus.IN_FUNNEL)
        self.assertFalse(report.report_flags.meeting_proposed)
        self.assertFalse(report.report_flags.meeting_agreed)
        self.assertTrue(report.report_flags.meeting_required_not_done)

    def test_both_formats_count_if_one_of_them_is_allowed(self):
        facts = ExtractedCallFacts(
            call_id="policy-both-valid",
            call_summary="",
            need_housing_type=_true_signal(),
            budget_discussed=_true_signal(),
            concrete_object_presented=_true_signal(),
            price_named=_true_signal(),
            linked_offer_to_need=_true_signal(),
            meeting_offered=_true_signal(),
            onsite_meeting_offered=_true_signal(),
            online_meeting_offered=_true_signal(),
            meeting_agreed=_true_signal(),
            meeting_value_explained=_true_signal(),
            next_step_discussed=_true_signal(),
            follow_up_fixed=_true_signal(),
        )
        policy = ClientPolicy(valid_meeting_types={MeetingType.ONSITE})

        report = score_call(facts, ResidentialComplexMatch(), policy)

        self.assertTrue(report.report_flags.meeting_proposed)
        self.assertTrue(report.report_flags.meeting_agreed)
        self.assertTrue(report.report_flags.meeting_operationally_confirmed)


if __name__ == "__main__":
    unittest.main()
