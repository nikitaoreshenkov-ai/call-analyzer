from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from typing import Any

from client_paths import DEFAULT_CLIENT_ID, reference_file_candidates
from jk_catalog import HousingComplexCatalog, load_reference_jk_aliases, load_reference_jk_names
from models_v1 import ANALYSIS_VERSION, ExtractedCallFacts
from policy_config import load_client_policy
from rule_engine import score_call
from storage import load_json_artifact


REFERENCE_DIR = os.path.join(os.path.dirname(__file__), "reference")
EXPERT_OVERRIDES_PATH = os.path.join(REFERENCE_DIR, "expert_overrides.json")


@lru_cache(maxsize=16)
def load_expert_overrides(path: str | None = None, client_id: str = DEFAULT_CLIENT_ID) -> dict[str, dict[str, Any]]:
    if path is None:
        path = next(
            (candidate for candidate in reference_file_candidates("expert_overrides.json", client_id) if os.path.exists(candidate)),
            EXPERT_OVERRIDES_PATH,
        )
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {str(key): value for key, value in raw.items() if isinstance(value, dict)}


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@lru_cache(maxsize=16)
def _catalog(client_id: str = DEFAULT_CLIENT_ID) -> HousingComplexCatalog:
    return HousingComplexCatalog.from_names(
        load_reference_jk_names(client_id=client_id),
        aliases=load_reference_jk_aliases(client_id=client_id),
    )


def _analysis_needs_rebuild(analysis: dict[str, Any]) -> bool:
    report_flags = analysis.get("report_flags", {})
    return (
        analysis.get("analysis_version") != ANALYSIS_VERSION
        or
        "meeting_operationally_confirmed" not in report_flags
        or "client_not_ready" not in report_flags
    )


def _rebuild_analysis_from_facts(phone: str, fallback_analysis: dict[str, Any], client_id: str = DEFAULT_CLIENT_ID) -> dict[str, Any]:
    facts_payload = load_json_artifact(phone, "facts.json", client_id=client_id)
    if not facts_payload:
        return fallback_analysis

    facts = ExtractedCallFacts.model_validate(facts_payload)
    complex_match = _catalog(client_id).normalize(facts.residential_complex_raw)
    return score_call(
        facts,
        complex_match,
        policy=load_client_policy(client_id=client_id),
    ).model_dump(mode="json")


def apply_expert_overrides_to_result(row: dict, client_id: str = DEFAULT_CLIENT_ID) -> dict:
    phone = str(row.get("phone", "")).strip()
    overrides = load_expert_overrides(client_id=client_id)
    override = overrides.get(phone)

    patched = copy.deepcopy(row)
    analysis = copy.deepcopy(patched.get("analysis", {}))

    if _analysis_needs_rebuild(analysis):
        analysis = _rebuild_analysis_from_facts(phone, analysis, client_id=client_id)

    if not override:
        patched["analysis"] = analysis
        return patched

    facts_override = override.get("fact_overrides")
    if isinstance(facts_override, dict):
        facts_payload = load_json_artifact(phone, "facts.json", client_id=client_id)
        if facts_payload:
            merged_payload = _deep_merge(facts_payload, facts_override)
            facts = ExtractedCallFacts.model_validate(merged_payload)
            complex_match = _catalog(client_id).normalize(facts.residential_complex_raw)
            analysis = score_call(
                facts,
                complex_match,
                policy=load_client_policy(client_id=client_id),
            ).model_dump(mode="json")

    if isinstance(override.get("analysis_overrides"), dict):
        analysis = _deep_merge(analysis, override["analysis_overrides"])

    if isinstance(override.get("report_flag_overrides"), dict):
        report_flags = copy.deepcopy(analysis.get("report_flags", {}))
        report_flags = _deep_merge(report_flags, override["report_flag_overrides"])
        analysis["report_flags"] = report_flags

    append_review_reasons = override.get("append_review_reasons")
    if isinstance(append_review_reasons, list):
        reasons = list(analysis.get("review_reasons", []))
        for reason in append_review_reasons:
            if isinstance(reason, str) and reason and reason not in reasons:
                reasons.append(reason)
        analysis["review_reasons"] = reasons

    if "review_required" in analysis and not analysis.get("review_required"):
        analysis["review_reasons"] = analysis.get("review_reasons", [])

    expert_note = override.get("expert_note")
    if isinstance(expert_note, str) and expert_note.strip():
        analysis["expert_note"] = expert_note.strip()

    patched["analysis"] = analysis
    return patched
