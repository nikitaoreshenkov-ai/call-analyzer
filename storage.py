from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from client_paths import (
    ARTIFACTS_ROOT_DIR,
    DEFAULT_CLIENT_ID,
    RESULTS_ROOT_DIR,
    artifact_dirs_for_read,
    client_artifacts_dir,
    client_results_dir,
    normalize_client_id,
    result_dirs_for_read,
)

def _ensure_dirs(client_id: str | None = None):
    os.makedirs(RESULTS_ROOT_DIR, exist_ok=True)
    os.makedirs(ARTIFACTS_ROOT_DIR, exist_ok=True)
    os.makedirs(client_results_dir(client_id), exist_ok=True)
    os.makedirs(client_artifacts_dir(client_id), exist_ok=True)


def _safe_call_id(call_id: str) -> str:
    collapsed = re.sub(r"\s+", "_", call_id.strip())
    return re.sub(r"[^A-Za-z0-9А-Яа-я._-]+", "_", collapsed)


def artifact_dir(call_id: str, client_id: str | None = None) -> str:
    _ensure_dirs(client_id)
    return os.path.join(client_artifacts_dir(client_id), _safe_call_id(call_id))


def save_json_artifact(call_id: str, artifact_name: str, payload: Any, client_id: str | None = None) -> str:
    call_dir = artifact_dir(call_id, client_id=client_id)
    os.makedirs(call_dir, exist_ok=True)
    out_path = os.path.join(call_dir, artifact_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


def load_json_artifact(call_id: str, artifact_name: str, client_id: str | None = None) -> dict | None:
    safe_call_id = _safe_call_id(call_id)
    for call_dir in artifact_dirs_for_read(safe_call_id, client_id=client_id):
        path = os.path.join(call_dir, artifact_name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_result(
    phone: str,
    filename: str,
    analysis: dict,
    n_chunks: int,
    transcript: str | None = None,
    extracted_facts: dict | None = None,
    client_id: str = DEFAULT_CLIENT_ID,
):
    normalized_client_id = normalize_client_id(client_id)
    _ensure_dirs(normalized_client_id)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_call_id = _safe_call_id(phone)
    analyzed_at = datetime.now().isoformat()

    payload = {
        "client_id": normalized_client_id,
        "phone": phone,
        "filename": filename,
        "analyzed_at": analyzed_at,
        "n_chunks": n_chunks,
        "analysis": analysis,
    }

    out_path = os.path.join(client_results_dir(normalized_client_id), f"{safe_call_id}_{timestamp}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    save_json_artifact(
        phone,
        "metadata.json",
        {
            "client_id": normalized_client_id,
            "call_id": phone,
            "filename": filename,
            "analyzed_at": analyzed_at,
            "n_chunks": n_chunks,
            "latest_summary_result": out_path,
        },
        client_id=normalized_client_id,
    )
    if transcript is not None:
        save_json_artifact(
            phone,
            "transcript.json",
            {"client_id": normalized_client_id, "call_id": phone, "text": transcript},
            client_id=normalized_client_id,
        )
    if extracted_facts is not None:
        save_json_artifact(phone, "facts.json", extracted_facts, client_id=normalized_client_id)
    save_json_artifact(phone, "report.json", analysis, client_id=normalized_client_id)

    return out_path


def already_processed(call_id: str, client_id: str = DEFAULT_CLIENT_ID) -> bool:
    normalized_client_id = normalize_client_id(client_id)
    _ensure_dirs(normalized_client_id)
    safe_call_id = _safe_call_id(call_id)
    for call_dir in artifact_dirs_for_read(safe_call_id, client_id=normalized_client_id):
        report_path = os.path.join(call_dir, "report.json")
        if os.path.exists(report_path):
            return True

    for results_dir in result_dirs_for_read(normalized_client_id):
        if not os.path.isdir(results_dir):
            continue
        for fname in os.listdir(results_dir):
            if fname.startswith(safe_call_id) and fname.endswith(".json"):
                return True
    return False


def load_all_results(client_id: str = DEFAULT_CLIENT_ID) -> list[dict]:
    normalized_client_id = normalize_client_id(client_id)
    _ensure_dirs(normalized_client_id)
    latest_by_phone: dict[str, dict] = {}
    for results_dir in result_dirs_for_read(normalized_client_id):
        if not os.path.isdir(results_dir):
            continue
        for fname in sorted(os.listdir(results_dir), reverse=True):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(results_dir, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    row = json.load(f)
            except Exception:
                continue
            row.setdefault("client_id", normalized_client_id)
            phone = row.get("phone")
            analyzed_at = row.get("analyzed_at", "")
            current = latest_by_phone.get(phone)
            if current is None or analyzed_at > current.get("analyzed_at", ""):
                latest_by_phone[phone] = row
    return sorted(latest_by_phone.values(), key=lambda x: x.get("analyzed_at", ""), reverse=True)
