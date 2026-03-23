from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Set


SURFACE_PATTERN = re.compile(r"""["'`](\/[A-Za-z0-9._~!$&'()*+,;=:@%/\-{}[\]]+)["'`]""")
METHOD_SURFACE_PATTERN = re.compile(r"""\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+(/[A-Za-z0-9._~!$&'()*+,;=:@%/\-{}[\]]+)""", re.IGNORECASE)
BARE_SURFACE_PATTERN = re.compile(r"""(?<![A-Za-z0-9_])(/[A-Za-z0-9._~!$&'()*+,;=:@%/\-{}[\]]+)""")
FRAMEWORK_ROUTE_PATTERNS = [
    re.compile(r"""\b(?:app|router|blueprint)\.(?:get|post|put|patch|delete|options|head)\(\s*["'`](\/[^"'`]+)["'`]""", re.IGNORECASE),
    re.compile(r"""@(?:app|router|blueprint)\.(?:get|post|put|patch|delete|options|head)\(\s*["'`](\/[^"'`]+)["'`]""", re.IGNORECASE),
]


def normalize_surface(value: str) -> str:
    surface = value.strip()
    if not surface.startswith("/"):
        return ""
    if surface.startswith("//"):
        return ""
    surface = surface.rstrip(".,:;)]}")
    if len(surface) > 1:
        surface = surface.rstrip("/")
    return surface


def extract_surfaces_from_line(line: str) -> Set[str]:
    matches: Set[str] = set()

    for match in SURFACE_PATTERN.finditer(line):
        normalized = normalize_surface(match.group(1))
        if normalized:
            matches.add(normalized)

    for match in METHOD_SURFACE_PATTERN.finditer(line):
        normalized = normalize_surface(match.group(2))
        if normalized:
            matches.add(normalized)

    for match in BARE_SURFACE_PATTERN.finditer(line):
        normalized = normalize_surface(match.group(1))
        if normalized:
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
