from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .ownership import build_ownership_signals
from .surface_map import doc_surface_matches, extract_surfaces


TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")
DOC_PATH_PATTERN = re.compile(r"([A-Za-z0-9_./-]+\.(?:md|mdx|txt))", re.IGNORECASE)
STOPWORDS = {
    "and",
    "are",
    "available",
    "because",
    "been",
    "but",
    "can",
    "for",
    "from",
    "get",
    "has",
    "have",
    "into",
    "its",
    "next",
    "not",
    "print",
    "self",
    "that",
    "the",
    "their",
    "then",
    "this",
    "was",
    "with",
}
SECURITY_HINTS = {
    "auth": {"auth", "authentication", "credential", "token", "api-key", "api", "key"},
    "ssrf": {"ssrf", "url", "http", "connector", "dns", "validateurl"},
    "search": {"search", "filter", "filters", "query", "truncate", "truncation"},
    "memory": {"memories", "memory", "ttl", "expired", "expiry", "store"},
    "audit": {"audit", "security", "findings"},
}
SUPPORT_DOC_HINTS = {
    "support",
    "faq",
    "troubleshooting",
    "troubleshoot",
    "runbook",
    "incident",
    "help",
    "known-issues",
    "errors",
}
ONBOARDING_DOC_HINTS = {
    "onboarding",
    "getting-started",
    "quickstart",
    "quick-start",
    "setup",
    "install",
    "installation",
    "tutorial",
    "walkthrough",
    "tour",
    "first-run",
    "signup",
    "login",
    "auth",
}
SYMBOL_PATTERNS = [
    re.compile(r"\b(?:function|async function)\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bclass\s+([A-Za-z0-9_]+)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\("),
    re.compile(r"\bexport\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bexport\s+class\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bexport\s+const\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bdef\s+([A-Za-z0-9_]+)\s*\("),
]


