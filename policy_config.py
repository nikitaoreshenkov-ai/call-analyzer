from __future__ import annotations

import json
import os

from client_paths import DEFAULT_CLIENT_ID, reference_file_candidates
from models_v1 import ClientPolicy, MeetingType


REFERENCE_DIR = os.path.join(os.path.dirname(__file__), "reference")
DEFAULT_POLICY_PATH = os.path.join(REFERENCE_DIR, "client_policy.json")


def load_client_policy(path: str | None = None, client_id: str = DEFAULT_CLIENT_ID) -> ClientPolicy:
    if path is None:
        path = next(
            (candidate for candidate in reference_file_candidates("client_policy.json", client_id) if os.path.exists(candidate)),
            DEFAULT_POLICY_PATH,
        )
    if not os.path.exists(path):
        return ClientPolicy()

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    return ClientPolicy.model_validate(raw)


def meeting_types_label(policy: ClientPolicy) -> str:
    labels = {
        MeetingType.ONSITE: "очная",
        MeetingType.ONLINE: "онлайн",
        MeetingType.BOTH: "оба типа",
    }
    ordered = [labels[t] for t in (MeetingType.ONSITE, MeetingType.ONLINE, MeetingType.BOTH) if t in policy.valid_meeting_types]
    return ", ".join(ordered) if ordered else "не выбрано"
