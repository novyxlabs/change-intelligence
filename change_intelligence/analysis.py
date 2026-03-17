from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Sequence, Set


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
SYMBOL_PATTERNS = [
    re.compile(r"\b(?:function|async function)\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bclass\s+([A-Za-z0-9_]+)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\("),
    re.compile(r"\bexport\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bexport\s+class\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bexport\s+const\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bdef\s+([A-Za-z0-9_]+)\s*\("),
]


def tokenize(value: str) -> List[str]:
    return [
        token.lower()
        for token in TOKEN_SPLIT.split(value)
        if token and len(token) > 2 and token.lower() not in STOPWORDS
    ]


@dataclass
class ChangedFile:
    path: str
    basename: str
    added_lines: List[str]
    removed_lines: List[str]
    path_tokens: Set[str]
    content_tokens: Set[str]


@dataclass
class DiffSummary:
    files: List[ChangedFile]
    symbols: Set[str]
    added_identifiers: List[str]


@dataclass
class DocIndex:
    path: str
    relative_path: str
    headings: List[str]
    content: str
    tokens: Set[str]


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
            line_symbols = extract_symbols(stripped)
            symbols.update(line_symbols)
            added_identifiers.extend(sorted(line_symbols))
            continue

        if line.startswith("-") and not line.startswith("---"):
            stripped = line[1:]
            current["removed_lines"].append(stripped)
            symbols.update(extract_symbols(stripped))

    if current is not None:
        files.append(finalize_file(current))

    return DiffSummary(files=files, symbols=symbols, added_identifiers=list(dict.fromkeys(added_identifiers)))


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

    return {
        "target_heading": target_heading,
        "summary": f"Update `{target_heading}` to reflect the code changes in this PR.",
        "proposed_changes": [
            (
                f"Document the new tool `{symbol}`."
                if is_reference_expansion(diff)
                else f"Update documentation for `{symbol}`."
            )
            for symbol in changed_symbols[:8]
        ][:6],
        "patch_preview": "\n".join(lines),
        "confidence_gate": recommendation["confidence"] >= 60,
    }


def score_document(
    diff: DiffSummary,
    doc: DocIndex,
    learned_signals: Dict[str, Dict[str, object]],
    pattern_doc_hits: Dict[str, int],
    actual_docs_changed: Set[str],
) -> Dict[str, object]:
    score = 0
    evidence: List[str] = []
    doc_signal = learned_signals.get(doc.relative_path) or learned_signals.get(Path(doc.relative_path).name) or {}
    domain_overlap = sorted(diff_domain_tokens(diff) & doc_domain_tokens(doc))

    for changed_file in diff.files:
        path_overlap = intersection_size(changed_file.path_tokens, doc.tokens)
        content_overlap = intersection_size(changed_file.content_tokens, doc.tokens)

        if changed_file.basename.lower() in doc.relative_path.lower():
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
    if matching_symbols:
        score += len(matching_symbols) * 20
        evidence.append("Mentions changed symbols: " + ", ".join(matching_symbols[:5]))

    if domain_overlap:
        score += len(domain_overlap) * 28
        evidence.append(f"Domain match for this change: {', '.join(domain_overlap)}")

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

    accepted_hits = int(doc_signal.get("accepted_hits", 0) or 0)
    if accepted_hits:
        score += accepted_hits * 12
        evidence.append(f"Past merged PRs reinforced `{doc.relative_path}` as a correct target ({accepted_hits} confirmations)")

    rejected_hits = int(doc_signal.get("rejected_hits", 0) or 0)
    if rejected_hits:
        score -= rejected_hits * 18
        evidence.append(f"Past merged PRs rejected `{doc.relative_path}` for similar changes ({rejected_hits} misses)")

    pattern_hits = pattern_doc_hits.get(doc.relative_path, 0) + pattern_doc_hits.get(Path(doc.relative_path).name, 0)
    if pattern_hits:
        score += pattern_hits * 8
        evidence.append(f"Historical change-pattern memories referenced `{doc.relative_path}` ({pattern_hits} matches)")

    if doc.relative_path in actual_docs_changed or Path(doc.relative_path).name in actual_docs_changed:
        score += 30
        evidence.append(f"PR already changed `{doc.relative_path}`, confirming relevance")

    confidence = max(0, min(100, score))
    if is_security_fix(diff) and not domain_overlap:
        confidence = min(confidence, 45)
        score = min(score, 45)
        evidence.append(f"Confidence capped because `{doc.relative_path}` does not match the security/auth/search domains in the diff")
    if is_reference_expansion(diff) and is_index_page(doc) and len(matching_symbols) < 3:
        confidence = min(confidence, 35)
        score = min(score, 35)
        evidence.append(f"Confidence capped because `{doc.relative_path}` is a broad index page without strong identifier matches")
    if (
        rejected_hits > 0
        and accepted_hits == 0
        and doc.relative_path not in actual_docs_changed
        and Path(doc.relative_path).name not in actual_docs_changed
    ):
        confidence = min(confidence, 45)
        evidence.append(f"Confidence capped because Novyx learned `{doc.relative_path}` was a false positive for similar changes")
    return {
        "path": doc.path,
        "relative_path": doc.relative_path,
        "score": score,
        "confidence": confidence,
        "evidence": list(dict.fromkeys(evidence))[:6],
    }


