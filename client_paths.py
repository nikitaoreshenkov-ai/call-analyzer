from __future__ import annotations

import os
import re


BASE_DIR = os.path.dirname(__file__)
RESULTS_ROOT_DIR = os.path.join(BASE_DIR, "results")
ARTIFACTS_ROOT_DIR = os.path.join(BASE_DIR, "artifacts")
REFERENCE_ROOT_DIR = os.path.join(BASE_DIR, "reference")
DEFAULT_CLIENT_ID = "default"


def normalize_client_id(raw_client_id: str | None) -> str:
    if not raw_client_id:
        return DEFAULT_CLIENT_ID

    collapsed = re.sub(r"\s+", "_", raw_client_id.strip().casefold())
    safe = re.sub(r"[^a-z0-9._-]+", "_", collapsed).strip("._-")
    return safe or DEFAULT_CLIENT_ID


def client_results_dir(client_id: str | None = None) -> str:
    return os.path.join(RESULTS_ROOT_DIR, normalize_client_id(client_id))


def client_artifacts_dir(client_id: str | None = None) -> str:
    return os.path.join(ARTIFACTS_ROOT_DIR, normalize_client_id(client_id))


def client_reference_dir(client_id: str | None = None) -> str:
    return os.path.join(REFERENCE_ROOT_DIR, normalize_client_id(client_id))


def result_dirs_for_read(client_id: str | None = None) -> list[str]:
    normalized = normalize_client_id(client_id)
    dirs = [client_results_dir(normalized)]
    if normalized == DEFAULT_CLIENT_ID:
        dirs.append(RESULTS_ROOT_DIR)
    return dirs


def artifact_dirs_for_read(call_id: str, client_id: str | None = None) -> list[str]:
    normalized = normalize_client_id(client_id)
    dirs = [os.path.join(client_artifacts_dir(normalized), call_id)]
    if normalized == DEFAULT_CLIENT_ID:
        dirs.append(os.path.join(ARTIFACTS_ROOT_DIR, call_id))
    return dirs


def reference_file_candidates(filename: str, client_id: str | None = None) -> list[str]:
    normalized = normalize_client_id(client_id)
    candidates = [os.path.join(client_reference_dir(normalized), filename)]
    candidates.append(os.path.join(REFERENCE_ROOT_DIR, filename))
    return candidates


def list_available_client_ids() -> list[str]:
    client_ids = set()

    for root_dir in (RESULTS_ROOT_DIR, ARTIFACTS_ROOT_DIR, REFERENCE_ROOT_DIR):
        if not os.path.isdir(root_dir):
            continue
        for name in os.listdir(root_dir):
            path = os.path.join(root_dir, name)
            if os.path.isdir(path):
                client_ids.add(name)

    if os.path.isdir(RESULTS_ROOT_DIR):
        if any(name.endswith(".json") for name in os.listdir(RESULTS_ROOT_DIR)):
            client_ids.add(DEFAULT_CLIENT_ID)
    if os.path.isdir(ARTIFACTS_ROOT_DIR):
        if any(os.path.isdir(os.path.join(ARTIFACTS_ROOT_DIR, name)) for name in os.listdir(ARTIFACTS_ROOT_DIR)):
            client_ids.add(DEFAULT_CLIENT_ID)
    if os.path.isdir(REFERENCE_ROOT_DIR):
        if any(os.path.isfile(os.path.join(REFERENCE_ROOT_DIR, name)) for name in os.listdir(REFERENCE_ROOT_DIR)):
            client_ids.add(DEFAULT_CLIENT_ID)

    if not client_ids:
        return [DEFAULT_CLIENT_ID]
    return sorted(client_ids)
