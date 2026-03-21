from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence


DEFAULT_OWNERSHIP_RULES_PATH = Path(__file__).resolve().parent / "seeds" / "doc_ownership.json"


@dataclass(frozen=True)
class OwnershipRule:
    code_prefix: str
    doc_prefix: str
    score_boost: int = 32
    description: str = ""


def normalize_prefix(value: str) -> str:
    normalized = value.strip().lstrip("./")
    return normalized.replace("\\", "/")


def load_ownership_rules(path: Optional[Path] = None) -> Dict[str, List[OwnershipRule]]:
    config_path = path or DEFAULT_OWNERSHIP_RULES_PATH
    if not config_path.exists():
        return {}

    payload = json.loads(config_path.read_text(encoding="utf8"))
    repositories = payload.get("repositories")
    if not isinstance(repositories, dict):
        return {}

    rules_by_repository: Dict[str, List[OwnershipRule]] = {}
    for repository, raw_rules in repositories.items():
        if not isinstance(repository, str) or not isinstance(raw_rules, list):
            continue
        parsed_rules: List[OwnershipRule] = []
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            code_prefix = item.get("code_prefix")
            doc_prefix = item.get("doc_prefix")
            if not isinstance(code_prefix, str) or not isinstance(doc_prefix, str):
                continue
            parsed_rules.append(
                OwnershipRule(
                    code_prefix=normalize_prefix(code_prefix),
                    doc_prefix=normalize_prefix(doc_prefix),
                    score_boost=int(item.get("score_boost", 32) or 32),
                    description=str(item.get("description") or ""),
                )
            )
        if parsed_rules:
            rules_by_repository[repository] = parsed_rules
    return rules_by_repository


def build_ownership_signals(
    repository: Optional[str],
    changed_files: Sequence[str],
    doc_paths: Sequence[str],
    rules_path: Optional[Path] = None,
) -> Dict[str, Dict[str, object]]:
    if not repository:
        return {}

    rules = load_ownership_rules(rules_path).get(repository, [])
    if not rules:
        return {}

    normalized_docs = {doc_path: normalize_prefix(doc_path) for doc_path in doc_paths}
    normalized_changed_files = [normalize_prefix(path) for path in changed_files]
    signals: Dict[str, Dict[str, object]] = {}

    for rule in rules:
        matching_files = [
            path
            for path in normalized_changed_files
            if path.startswith(rule.code_prefix)
        ]
        if not matching_files:
            continue

        for original_doc_path, normalized_doc_path in normalized_docs.items():
            if not normalized_doc_path.startswith(rule.doc_prefix):
                continue
            signal = signals.setdefault(
                original_doc_path,
                {
                    "score_boost": 0,
                    "matched_code_prefixes": [],
                    "matched_doc_prefixes": [],
                    "matched_files": [],
                    "descriptions": [],
                },
            )
            signal["score_boost"] += rule.score_boost
            signal["matched_code_prefixes"].append(rule.code_prefix)
            signal["matched_doc_prefixes"].append(rule.doc_prefix)
            signal["matched_files"].extend(matching_files)
            if rule.description:
                signal["descriptions"].append(rule.description)

    for signal in signals.values():
        signal["matched_code_prefixes"] = sorted(dict.fromkeys(signal["matched_code_prefixes"]))
        signal["matched_doc_prefixes"] = sorted(dict.fromkeys(signal["matched_doc_prefixes"]))
        signal["matched_files"] = sorted(dict.fromkeys(signal["matched_files"]))
        signal["descriptions"] = sorted(dict.fromkeys(signal["descriptions"]))

    return signals
