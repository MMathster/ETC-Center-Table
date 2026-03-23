#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs' / 'data' / 'barycentric_index.json'
BASE = 'https://faculty.evansville.edu/ck6/encyclopedia/'
BARY_STOP = re.compile(r"\s+(?:where|for\b|which\b|See\s+also|Trilinears|Tripolars|Lines|Note|Also|Polar|Coordinates|equals?|Compare|The\s)", re.IGNORECASE)
MATH_WORDS = frozenset(['sin','cos','tan','cot','sec','csc','sinh','cosh','tanh','sqrt','cbrt','acot','atan','asin','acos','atan2','exp','log','abs','sgn','sign','floor','ceil'])


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()


def node_to_lines(center_node: Tag) -> list[str]:
    lines: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        line = normalize(' '.join(buf))
        if line:
            lines.append(line)
        buf.clear()

    def visit(node) -> None:
        if isinstance(node, NavigableString):
            txt = str(node).replace('\n', ' ')
            if txt.strip():
                buf.append(txt.strip())
        elif isinstance(node, Tag):
            if node.name == 'br':
                flush()
            elif node.name not in ('p', 'hr', 'h3', 'h2'):
                for child in node.children:
                    visit(child)

    node = center_node.next_sibling
    while node:
        if isinstance(node, Tag) and node.name in ('h3', 'h2', 'hr', 'p'):
            break
        visit(node)
        node = node.next_sibling
    flush()
    return lines


def is_math_coord(raw: str) -> bool:
    for part in raw.split(':'):
        words = re.findall(r'[A-Za-z]{4,}', part)
        prose = [w for w in words if w.lower() not in MATH_WORDS]
        if len(prose) >= 2:
            return False
    return True


def extract_funcs(lines: Iterable[str]) -> dict[str, list[str]]:
    funcs: dict[str, list[str]] = {}
    block = ' '.join(lines)
    regex = re.compile(
        r"\b([fghFGH])\s*\(\s*([a-zA-Z])\s*,\s*([a-zA-Z])\s*,\s*([a-zA-Z])\s*\)\s*=\s*(.*?)(?=\s*(?:;|\bfor\b|\bwhere\b|\bBarycentrics\b|\bTrilinears\b)|$)",
        re.IGNORECASE,
    )
    for match in regex.finditer(block):
        name, v1, v2, v3, body = match.groups()
        body = body.replace('[', '(').replace(']', ')').strip().rstrip(',.;')
        funcs[name.lower()] = [v1, v2, v3, body]
    return funcs


def extract_bary_lines(lines: Iterable[str]) -> list[str]:
    results: list[str] = []
    bary_re = re.compile(r'^Barycentrics\s+(.+)', re.IGNORECASE)
    prose_re = re.compile(r'^(?:for|of|are|see|that|in|at|the|and|by|from|to|is)\b', re.IGNORECASE)
    xref_re = re.compile(r'X\s*\(\s*\d', re.IGNORECASE)
    for line in lines:
        match = bary_re.match(line)
        if not match:
            continue
        raw = normalize(match.group(1)).rstrip(',.;')
        if prose_re.match(raw) or xref_re.search(raw):
            continue
        raw = BARY_STOP.split(raw, maxsplit=1)[0].strip().rstrip(',.;')
        if ':' not in raw or not is_math_coord(raw):
            continue
        if raw not in results:
            results.append(raw)
    return results


def parse_page(html: str, source_page: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    rows: list[dict] = []
    for header in soup.find_all(['h3', 'h2']):
        text = normalize(header.get_text(' ', strip=True))
        match = re.search(r'(X\(\d+\))', text)
        if not match:
            continue
        center_id = match.group(1)
        name = text[text.find(center_id) + len(center_id):].lstrip(' :—-').strip() or center_id
        lines = node_to_lines(header)
        barycentrics = extract_bary_lines(lines)
        if not barycentrics:
            continue
        rows.append({
            'center_id': center_id,
            'name': name,
            'source_page': source_page,
            'barycentrics': barycentrics,
            'funcs': extract_funcs(lines),
            'search_text': ' | '.join([center_id, name, source_page, *barycentrics]),
        })
    return rows


def fetch_pages() -> tuple[list[dict], list[str]]:
    session = requests.Session()
    pages_seen: list[str] = []
    rows: list[dict] = []
    for part in range(1, 38):
        page = 'ETC.html' if part == 1 else f'ETCPart{part}.html'
        url = BASE + page
        response = session.get(url, timeout=30)
        if response.status_code == 404:
            break
        response.raise_for_status()
        pages_seen.append(page)
        rows.extend(parse_page(response.text, page))
    return rows, pages_seen


def main() -> None:
    rows, pages_seen = fetch_pages()
    payload = {
        'meta': {
            'generated_by': 'scripts/build_docs_barycentric_index.py',
            'source': BASE,
            'pages_present': pages_seen,
            'total_centers': len(rows),
        },
        'centers': rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {len(rows)} centers from {len(pages_seen)} ETC pages to {OUTPUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