def split_identifier_tokens(value: str) -> List[str]:
    parts = [
        fragment
        for fragment in re.findall(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+", value)
        if fragment
    ]
    return parts or [value]


def tokenize(value: str) -> List[str]:
    tokens: List[str] = []
    for raw in TOKEN_SPLIT.split(value):
        if not raw:
            continue
        for fragment in split_identifier_tokens(raw):
            lowered = fragment.lower()
            if len(lowered) > 2 and lowered not in STOPWORDS:
                tokens.append(lowered)
    return tokens


@dataclass
class ChangedFile:
    path: str
    basename: str
    added_lines: List[str]
    removed_lines: List[str]
    path_tokens: Set[str]
    content_tokens: Set[str]
    is_test: bool


@dataclass
class DiffSummary:
    files: List[ChangedFile]
    symbols: Set[str]
    added_identifiers: List[str]
    surfaces: List[str]


@dataclass
class DocIndex:
    path: str
    relative_path: str
    headings: List[str]
    content: str
    tokens: Set[str]
    surfaces: Set[str]


def doc_text(doc: DocIndex) -> str:
    return f"{doc.relative_path.lower()} {' '.join(doc.headings).lower()} {doc.content.lower()}"


def doc_matches_audience(doc: DocIndex, hints: Set[str]) -> bool:
    text = doc_text(doc)
    return any(hint in text for hint in hints)


def extract_symbols(line: str) -> Set[str]:
    symbols: Set[str] = set()
    for pattern in SYMBOL_PATTERNS:
        for match in pattern.finditer(line):
            symbols.add(match.group(1))
    return symbols


def parse_unified_diff(diff_text: str) -> DiffSummary:
    files: List[ChangedFile] = []
    symbols: Set[str] = set()
    added_identifiers: List[str] = []
    surfaces: List[str] = []
    current: Dict[str, object] | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                files.append(finalize_file(current))
            current = {
                "path": "",
                "added_lines": [],
                "removed_lines": [],
            }
            continue

        if current is None:
            continue

        if line.startswith("+++ b/"):
            current["path"] = line[len("+++ b/") :]
            continue

        if line.startswith("+") and not line.startswith("+++"):
            stripped = line[1:]
            current["added_lines"].append(stripped)
            current_path = str(current.get("path") or "")
            if not is_test_path(current_path):
                line_symbols = extract_symbols(stripped)
                symbols.update(line_symbols)
                added_identifiers.extend(sorted(line_symbols))
                surfaces.extend(extract_surfaces([stripped]))
            continue

        if line.startswith("-") and not line.startswith("---"):
            stripped = line[1:]
            current["removed_lines"].append(stripped)
            current_path = str(current.get("path") or "")
            if not is_test_path(current_path):
                symbols.update(extract_symbols(stripped))
                surfaces.extend(extract_surfaces([stripped]))

    if current is not None:
        files.append(finalize_file(current))

    return DiffSummary(
        files=files,
        symbols=symbols,
        added_identifiers=list(dict.fromkeys(added_identifiers)),
        surfaces=list(dict.fromkeys(surfaces)),
    )


def finalize_file(raw_file: Dict[str, object]) -> ChangedFile:
    path = str(raw_file["path"])
    basename = Path(path).name
    added_lines = list(raw_file["added_lines"])
    removed_lines = list(raw_file["removed_lines"])
    path_tokens = set(tokenize(path))
    content_tokens = set(
        token
        for line in added_lines + removed_lines
        for token in tokenize(line)
    )
    return ChangedFile(
        path=path,
        basename=basename,
        added_lines=added_lines,
        removed_lines=removed_lines,
        path_tokens=path_tokens,
        content_tokens=content_tokens,
        is_test=is_test_path(path),
    )


def is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return (
        normalized.startswith("tests/")
        or normalized.startswith("test/")
        or "/tests/" in normalized
        or "/test/" in normalized
        or normalized.endswith("_test.py")
        or normalized.endswith(".test.js")
        or normalized.endswith(".spec.js")
    )


def extract_headings(content: str) -> List[str]:
    headings = []
    for line in content.splitlines():
        if line.startswith("#"):
            headings.append(re.sub(r"^#+\s*", "", line).strip())
    return headings


def index_docs(root: Path) -> List[DocIndex]:
    raw_docs: List[Dict[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".mdx", ".txt"}:
            continue
        raw_docs.append(
            {
                "path": str(path),
                "relative_path": path.relative_to(root).as_posix(),
                "content": path.read_text(encoding="utf8"),
            }
        )
    return index_doc_blobs(raw_docs)


def index_doc_blobs(raw_docs: Sequence[Dict[str, str]]) -> List[DocIndex]:
    docs: List[DocIndex] = []
    for item in raw_docs:
        path = item["path"]
        relative_path = item.get("relative_path") or Path(path).name
        content = item["content"]
        headings = extract_headings(content)
        tokens = set(tokenize(relative_path))
        tokens.update(tokenize(content))
        for heading in headings:
            tokens.update(tokenize(heading))
        docs.append(
            DocIndex(
                path=str(path),
                relative_path=relative_path,
                headings=headings,
                content=content,
                tokens=tokens,
                surfaces=doc_surface_matches(content, headings),
            )
        )
    return docs


def intersection_size(left: Iterable[str], right: Set[str]) -> int:
    total = 0
    for token in left:
        if token in right:
            total += 1
    return total


def top_overlap(tokens: Iterable[str], doc_tokens: Set[str], limit: int = 5) -> List[str]:
    return [token for token in sorted(dict.fromkeys(tokens)) if token in doc_tokens][:limit]


def build_focus_areas(doc: DocIndex, diff: DiffSummary) -> List[str]:
    focus: List[str] = []
    matching_surfaces = [surface for surface in diff.surfaces if surface in doc.surfaces]
    if matching_surfaces:
        focus.append(
            "Review sections covering routes and APIs: "
            + ", ".join(matching_surfaces[:3])
            + "."
        )
    for changed_file in diff.files:
        overlapping_terms = top_overlap(changed_file.content_tokens, doc.tokens, limit=4)
        if not overlapping_terms:
            continue
        focus.append(
            "Review sections covering "
            + ", ".join(overlapping_terms)
            + f" because `{changed_file.path}` changed."
        )
    if not focus and diff.symbols:
        focus.append(
            "Check references to changed symbols: "
            + ", ".join(sorted(diff.symbols)[:4])
            + "."
        )
    return list(dict.fromkeys(focus))[:3]


def extract_docs_from_patterns(patterns: Sequence[Dict[str, object]]) -> Dict[str, int]:
    matches: Dict[str, int] = {}
    for pattern in patterns:
        observation = str(pattern.get("observation") or "")
        for match in DOC_PATH_PATTERN.findall(observation):
            doc_name = Path(match).name
            matches[doc_name] = matches.get(doc_name, 0) + 1
            matches[match] = matches.get(match, 0) + 1
    return matches


def determine_target_heading(doc: DocIndex, diff: DiffSummary) -> str:
    for symbol in diff.added_identifiers or sorted(diff.symbols):
        for heading in doc.headings:
            if symbol.lower() in heading.lower():
                return heading
    if doc.headings:
        return doc.headings[0]
    return "Overview"


def collect_change_terms(diff: DiffSummary, doc: DocIndex, limit: int = 5) -> List[str]:
    terms: List[str] = []
    for changed_file in diff.files:
        terms.extend(top_overlap(changed_file.content_tokens, doc.tokens, limit=limit))
    return list(dict.fromkeys(terms))[:limit]


def is_reference_page(doc: DocIndex) -> bool:
    path = doc.relative_path.lower()
    text = " ".join(doc.headings).lower()
    return "reference" in path or "reference" in text or "tools-reference" in path


def is_index_page(doc: DocIndex) -> bool:
    path = doc.relative_path.lower()
    return path.endswith("index.md") or path == "index.md"


def is_changelog_page(doc: DocIndex) -> bool:
    path = doc.relative_path.lower()
    return path.endswith("changelog.md") or path == "changelog.md"


def is_sdk_page(doc: DocIndex) -> bool:
    path = doc.relative_path.lower()
    return path.startswith("sdks/") or "/sdks/" in path


def is_broad_doc_target(doc: DocIndex) -> bool:
    return is_index_page(doc) or is_changelog_page(doc) or is_sdk_page(doc)


def is_error_reference_page(doc: DocIndex) -> bool:
    path = doc.relative_path.lower()
    text = " ".join(doc.headings).lower()
    return path.endswith("errors.md") or path == "errors.md" or "error reference" in text


def has_structural_support(
    matching_symbols: Sequence[str],
    matching_surfaces: Sequence[str],
    ownership_boost: int,
    exact_file_hits: int,
    accepted_hits: int,
    missed_hits: int,
    actual_doc_changed: bool,
    audience_prior: bool = False,
) -> bool:
    return bool(
        matching_symbols
        or matching_surfaces
        or ownership_boost
        or exact_file_hits
        or accepted_hits
        or missed_hits
        or actual_doc_changed
        or audience_prior
    )


def exact_surface_targets(diff: DiffSummary, docs: Sequence[DocIndex]) -> Set[str]:
    if not diff.surfaces:
        return set()
    targets: Set[str] = set()
    for doc in docs:
        if any(surface in doc.surfaces for surface in diff.surfaces):
            targets.add(doc.relative_path)
    return targets


def matching_surface_details(diff: DiffSummary, doc: DocIndex) -> List[str]:
    return [surface for surface in diff.surfaces if surface in doc.surfaces]


def surface_specificity(surface: str) -> int:
    return surface.count("/") + (surface.count("{") * 2) + len(surface)


def relevant_surfaces_for_docs(diff: DiffSummary, docs: Sequence[DocIndex]) -> List[str]:
    if not diff.surfaces:
        return []
    doc_surfaces = {
        surface
        for doc in docs
        for surface in doc.surfaces
    }
    return [surface for surface in diff.surfaces if surface in doc_surfaces]


def is_reference_expansion(diff: DiffSummary) -> bool:
    identifier_count = len(diff.added_identifiers)
    changed_paths = " ".join(file.path.lower() for file in diff.files)
    return identifier_count >= 10 and ("server.py" in changed_paths or "mcp" in changed_paths)


def is_security_fix(diff: DiffSummary) -> bool:
    text = " ".join(
        [
            *[file.path.lower() for file in diff.files],
            *[token for file in diff.files for token in file.content_tokens],
            *[symbol.lower() for symbol in diff.added_identifiers],
        ]
    )
    return any(term in text for term in ["auth", "ssrf", "validateurl", "ttl", "filter", "search", "credential"])


def doc_domain_tokens(doc: DocIndex) -> Set[str]:
    path = doc.relative_path.lower()
    headings = " ".join(doc.headings).lower()
    content = doc.content.lower()
    text = f"{path} {headings} {content}"
    matches: Set[str] = set()
    for label, terms in SECURITY_HINTS.items():
        if any(term in text for term in terms):
            matches.add(label)
    return matches


def diff_domain_tokens(diff: DiffSummary) -> Set[str]:
    text = " ".join(
        [
            *[file.path.lower() for file in diff.files],
            *[token for file in diff.files for token in file.content_tokens],
            *[symbol.lower() for symbol in diff.added_identifiers],
        ]
    )
    matches: Set[str] = set()
    for label, terms in SECURITY_HINTS.items():
        if any(term in text for term in terms):
            matches.add(label)
    return matches


def build_draft_patch(doc: DocIndex, diff: DiffSummary, recommendation: Dict[str, object]) -> Dict[str, object]:
    target_heading = determine_target_heading(doc, diff)
    changed_symbols = diff.added_identifiers[:12] or sorted(diff.symbols)[:12]
    lines = [
        f"@@ {target_heading}",
        "+ Clarify the behavior changed in this PR.",
    ]
    if changed_symbols:
        if is_reference_expansion(diff):
            lines.append("+ Add the newly available tools: " + ", ".join(f"`{item}`" for item in changed_symbols[:8]) + ".")
        else:
            lines.append("+ Update references to: " + ", ".join(f"`{item}`" for item in changed_symbols[:8]) + ".")

    proposed_changes = [
        (
            f"Document the new tool `{symbol}`."
            if is_reference_expansion(diff)
            else f"Update documentation for `{symbol}`."
        )
        for symbol in changed_symbols[:8]
    ][:6]
    if diff.surfaces:
        proposed_changes.append(
            "Confirm the documented route and API behavior for "
            + ", ".join(f"`{item}`" for item in diff.surfaces[:3])
            + "."
        )

    return {
        "target_heading": target_heading,
        "summary": f"Update `{target_heading}` to reflect the code changes in this PR.",
        "proposed_changes": proposed_changes[:6],
        "patch_preview": "\n".join(lines),
        "confidence_gate": recommendation["confidence"] >= 60,
    }


def prioritize_evidence(evidence: Sequence[str]) -> List[str]:
    priority_order = [
        "Mentions changed routes or APIs:",
        "Mentions changed symbols:",
        "Ownership rule matched",
        "Novyx remembers this exact changed file mapping",
        "Past merged PRs reinforced",
        "Past merges taught Novyx",
        "Learned Novyx graph links",
        "Domain match for this change:",
        "Path references changed file basename",
        "Shared path terms with",
        "Shared change terms with",
        "Historical change-pattern memories referenced",
        "Post-rank boost:",
        "Post-rank trim:",
        "Post-rank demotion:",
        "Confidence capped because",
        "Reference-page prior:",
        "Index-page penalty:",
    ]

    ranked = sorted(
        dict.fromkeys(evidence),
        key=lambda line: next(
            (index for index, prefix in enumerate(priority_order) if str(line).startswith(prefix)),
            len(priority_order),
        ),
    )
    return ranked[:8]


def score_document(
    diff: DiffSummary,
    doc: DocIndex,
    learned_signals: Dict[str, Dict[str, object]],
    pattern_doc_hits: Dict[str, int],
    actual_docs_changed: Set[str],
    ownership_signal: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    score = 0
    evidence: List[str] = []
    doc_signal = learned_signals.get(doc.relative_path) or learned_signals.get(Path(doc.relative_path).name) or {}
    domain_overlap = sorted(diff_domain_tokens(diff) & doc_domain_tokens(doc))
    max_path_overlap = 0
    has_basename_reference = False

    for changed_file in diff.files:
        if changed_file.is_test:
            continue
        path_overlap = intersection_size(changed_file.path_tokens, doc.tokens)
        content_overlap = intersection_size(changed_file.content_tokens, doc.tokens)
        max_path_overlap = max(max_path_overlap, path_overlap)

        if changed_file.basename.lower() in doc.relative_path.lower():
            has_basename_reference = True
            score += 8
            evidence.append(f"Path references changed file basename `{changed_file.basename}`")

        if path_overlap:
            shared = top_overlap(changed_file.path_tokens, doc.tokens)
            score += path_overlap * 3
            evidence.append(f"Shared path terms with `{changed_file.path}`: " + ", ".join(shared))

        if content_overlap:
            shared = top_overlap(changed_file.content_tokens, doc.tokens)
            score += content_overlap * 2
            evidence.append(f"Shared change terms with `{changed_file.path}`: " + ", ".join(shared))

    matching_symbols = [
        symbol
        for symbol in diff.added_identifiers or sorted(diff.symbols)
        if symbol.lower() in doc.content.lower()
        or any(symbol.lower() in heading.lower() for heading in doc.headings)
    ]
    matching_surfaces = matching_surface_details(diff, doc)
    if matching_symbols:
        score += len(matching_symbols) * 20
        evidence.append("Mentions changed symbols: " + ", ".join(matching_symbols[:5]))

    if matching_surfaces:
        score += len(matching_surfaces) * 34
        evidence.append("Mentions changed routes or APIs: " + ", ".join(matching_surfaces[:4]))

    if domain_overlap:
        score += len(domain_overlap) * 28
        evidence.append(f"Domain match for this change: {', '.join(domain_overlap)}")

    error_focused_change = any(
        "error" in changed_file.path_tokens
        or "errors" in changed_file.path_tokens
        or changed_file.basename.lower().startswith("error")
        for changed_file in diff.files
        if not changed_file.is_test
    )
    audience_prior = False
    if error_focused_change and is_error_reference_page(doc) and doc_matches_audience(doc, SUPPORT_DOC_HINTS):
        audience_prior = True
        score += 44
        evidence.append(f"Support-doc prior: `{doc.relative_path}` matches an error-focused change")

    if is_reference_expansion(diff):
        if is_reference_page(doc):
            score += 140
            evidence.append(f"Reference-page prior: this diff adds many named tools, so `{doc.relative_path}` is a stronger target")
        if is_index_page(doc):
            score -= 120
            evidence.append(f"Index-page penalty: broad landing pages should not outrank reference docs for tool-surface expansions")

    graph_hits = int(doc_signal.get("graph_hits", 0) or 0)
    if graph_hits:
        score += graph_hits * 18
        evidence.append(f"Learned Novyx graph links connect changed files to `{doc.relative_path}` ({graph_hits} hits)")

    exact_file_hits = int(doc_signal.get("exact_file_hits", 0) or 0)
    if exact_file_hits:
        score += exact_file_hits * 26
        evidence.append(f"Novyx remembers this exact changed file mapping to `{doc.relative_path}` ({exact_file_hits} matches)")

    exact_rejected_file_hits = int(doc_signal.get("exact_rejected_file_hits", 0) or 0)
    if exact_rejected_file_hits:
        score -= exact_rejected_file_hits * 34
        evidence.append(
            f"Novyx remembers this exact changed file was rejected for `{doc.relative_path}` ({exact_rejected_file_hits} false positives)"
        )

    accepted_hits = int(doc_signal.get("accepted_hits", 0) or 0)
    if accepted_hits:
        score += accepted_hits * 22
        evidence.append(f"Past merged PRs reinforced `{doc.relative_path}` as a correct target ({accepted_hits} confirmations)")

    missed_hits = int(doc_signal.get("missed_hits", 0) or 0)
    if missed_hits:
        score += missed_hits * 18
        evidence.append(f"Past merges taught Novyx that `{doc.relative_path}` was missed for similar changes ({missed_hits} misses)")

    rejected_hits = int(doc_signal.get("rejected_hits", 0) or 0)
    if rejected_hits:
        score -= rejected_hits * 24
        evidence.append(f"Past merged PRs rejected `{doc.relative_path}` for similar changes ({rejected_hits} misses)")

    pattern_hits = pattern_doc_hits.get(doc.relative_path, 0) + pattern_doc_hits.get(Path(doc.relative_path).name, 0)
    if pattern_hits:
        score += pattern_hits * 8
        evidence.append(f"Historical change-pattern memories referenced `{doc.relative_path}` ({pattern_hits} matches)")

    ownership_boost = int((ownership_signal or {}).get("score_boost", 0) or 0)
    if ownership_boost:
        score += ownership_boost
        code_prefixes = ", ".join((ownership_signal or {}).get("matched_code_prefixes", [])[:2])
        doc_prefixes = ", ".join((ownership_signal or {}).get("matched_doc_prefixes", [])[:2])
        matched_files = ", ".join((ownership_signal or {}).get("matched_files", [])[:2])
        evidence_line = (
            "Ownership rule matched "
            + (f"`{code_prefixes}`" if code_prefixes else "configured code prefixes")
            + " -> "
            + (f"`{doc_prefixes}`" if doc_prefixes else "configured doc prefixes")
        )
        if matched_files:
            evidence_line += f" for {matched_files}"
        descriptions = (ownership_signal or {}).get("descriptions", [])
        if descriptions:
            evidence_line += f" ({descriptions[0]})"
        evidence.append(evidence_line)

    actual_doc_changed = doc.relative_path in actual_docs_changed or Path(doc.relative_path).name in actual_docs_changed
    if actual_doc_changed:
        score += 30
        evidence.append(f"PR already changed `{doc.relative_path}`, confirming relevance")

    confidence = max(0, min(100, score))
    if (accepted_hits >= 2 or exact_file_hits >= 1 or missed_hits >= 2) and rejected_hits == 0:
        confidence = max(confidence, 72)
    if (
        not has_structural_support(
            matching_symbols,
            matching_surfaces,
            ownership_boost,
            exact_file_hits,
            accepted_hits,
            missed_hits,
            actual_doc_changed,
            audience_prior,
        )
        and not has_basename_reference
        and max_path_overlap < 2
    ):
        confidence = min(confidence, 58)
        score = min(score, 58)
        evidence.append(
            f"Confidence capped because `{doc.relative_path}` only matched weak term overlap without a structural doc signal"
        )
    if (
        is_broad_doc_target(doc)
        and not has_structural_support(
            matching_symbols,
            matching_surfaces,
            ownership_boost,
            exact_file_hits,
            accepted_hits,
            missed_hits,
            actual_doc_changed,
            audience_prior,
        )
        and not has_basename_reference
    ):
        confidence = min(confidence, 34)
        score = min(score, 34)
        evidence.append(
            f"Confidence capped because `{doc.relative_path}` is a broad doc target without explicit structural support"
        )
    if is_security_fix(diff) and not domain_overlap:
        confidence = min(confidence, 45)
        score = min(score, 45)
        evidence.append(f"Confidence capped because `{doc.relative_path}` does not match the security/auth/search domains in the diff")
    if is_reference_expansion(diff) and is_index_page(doc) and len(matching_symbols) < 3:
        confidence = min(confidence, 35)
        score = min(score, 35)
        evidence.append(f"Confidence capped because `{doc.relative_path}` is a broad index page without strong identifier matches")
    if (
        (rejected_hits > 0 or exact_rejected_file_hits > 0)
        and accepted_hits == 0
        and missed_hits == 0
        and exact_file_hits == 0
        and doc.relative_path not in actual_docs_changed
        and Path(doc.relative_path).name not in actual_docs_changed
    ):
        strong_negative_hits = max(rejected_hits, exact_rejected_file_hits)
        confidence = min(confidence, 25 if strong_negative_hits >= 2 else 38)
        evidence.append(f"Confidence capped because Novyx learned `{doc.relative_path}` was a false positive for similar changes")
    return {
        "path": doc.path,
        "relative_path": doc.relative_path,
        "score": score,
        "confidence": confidence,
        "evidence": prioritize_evidence(evidence),
        "graph_hits": graph_hits,
        "exact_file_hits": exact_file_hits,
        "accepted_hits": accepted_hits,
        "missed_hits": missed_hits,
        "rejected_hits": rejected_hits,
        "exact_rejected_file_hits": exact_rejected_file_hits,
        "surface_match_count": len(matching_surfaces),
        "surface_match_specificity": sum(surface_specificity(surface) for surface in matching_surfaces),
        "domain_overlap_count": len(domain_overlap),
    }


def rank_documents(
    diff: DiffSummary,
    docs: Sequence[DocIndex],
    learned_signals: Optional[Dict[str, Dict[str, object]]] = None,
    patterns: Optional[Sequence[Dict[str, object]]] = None,
    actual_docs_changed: Optional[Set[str]] = None,
    repository: Optional[str] = None,
    ownership_rules_path: Optional[Path] = None,
) -> List[Dict[str, object]]:
    recommendations: List[Dict[str, object]] = []
    learned_signals = learned_signals or {}
    pattern_doc_hits = extract_docs_from_patterns(patterns or [])
    actual_docs_changed = actual_docs_changed or set()
    ownership_signals = build_ownership_signals(
        repository,
        [item.path for item in diff.files],
        [item.relative_path for item in docs],
        rules_path=ownership_rules_path,
    )

    for doc in docs:
        recommendation = score_document(
            diff,
            doc,
            learned_signals,
            pattern_doc_hits,
            actual_docs_changed,
            ownership_signal=ownership_signals.get(doc.relative_path),
        )

        if recommendation["score"] <= 0:
            continue

        recommendation["update_focus"] = build_focus_areas(doc, diff)
        recommendation["draft_patch"] = build_draft_patch(doc, diff, recommendation)
        recommendations.append(recommendation)

    if is_reference_expansion(diff):
        has_reference_target = any(is_reference_page(doc) for doc in docs)
        if has_reference_target:
            for item in recommendations:
                if is_index_page(DocIndex(path=item["path"], relative_path=item["relative_path"], headings=[], content="", tokens=set())):
                    item["score"] = min(int(item["score"]), 55)
                    item["confidence"] = min(int(item["confidence"]), 55)
                    item["evidence"] = item["evidence"] + [
                        "Post-rank demotion: reference docs outrank broad index pages for tool-surface expansions"
                    ]

    surface_targets = exact_surface_targets(diff, docs)
    if surface_targets:
        for item in recommendations:
            relative_path = str(item.get("relative_path") or "")
            if relative_path in surface_targets:
                match_count = int(item.get("surface_match_count") or 0)
                match_specificity = int(item.get("surface_match_specificity") or 0)
                item["score"] = int(item["score"]) + 24 + (match_count * 18) + match_specificity
                confidence_floor = 70
                if match_count >= 2:
                    confidence_floor = 92
                elif match_count == 1:
                    confidence_floor = 78
                item["confidence"] = max(
                    confidence_floor,
                    min(100, int(item["confidence"]) + 8),
                )
                item["evidence"] = item["evidence"] + [
                    "Post-rank boost: exact route/API matches outrank broad historical-pattern matches"
                ]
                if match_count > 1:
                    item["evidence"] = item["evidence"] + [
                        "Post-rank boost: docs covering more of the changed API surface outrank broad parent-route mentions"
                    ]
                continue
            if is_index_page(DocIndex(path=str(item["path"]), relative_path=relative_path, headings=[], content="", tokens=set(), surfaces=set())):
                item["score"] = max(0, int(item["score"]) - 42)
                item["confidence"] = min(int(item["confidence"]), 60)
                item["evidence"] = item["evidence"] + [
                    "Post-rank demotion: broad index pages should not outrank specific docs with exact route/API matches"
                ]
                continue
            if is_changelog_page(DocIndex(path=str(item["path"]), relative_path=relative_path, headings=[], content="", tokens=set(), surfaces=set())):
                item["score"] = max(0, int(item["score"]) - 36)
                item["confidence"] = min(int(item["confidence"]), 64)
                item["evidence"] = item["evidence"] + [
                    "Post-rank demotion: changelog pages should not outrank docs with exact route/API matches"
                ]
                continue
            if diff.surfaces and int(item["confidence"]) >= 80:
                item["score"] = max(0, int(item["score"]) - 20)
                item["confidence"] = max(50, min(int(item["confidence"]), 80))
                item["evidence"] = item["evidence"] + [
                    "Post-rank trim: exact route/API matches were found elsewhere, so weaker indirect matches were demoted"
                ]

        best_surface_count = max(
            int(item.get("surface_match_count") or 0)
            for item in recommendations
            if str(item.get("relative_path") or "") in surface_targets
        )
        best_surface_specificity = max(
            int(item.get("surface_match_specificity") or 0)
            for item in recommendations
            if str(item.get("relative_path") or "") in surface_targets
        )
        for item in recommendations:
            relative_path = str(item.get("relative_path") or "")
            if relative_path not in surface_targets:
                continue
            match_count = int(item.get("surface_match_count") or 0)
            match_specificity = int(item.get("surface_match_specificity") or 0)
            coverage_gap = max(0, best_surface_count - match_count)
            specificity_gap = max(0, best_surface_specificity - match_specificity)
            if coverage_gap == 0 and specificity_gap == 0:
                continue
            item["score"] = max(
                0,
                int(item["score"]) - (coverage_gap * 48) - min(72, specificity_gap),
            )
            item["confidence"] = min(
                int(item["confidence"]),
                max(68, 90 - (coverage_gap * 8)),
            )
            item["evidence"] = item["evidence"] + [
                "Post-rank trim: narrower exact matches were demoted because another doc covers more of the changed API surface"
            ]

    recommendations.sort(
        key=lambda item: (
            int(item.get("surface_match_count") or 0),
            int(item.get("surface_match_specificity") or 0),
            int(item["score"]),
            int(item["confidence"]),
        ),
        reverse=True,
    )
    if is_security_fix(diff):
        narrowed = [item for item in recommendations if int(item["confidence"]) >= 60]
        if narrowed:
            recommendations = narrowed[:3] + [item for item in recommendations if int(item["confidence"]) < 60]
    return recommendations[:10]


def render_markdown(summary: Dict[str, object], recommendations: Sequence[Dict[str, object]]) -> str:
    lines = [
        "# Change Intelligence Report",
        "",
        "## Summary",
        "",
        f"- Changed files: {len(summary['changed_files'])}",
        f"- Changed symbols: {len(summary['changed_symbols'])}",
        f"- Changed routes/APIs: {len(summary.get('changed_surfaces', []))}",
        f"- Docs analyzed: {summary['docs_analyzed']}",
        f"- Recommended docs updates: {len(recommendations)}",
        "",
        "## Changed Files",
        "",
    ]
    for path in summary["changed_files"]:
        lines.append(f"- `{path}`")
    lines.extend(["", "## Changed Symbols", ""])
    for symbol in summary["changed_symbols"]:
        lines.append(f"- `{symbol}`")
    lines.extend(["", "## Changed Routes/APIs", ""])
    for surface in summary.get("changed_surfaces", []):
        lines.append(f"- `{surface}`")
    lines.extend(["", "## Recommended Docs", ""])
    if not recommendations:
        lines.append("No affected docs were detected from the current inputs.")
        return "\n".join(lines)

    for item in recommendations:
        lines.append(f"### {item['relative_path']}")
        lines.extend(["", f"Confidence: **{item['confidence']}**", f"Score: **{item['score']}**", "", "Evidence:"])
        for evidence in item["evidence"]:
            lines.append(f"- {evidence}")
        lines.extend(["", "Update focus:"])
        for focus in item["update_focus"]:
            lines.append(f"- {focus}")
        lines.extend(["", "Draft patch:"])
        lines.append(f"- Target heading: `{item['draft_patch']['target_heading']}`")
        for proposed in item["draft_patch"]["proposed_changes"][:3]:
            lines.append(f"- {proposed}")
        lines.extend(["", "```diff", item["draft_patch"]["patch_preview"], "```", ""])
    return "\n".join(lines).rstrip()


def build_release_notes(summary: Dict[str, object], diff: DiffSummary, recommendations: Sequence[Dict[str, object]]) -> Dict[str, object]:
    top = recommendations[0] if recommendations else {}
    top_confidence = int(top.get("confidence", 0) or 0)
    affected_surfaces = diff.surfaces[:5]
    changed_symbols = summary["changed_symbols"][:5]
    recommended_docs = [item["relative_path"] for item in recommendations[:3]]
    included = top_confidence >= 60 and bool(recommendations)

    if affected_surfaces:
        title = f"Update {' and '.join(affected_surfaces[:2])}"
    elif changed_symbols:
        title = f"Update {', '.join(changed_symbols[:2])}"
    elif summary["changed_files"]:
        title = f"Update {Path(summary['changed_files'][0]).stem}"
    else:
        title = "Product update"

    bullets: List[str] = []
    if affected_surfaces:
        bullets.append("Adjusted route or API behavior for " + ", ".join(f"`{item}`" for item in affected_surfaces[:3]) + ".")
    if changed_symbols:
        bullets.append("Touched implementation symbols: " + ", ".join(f"`{item}`" for item in changed_symbols[:4]) + ".")
    if recommended_docs:
        bullets.append("Documentation likely needs updates in " + ", ".join(f"`{item}`" for item in recommended_docs) + ".")
    if not bullets and summary["changed_files"]:
        bullets.append("Updated code paths: " + ", ".join(f"`{item}`" for item in summary["changed_files"][:3]) + ".")

    return {
        "title": title,
        "summary": bullets[0] if bullets else "Product behavior changed in this PR.",
        "bullets": bullets[:3],
        "affected_surfaces": affected_surfaces,
        "recommended_docs": recommended_docs,
        "confidence": top_confidence,
        "included_in_report": included,
        "suppressed_reason": None if included else "Top recommendation confidence below release-note threshold.",
    }


def build_support_updates(
    summary: Dict[str, object],
    diff: DiffSummary,
    recommendations: Sequence[Dict[str, object]],
    docs: Sequence[DocIndex],
) -> Dict[str, object]:
    docs_by_path = {item.relative_path: item for item in docs}
    support_recommendations = [
        item for item in recommendations
        if doc_matches_audience(docs_by_path.get(item["relative_path"], DocIndex("", "", [], "", set(), set())), SUPPORT_DOC_HINTS)
    ]
    top = support_recommendations[0] if support_recommendations else {}
    confidence = int(top.get("confidence", 0) or 0)
    primary_confidence = int((recommendations[0] if recommendations else {}).get("confidence", 0) or 0)
    included = confidence >= 50 and primary_confidence >= 80 and bool(support_recommendations)
    affected_surfaces = diff.surfaces[:4]
    changed_symbols = summary["changed_symbols"][:4]
    target_docs = [item["relative_path"] for item in support_recommendations[:3]]

    bullets: List[str] = []
    if target_docs:
        bullets.append("Update support-facing docs in " + ", ".join(f"`{item}`" for item in target_docs) + ".")
    if affected_surfaces:
        bullets.append("Support should expect customer questions about " + ", ".join(f"`{item}`" for item in affected_surfaces[:3]) + ".")
    if changed_symbols:
        bullets.append("Verify troubleshooting guidance still reflects " + ", ".join(f"`{item}`" for item in changed_symbols[:3]) + ".")

    return {
        "title": "Support Knowledge Update",
        "summary": bullets[0] if bullets else "Support-facing knowledge may need updates after this change.",
        "bullets": bullets[:3],
        "recommended_docs": target_docs,
        "affected_surfaces": affected_surfaces,
        "confidence": confidence,
        "included_in_report": included,
        "suppressed_reason": None if included else "No support-oriented docs ranked above the adjacent-update threshold.",
    }


def build_onboarding_updates(
    summary: Dict[str, object],
    diff: DiffSummary,
    recommendations: Sequence[Dict[str, object]],
    docs: Sequence[DocIndex],
) -> Dict[str, object]:
    docs_by_path = {item.relative_path: item for item in docs}
    onboarding_recommendations = [
        item for item in recommendations
        if doc_matches_audience(docs_by_path.get(item["relative_path"], DocIndex("", "", [], "", set(), set())), ONBOARDING_DOC_HINTS)
    ]
    top = onboarding_recommendations[0] if onboarding_recommendations else {}
    confidence = int(top.get("confidence", 0) or 0)
    primary_confidence = int((recommendations[0] if recommendations else {}).get("confidence", 0) or 0)
    included = confidence >= 50 and primary_confidence >= 80 and bool(onboarding_recommendations)
    affected_surfaces = diff.surfaces[:4]
    changed_symbols = summary["changed_symbols"][:4]
    target_docs = [item["relative_path"] for item in onboarding_recommendations[:3]]

    bullets: List[str] = []
    if target_docs:
        bullets.append("Update onboarding or setup docs in " + ", ".join(f"`{item}`" for item in target_docs) + ".")
    if affected_surfaces:
        bullets.append("Check first-run or setup flows that touch " + ", ".join(f"`{item}`" for item in affected_surfaces[:3]) + ".")
    if changed_symbols:
        bullets.append("Confirm walkthrough steps still match " + ", ".join(f"`{item}`" for item in changed_symbols[:3]) + ".")

    return {
        "title": "Onboarding/Tour Update",
        "summary": bullets[0] if bullets else "Onboarding guidance may need updates after this change.",
        "bullets": bullets[:3],
        "recommended_docs": target_docs,
        "affected_surfaces": affected_surfaces,
        "confidence": confidence,
        "included_in_report": included,
        "suppressed_reason": None if included else "No onboarding-oriented docs ranked above the adjacent-update threshold.",
    }


def render_report(
    summary: Dict[str, object],
    recommendations: Sequence[Dict[str, object]],
    release_notes: Dict[str, object],
    support_updates: Dict[str, object],
    onboarding_updates: Dict[str, object],
) -> str:
    base = render_markdown(summary, recommendations)
    sections = [base]

    if release_notes.get("included_in_report"):
        lines = [
            "",
            "## Release Notes Draft",
            "",
            f"Title: **{release_notes['title']}**",
            "",
        ]
        for bullet in release_notes.get("bullets", []):
            lines.append(f"- {bullet}")
        sections.append("\n".join(lines).rstrip())

    if support_updates.get("included_in_report"):
        lines = [
            "",
            "## Support Knowledge Update",
            "",
            f"Title: **{support_updates['title']}**",
            "",
        ]
        for bullet in support_updates.get("bullets", []):
            lines.append(f"- {bullet}")
        sections.append("\n".join(lines).rstrip())

    if onboarding_updates.get("included_in_report"):
        lines = [
            "",
            "## Onboarding/Tour Update",
            "",
            f"Title: **{onboarding_updates['title']}**",
            "",
        ]
        for bullet in onboarding_updates.get("bullets", []):
            lines.append(f"- {bullet}")
        sections.append("\n".join(lines).rstrip())

    return "\n".join(section.rstrip() for section in sections if section).rstrip()


def analyze_patch(
    diff_text: str,
    docs_root: Optional[Path] = None,
    docs: Optional[Sequence[Dict[str, str]]] = None,
    learned_signals: Optional[Dict[str, Dict[str, object]]] = None,
    patterns: Optional[Sequence[Dict[str, object]]] = None,
    actual_docs_changed: Optional[Set[str]] = None,
    repository: Optional[str] = None,
    ownership_rules_path: Optional[Path] = None,
) -> Dict[str, object]:
    diff = parse_unified_diff(diff_text)
    indexed_docs = index_doc_blobs(docs) if docs is not None else index_docs(docs_root)
    relevant_surfaces = relevant_surfaces_for_docs(diff, indexed_docs)
    ranking_diff = DiffSummary(
        files=diff.files,
        symbols=diff.symbols,
        added_identifiers=diff.added_identifiers,
        surfaces=relevant_surfaces,
    )
    recommendations = rank_documents(
        ranking_diff,
        indexed_docs,
        learned_signals=learned_signals,
        patterns=patterns,
        actual_docs_changed=actual_docs_changed,
        repository=repository,
        ownership_rules_path=ownership_rules_path,
    )
    summary = {
        "changed_files": [item.path for item in diff.files],
        "changed_symbols": sorted(diff.symbols),
        "changed_surfaces": ranking_diff.surfaces,
        "docs_analyzed": len(indexed_docs),
    }
    release_notes = build_release_notes(summary, ranking_diff, recommendations)
    support_updates = build_support_updates(summary, ranking_diff, recommendations, indexed_docs)
    onboarding_updates = build_onboarding_updates(summary, ranking_diff, recommendations, indexed_docs)
    return {
        "summary": summary,
        "recommendations": recommendations,
        "release_notes": release_notes,
        "support_updates": support_updates,
        "onboarding_updates": onboarding_updates,
        "markdown": render_report(summary, recommendations, release_notes, support_updates, onboarding_updates),
    }
