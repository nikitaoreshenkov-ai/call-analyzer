from __future__ import annotations

import unittest

from report_text import normalize_missed_text


class ReportTextNormalizationTest(unittest.TestCase):
    def test_empty_text_returns_dash(self):
        self.assertEqual(normalize_missed_text(""), "—")
        self.assertEqual(normalize_missed_text(None), "—")

    def test_single_positive_phrase_is_inverted(self):
        self.assertEqual(
            normalize_missed_text("Менеджер назвал себя"),
            "Менеджер не представился",
        )

    def test_multiple_phrases_are_inverted(self):
        source = "Предложен конкретный объект или вариант; Названа цена; Презентация связана с потребностью клиента"
        expected = "Не предложен конкретный объект или вариант; Не названа цена; Презентация не связана с потребностью клиента"
        self.assertEqual(normalize_missed_text(source), expected)

    def test_contact_confirmation_normalizes_both_spellings(self):
        self.assertEqual(
            normalize_missed_text("Подтверждён контакт клиента"),
            "Не подтверждён контакт клиента",
        )
        self.assertEqual(
            normalize_missed_text("Подтвержден контакт клиента"),
            "Не подтверждён контакт клиента",
        )

    def test_unknown_text_is_left_unchanged(self):
        source = "Нестандартная формулировка модели"
        self.assertEqual(normalize_missed_text(source), source)


if __name__ == "__main__":
    unittest.main()
