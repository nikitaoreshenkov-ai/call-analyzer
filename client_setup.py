from __future__ import annotations

import json
import os
from typing import Any

from client_paths import client_artifacts_dir, client_reference_dir, client_results_dir, normalize_client_id
from policy_config import DEFAULT_POLICY_PATH


CLIENT_REFERENCE_README = """# Клиентский контур

В этой папке лежат настройки и справочники конкретного клиента.

Файлы:
- `client_policy.json` — правила воронки и допустимые форматы встреч
- `jk_names.txt` — список ЖК клиента, по одному названию на строке
- `jk_aliases.json` — алиасы и искажённые варианты названий ЖК
- `expert_overrides.json` — редкие ручные корректировки спорных кейсов
"""


def _write_json_if_missing(path: str, payload: Any) -> bool:
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return True


def _write_text_if_missing(path: str, text: str) -> bool:
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def ensure_client_template(client_id: str) -> dict[str, Any]:
    normalized_client_id = normalize_client_id(client_id)
    reference_dir = client_reference_dir(normalized_client_id)
    results_dir = client_results_dir(normalized_client_id)
    artifacts_dir = client_artifacts_dir(normalized_client_id)

    os.makedirs(reference_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    with open(DEFAULT_POLICY_PATH, encoding="utf-8") as f:
        default_policy = json.load(f)

    created_files: list[str] = []
    if _write_json_if_missing(os.path.join(reference_dir, "client_policy.json"), default_policy):
        created_files.append("client_policy.json")
    if _write_text_if_missing(os.path.join(reference_dir, "jk_names.txt"), ""):
        created_files.append("jk_names.txt")
    if _write_json_if_missing(os.path.join(reference_dir, "jk_aliases.json"), {}):
        created_files.append("jk_aliases.json")
    if _write_json_if_missing(os.path.join(reference_dir, "expert_overrides.json"), {}):
        created_files.append("expert_overrides.json")
    if _write_text_if_missing(os.path.join(reference_dir, "README.md"), CLIENT_REFERENCE_README):
        created_files.append("README.md")

    return {
        "client_id": normalized_client_id,
        "reference_dir": reference_dir,
        "results_dir": results_dir,
        "artifacts_dir": artifacts_dir,
        "created_files": created_files,
    }
