from __future__ import annotations

import json
import unittest
from pathlib import Path

from expert_overrides import apply_expert_overrides_to_result
from storage import load_all_results


BASE_DIR = Path(__file__).resolve().parents[1]
FIXTURE_PATH = BASE_DIR / "reference" / "a101_regression_fixture.json"


def _load_fixture() -> list[dict]:
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _load_actual_results() -> dict[str, dict]:
    rows = [apply_expert_overrides_to_result(row) for row in load_all_results()]
    return {str(row.get("phone")): row for row in rows}


class A101RegressionTest(unittest.TestCase):
    def test_fixture_calls_are_present(self):
        fixture = _load_fixture()
        actual = _load_actual_results()
        missing = [item["call_id"] for item in fixture if item["call_id"] not in actual]
        self.assertEqual(missing, [], f"В результатах отсутствуют звонки из эталонного набора: {missing}")

    def test_expected_outputs_match_fixture(self):
        fixture = _load_fixture()
        actual = _load_actual_results()

        for item in fixture:
            with self.subTest(call_id=item["call_id"]):
                row = actual[item["call_id"]]
                analysis = row.get("analysis", {})
                flags = analysis.get("report_flags", {})

                self.assertEqual(
                    analysis.get("call_status"),
                    item["expected_call_status"],
                    "Статус звонка отличается от эталона.",
                )
                self.assertEqual(
                    analysis.get("in_funnel"),
                    item["expected_in_funnel"],
                    "Признак принадлежности к основной воронке отличается от эталона.",
                )
                self.assertEqual(
                    analysis.get("review_required"),
                    item["expected_review_required"],
                    "Флаг экспертной проверки отличается от эталона.",
                )
                self.assertEqual(
                    analysis.get("residential_complex"),
                    item["expected_residential_complex"],
                    "Нормализованное название ЖК отличается от эталона.",
                )

                for flag_name, expected_value in item["expected_flags"].items():
                    self.assertEqual(
                        flags.get(flag_name),
                        expected_value,
                        f"Флаг `{flag_name}` отличается от эталона.",
                    )


if __name__ == "__main__":
    unittest.main()