def rank_documents(
    diff: DiffSummary,
    docs: Sequence[DocIndex],
    learned_signals: Optional[Dict[str, Dict[str, object]]] = None,
    patterns: Optional[Sequence[Dict[str, object]]] = None,
    actual_docs_changed: Optional[Set[str]] = None,
) -> List[Dict[str, object]]:
    recommendations: List[Dict[str, object]] = []
    learned_signals = learned_signals or {}
    pattern_doc_hits = extract_docs_from_patterns(patterns or [])
    actual_docs_changed = actual_docs_changed or set()

    for doc in docs:
        recommendation = score_document(
            diff,
            doc,
            learned_signals,
            pattern_doc_hits,
            actual_docs_changed,
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

    if is_security_fix(diff):
        narrowed = []
        for item in recommendations:
            if int(item["confidence"]) >= 60:
                narrowed.append(item)
        if narrowed:
            recommendations = narrowed[:3] + [item for item in recommendations if int(item["confidence"]) < 60]

    recommendations.sort(
        key=lambda item: (item["confidence"], item["score"]),
        reverse=True,
    )
    return recommendations[:10]


def render_markdown(summary: Dict[str, object], recommendations: Sequence[Dict[str, object]]) -> str:
    lines = [
        "# Change Intelligence Report",
        "",
        "## Summary",
        "",
        f"- Changed files: {len(summary['changed_files'])}",
        f"- Changed symbols: {len(summary['changed_symbols'])}",
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


def analyze_patch(
    diff_text: str,
    docs_root: Optional[Path] = None,
    docs: Optional[Sequence[Dict[str, str]]] = None,
    learned_signals: Optional[Dict[str, Dict[str, object]]] = None,
    patterns: Optional[Sequence[Dict[str, object]]] = None,
    actual_docs_changed: Optional[Set[str]] = None,
) -> Dict[str, object]:
    diff = parse_unified_diff(diff_text)
    indexed_docs = index_doc_blobs(docs) if docs is not None else index_docs(docs_root)
    recommendations = rank_documents(
        diff,
        indexed_docs,
        learned_signals=learned_signals,
        patterns=patterns,
        actual_docs_changed=actual_docs_changed,
    )
    summary = {
        "changed_files": [item.path for item in diff.files],
        "changed_symbols": sorted(diff.symbols),
        "docs_analyzed": len(indexed_docs),
    }
    return {
        "summary": summary,
        "recommendations": recommendations,
        "markdown": render_markdown(summary, recommendations),
    }
