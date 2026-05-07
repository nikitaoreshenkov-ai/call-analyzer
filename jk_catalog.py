from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher

from client_paths import DEFAULT_CLIENT_ID, reference_file_candidates
from models_v1 import ResidentialComplexMatch


REFERENCE_DIR = os.path.join(os.path.dirname(__file__), "reference")
REFERENCE_JK_PATH = os.path.join(REFERENCE_DIR, "jk_names.txt")
REFERENCE_JK_ALIASES_PATH = os.path.join(REFERENCE_DIR, "jk_aliases.json")


def load_reference_jk_names(path: str | None = None, client_id: str = DEFAULT_CLIENT_ID) -> list[str]:
    if path is None:
        path = next((candidate for candidate in reference_file_candidates("jk_names.txt", client_id) if os.path.exists(candidate)), REFERENCE_JK_PATH)
    if not os.path.exists(path):
        return []

    names = []
    seen = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def load_reference_jk_aliases(path: str | None = None, client_id: str = DEFAULT_CLIENT_ID) -> dict[str, list[str]]:
    if path is None:
        path = next((candidate for candidate in reference_file_candidates("jk_aliases.json", client_id) if os.path.exists(candidate)), REFERENCE_JK_ALIASES_PATH)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {key: value for key, value in raw.items() if isinstance(value, list)}


def merge_jk_names(reference_names: list[str], custom_names: list[str]) -> list[str]:
    merged = []
    seen = set()
    for name in reference_names + custom_names:
        normalized = name.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged


def _normalize_token(text: str) -> str:
    cleaned = text.casefold().replace("ё", "е")
    cleaned = re.sub(r"[^a-zа-я0-9]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _significant_tokens(normalized_name: str) -> list[str]:
    tokens = []
    for token in normalized_name.split():
        if len(token) <= 2:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
    return tokens


class HousingComplexCatalog:
    def __init__(self, names: list[str], aliases: dict[str, list[str]] | None = None):
        self.names = names
        self._normalized_pairs = [(name, _normalize_token(name)) for name in names]
        self._token_pairs = [(name, _significant_tokens(normalized_name)) for name, normalized_name in self._normalized_pairs]
        self.aliases = aliases or {}
        self._normalized_aliases = {}
        for canonical_name, alias_values in self.aliases.items():
            if canonical_name not in self.names:
                continue
            alias_tokens = {_normalize_token(canonical_name)}
            alias_tokens.update(_normalize_token(alias) for alias in alias_values if alias)
            self._normalized_aliases[canonical_name] = {token for token in alias_tokens if token}

    @classmethod
    def from_names(cls, names: list[str], aliases: dict[str, list[str]] | None = None) -> "HousingComplexCatalog":
        return cls(names, aliases=aliases)

    @classmethod
    def from_reference(cls, extra_names: list[str] | None = None, client_id: str = DEFAULT_CLIENT_ID) -> "HousingComplexCatalog":
        reference_names = load_reference_jk_names(client_id=client_id)
        return cls(
            merge_jk_names(reference_names, extra_names or []),
            aliases=load_reference_jk_aliases(client_id=client_id),
        )

    def normalize(self, raw_name: str | None) -> ResidentialComplexMatch:
        if not raw_name:
            return ResidentialComplexMatch()

        raw_token = _normalize_token(raw_name)
        if not raw_token:
            return ResidentialComplexMatch(raw_name=raw_name)

        for canonical_name, alias_tokens in self._normalized_aliases.items():
            if raw_token in alias_tokens:
                return ResidentialComplexMatch(
                    raw_name=raw_name,
                    normalized_name=canonical_name,
                    confidence=0.99,
                    review_required=False,
                )

        best_name = None
        best_score = 0.0
        second_best_score = 0.0
        for idx, (name, normalized_name) in enumerate(self._normalized_pairs):
            if raw_token == normalized_name:
                return ResidentialComplexMatch(
                    raw_name=raw_name,
                    normalized_name=name,
                    confidence=1.0,
                    review_required=False,
                )

            score = SequenceMatcher(None, raw_token, normalized_name).ratio()
            if raw_token in normalized_name or normalized_name in raw_token:
                score = max(score, 0.93)
            for token in self._token_pairs[idx][1]:
                token_score = SequenceMatcher(None, raw_token, token).ratio()
                if raw_token in token or token in raw_token:
                    token_score = max(token_score, 0.94)
                score = max(score, min(token_score, 0.95))
            if score > best_score or (
                abs(score - best_score) < 0.015 and best_name is not None and len(name) < len(best_name)
            ):
                second_best_score = best_score
                best_score = score
                best_name = name
            elif score > second_best_score:
                second_best_score = score

        if not best_name:
            return ResidentialComplexMatch(raw_name=raw_name)

        assign_threshold = 0.6
        is_ambiguous = second_best_score and (best_score - second_best_score) < 0.06

        return ResidentialComplexMatch(
            raw_name=raw_name,
            normalized_name=best_name if best_score >= assign_threshold else "Не определён",
            confidence=round(best_score, 3),
            review_required=best_score < 0.9 or is_ambiguous,
        )
