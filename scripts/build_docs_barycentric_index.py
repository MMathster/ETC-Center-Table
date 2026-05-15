#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs' / 'data' / 'barycentric_index.json'
BASE = 'https://faculty.evansville.edu/ck6/encyclopedia/'
MAX_PART = 100
COORD_LABELS = ('Trilinears', 'Barycentrics', 'Tripolars')
COORD_STOP = re.compile(
    r"\s+(?:where|for\b|which\b|See\s+also|Lines|Note|Also|Polar|Coordinates|equals?|Compare|The\s).*",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('\xa0', ' ')).strip()


def page_name(part: int) -> str:
    return 'ETC.html' if part == 1 else f'ETCPart{part}.html'


def html_to_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, 'html.parser')
    lines: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        line = normalize(' '.join(buf))
        if line:
            lines.append(line)
        buf.clear()

    def visit(node) -> None:
        if isinstance(node, NavigableString):
            text = str(node).replace('\n', ' ')
            if text.strip():
                buf.append(text.strip())
            return
        if not isinstance(node, Tag):
            return
        tag = (node.name or '').lower()
        if tag in {'script', 'style', 'noscript'}:
            return
        if tag in {'br', 'hr'}:
            flush()
            return
        if tag in {'h1', 'h2', 'h3', 'h4', 'p', 'div', 'li', 'tr'}:
            flush()
        for child in node.children:
            visit(child)
        if tag in {'h1', 'h2', 'h3', 'h4', 'p', 'div', 'li', 'tr'}:
            flush()

    visit(soup.body or soup)
    flush()
    return lines


def strip_tail(text: str) -> str:
    return COORD_STOP.sub('', normalize(text)).rstrip('.,;').strip()


def extract_coordinate_runs(block_text: str, label: str) -> list[str]:
    labels = '|'.join(COORD_LABELS)
    pattern = re.compile(
        rf'(?:^|\s){label}\s+([\s\S]*?)(?=(?:\s+(?:{labels})\s+)|(?:\s+X\(\d+\)\s*=)|$)',
        re.IGNORECASE,
    )
    rows: list[str] = []
    for match in pattern.finditer(block_text):
        cleaned = strip_tail(match.group(1))
        if cleaned and (label == 'Tripolars' or ':' in cleaned) and cleaned not in rows:
            rows.append(cleaned)
    return rows


def parse_page(html: str, source_page: str) -> list[dict]:
    rows: list[dict] = []
    active: dict | None = None
    header_re = re.compile(r'^X\s*\(\s*(\d+)\s*\)\s*=\s*(.+)$', re.IGNORECASE)

    def finish() -> None:
        nonlocal active
        if not active:
            return
        block = normalize(' '.join(active['lines']))
        barycentrics = extract_coordinate_runs(block, 'Barycentrics')
        if barycentrics:
            trilinears = extract_coordinate_runs(block, 'Trilinears')
            tripolars = extract_coordinate_runs(block, 'Tripolars')
            rows.append({
                'center_id': active['center_id'],
                'name': active['name'],
                'source_page': source_page,
                'source_url': BASE + source_page,
                'barycentrics': barycentrics,
                'trilinears': trilinears,
                'tripolars': tripolars,
                'additional': {
                    'trilinears': trilinears,
                    'barycentrics': barycentrics,
                    'tripolars': tripolars,
                },
                'search_text': ' | '.join([active['center_id'], active['name'], source_page, *trilinears, *barycentrics, *tripolars]),
            })
        active = None

    for line in html_to_lines(html):
        match = header_re.match(line)
        if match:
            finish()
            center_id = f'X({int(match.group(1))})'
            name = normalize(match.group(2)).lstrip('=:—- ').strip() or center_id
            active = {'center_id': center_id, 'name': name, 'lines': []}
        elif active:
            active['lines'].append(line)
    finish()
    return rows


def numeric_id(center_id: str) -> int:
    match = re.search(r'\d+', center_id)
    return int(match.group()) if match else 0


def dedupe_centers(rows: list[dict]) -> list[dict]:
    by_id: set[str] = set()
    by_name: set[str] = set()
    deduped: list[dict] = []
    for row in sorted(rows, key=lambda item: numeric_id(item['center_id'])):
        name_key = normalize(row['name']).lower()
        if row['center_id'] in by_id or name_key in by_name:
            continue
        by_id.add(row['center_id'])
        by_name.add(name_key)
        deduped.append(row)
    return deduped


def fetch_pages() -> tuple[list[dict], list[str]]:
    session = requests.Session()
    pages_seen: list[str] = []
    rows: list[dict] = []
    for part in range(1, MAX_PART + 1):
        page = page_name(part)
        url = BASE + page
        response = session.get(url, timeout=30)
        if response.status_code == 404:
            break
        response.raise_for_status()
        pages_seen.append(page)
        rows.extend(parse_page(response.text, page))
    return dedupe_centers(rows), pages_seen


def main() -> None:
    rows, pages_seen = fetch_pages()
    payload = {
        'meta': {
            'generated_by': 'scripts/build_docs_barycentric_index.py',
            'source': BASE,
            'pages_present': pages_seen,
            'total_centers': len(rows),
            'notes': 'Fallback index for docs/barycentric_search.html when direct browser fetches to ETC are unavailable.',
        },
        'centers': rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {len(rows)} centers from {len(pages_seen)} ETC pages to {OUTPUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
