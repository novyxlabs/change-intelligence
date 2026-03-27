from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Set


SURFACE_PATTERN = re.compile(r"""["'`](\/[A-Za-z0-9._~!$&'()*+,;=:@%/\-{}[\]]+)["'`]""")
METHOD_SURFACE_PATTERN = re.compile(r"""\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(/[A-Za-z0-9._~!$&'()*+,;=:@%/\-{}[\]]+)""", re.IGNORECASE)
BARE_SURFACE_PATTERN = re.compile(r"""(?<![A-Za-z0-9_/{}])(/[A-Za-z0-9._~!$&'()*+,;=:@%/\-{}[\]]+)""")
FRAMEWORK_ROUTE_PATTERNS = [
    re.compile(r"""\b(?:app|router|blueprint)\.(?:get|post|put|patch|delete|options|head)\(\s*["'`](\/[^"'`]+)["'`]""", re.IGNORECASE),
    re.compile(r"""@(?:app|router|blueprint)\.(?:get|post|put|patch|delete|options|head)\(\s*["'`](\/[^"'`]+)["'`]""", re.IGNORECASE),
]
ROUTE_CONTEXT_HINTS = (
    "route",
    "router",
    "endpoint",
    "request",
    "fetch",
    "path",
    "pathname",
    "href",
    "navigate",
    "redirect",
    "webhook",
    "api",
)
HTML_TAG_NAMES = {
    "a",
    "article",
    "aside",
    "b",
    "body",
    "button",
    "code",
    "div",
    "em",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "head",
    "header",
    "html",
    "i",
    "img",
    "input",
    "label",
    "li",
    "link",
    "main",
    "meta",
    "nav",
    "ol",
    "option",
    "p",
    "script",
    "section",
    "small",
    "span",
    "strong",
    "style",
    "svg",
    "table",
    "tbody",
    "td",
    "textarea",
    "th",
    "thead",
    "title",
    "tr",
    "ul",
}


def normalize_surface(value: str) -> str:
    surface = value.strip()
    if not surface.startswith("/"):
        return ""
    if surface.startswith("//"):
        return ""
    surface = surface.rstrip(""".,:;)]}'">""")
    if len(surface) > 1:
        surface = surface.rstrip("/")
    return surface


def line_has_route_context(line: str) -> bool:
    lowered = line.lower()
    return any(hint in lowered for hint in ROUTE_CONTEXT_HINTS)


def looks_like_markup_tag(surface: str, line: str) -> bool:
    segment = surface[1:]
    if "/" in segment or "{" in segment or "}" in segment:
        return False
    if segment.lower() not in HTML_TAG_NAMES:
        return False
    lowered = line.lower()
    return f"</{segment.lower()}" in lowered or f"<{segment.lower()}" in lowered


def allow_context_free_surface(surface: str) -> bool:
    return (
        surface.startswith("/v")
        or surface.count("/") >= 2
        or "{" in surface
        or any(char.isdigit() for char in surface)
    )


def extract_surfaces_from_line(line: str) -> Set[str]:
    matches: Set[str] = set()
    route_context = line_has_route_context(line)

    for match in SURFACE_PATTERN.finditer(line):
        normalized = normalize_surface(match.group(1))
        if normalized and not looks_like_markup_tag(normalized, line) and (route_context or allow_context_free_surface(normalized)):
            matches.add(normalized)

    for match in METHOD_SURFACE_PATTERN.finditer(line):
        normalized = normalize_surface(match.group(2))
        if normalized:
            matches.add(normalized)

    for match in BARE_SURFACE_PATTERN.finditer(line):
        normalized = normalize_surface(match.group(1))
        if normalized and not looks_like_markup_tag(normalized, line) and (route_context or allow_context_free_surface(normalized)):
            matches.add(normalized)

    for pattern in FRAMEWORK_ROUTE_PATTERNS:
        for match in pattern.finditer(line):
            normalized = normalize_surface(match.group(1))
            if normalized:
                matches.add(normalized)

    return matches


def extract_surfaces(lines: Iterable[str]) -> List[str]:
    surfaces: List[str] = []
    for line in lines:
        surfaces.extend(sorted(extract_surfaces_from_line(line)))
    return list(dict.fromkeys(surfaces))


def doc_surface_matches(content: str, headings: Sequence[str]) -> Set[str]:
    return set(extract_surfaces([content, *headings]))
