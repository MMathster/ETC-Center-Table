#!/usr/bin/env python3
"""
build_docs_barycentric_index.py
Scrapes all ETC triangle-center pages and writes docs/data/barycentric_index.json.

ROOT CAUSE FIX (this revision)
────────────────────────────────────────────────────────────────────────────
Only 18,686 of ~72,000 centers were captured because the header regex
required "X(n) = Name" on a SINGLE LINE.  In later ETC pages the name
appears on the NEXT line after a <br> / paragraph boundary:

    <b>X(50000) =</b><br>
    Some center description<br>
    <b>Barycentrics</b> a : b : c

After html_to_lines() this becomes:
    "X(50000) ="          ← (.+) fails → center SKIPPED
    "Some center description"
    "Barycentrics a : b : c"

FIX: two-stage header detection in parse_page():
    Stage 1 – full   "X(n) = Name"  → name extracted from same line.
    Stage 2 – partial "X(n) =" or bare "X(n)"
              → awaiting_name=True; next non-coordinate line is the name.

Previously fixed bugs (retained)
────────────────────────────────────────────────────────────────────────────
Bug 1  dedupe_centers: by_name removed (id-only dedup)
Bug 2  MAX_PART: 150 → 200
Bug 3  MAX_CONSECUTIVE_MISSING_PAGES: 3 → 5
Bug 6  Retry adapter + INTER_PAGE_DELAY_SEC
Bug 7  COORD_STOP: tightened with prose-boundary prefix
Bug 8  extractCoordinateRuns: non-greedy *? pattern (Python re equivalent)
Bug 9  by_name removed from Python dedup
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT   = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs' / 'data' / 'barycentric_index.json'
BASE   = 'https://faculty.evansville.edu/ck6/encyclopedia/'

MAX_PART                      = 200   # Bug 2
MAX_CONSECUTIVE_MISSING_PAGES = 5     # Bug 3
MAX_FETCH_RETRIES             = 3
INTER_PAGE_DELAY_SEC          = 0.15  # Bug 6

COORD_LABELS = ('Trilinears', 'Barycentrics', 'Tripolars')

# Bug 7: require prose-boundary before stop-words (punctuation or ≥2 spaces)
COORD_STOP = re.compile(
    r'(?:[.;,]\s+|\s{2,})'
    r'(?:where\b|which\b|See\s+also\b|Also\b|Note:\s|for\s+all\b'
    r'|Lines\b(?=\s+through|\s+from)|equals?\s+X\('
    r'|Compare\s+ETC\b|The\s+point\b)',
    re.IGNORECASE,
)

# ── Header regexes ────────────────────────────────────────────────────────
# ROOT CAUSE FIX: two patterns instead of one
HDR_FULL    = re.compile(r'^X\s*\(\s*(\d+)\s*\)\s*=\s*(.+)$',   re.IGNORECASE)
HDR_PARTIAL = re.compile(r'^X\s*\(\s*(\d+)\s*\)\s*=?\s*$',       re.IGNORECASE)

# Matches the start of a coordinate-label line
COORD_LABEL_LINE = re.compile(r'^(?:Trilinears?|Barycentrics?|Tripolars?)\s+', re.IGNORECASE)


def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').replace('\xa0', ' ')).strip()


def page_name(part: int) -> str:
    return 'ETC.html' if part == 1 else f'ETCPart{part}.html'


def make_session() -> requests.Session:
    retry = Retry(
        total=MAX_FETCH_RETRIES,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['GET'],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount('https://', adapter)
    session.mount('http://',  adapter)
    return session


def html_to_lines(html: str) -> list[str]:
    """Convert ETC HTML to a list of plain-text lines, one per visual row."""
    soup = BeautifulSoup(html, 'html.parser')
    lines: list[str] = []
    buf:   list[str] = []

    def flush() -> None:
        line = normalize(' '.join(buf))
        if line:
            lines.append(line)
        buf.clear()

    def visit(node) -> None:
        if isinstance(node, NavigableString):
            t = str(node).replace('\n', ' ')
            if t.strip():
                buf.append(t.strip())
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
    """Remove prose annotations from the end of a barycentric expression."""
    m = COORD_STOP.search(text)
    return normalize(text[:m.start()] if m else text).rstrip('.,;').strip()


def extract_coordinate_runs(block_text: str, label: str) -> list[str]:
    """Extract all coordinate expressions for a given label from the block."""
    results: list[str] = []
    labels   = '|'.join(COORD_LABELS)
    # Bug 8 fix: *? non-greedy so we stop at the first next label
    pattern = re.compile(
        rf'\b{label}\s+([\s\S]*?)(?=\s+(?:{labels})\s+|\s+X\s*\(\d+\)\s*=|$)',
        re.IGNORECASE,
    )
    for match in pattern.finditer(block_text):
        cleaned = strip_tail(match.group(1))
        if cleaned and (label == 'Tripolars' or ':' in cleaned) and cleaned not in results:
            results.append(cleaned)
    return results


def parse_page(html: str, source_page: str) -> list[dict]:
    """
    Parse one ETC HTML page into a list of center dicts.

    ROOT CAUSE FIX: two-stage header detection.
    Stage 1 – full header "X(n) = Name" on one line   → direct capture.
    Stage 2 – partial   "X(n) =" or bare "X(n)"        → set awaiting_name;
               next non-coordinate line becomes the center's name.
    """
    lines   = html_to_lines(html)
    centers: list[dict] = []
    active:  dict | None = None
    awaiting_name = False

    def finish() -> None:
        nonlocal active, awaiting_name
        if not active:
            return
        block        = normalize(' '.join(active['lines']))
        barycentrics = extract_coordinate_runs(block, 'Barycentrics')
        trilinears   = extract_coordinate_runs(block, 'Trilinears')
        tripolars    = extract_coordinate_runs(block, 'Tripolars')
        centers.append({
            'center_id':    active['center_id'],
            'name':         active['name'],
            'source_page':  source_page,
            'source_url':   BASE + source_page,
            'barycentrics': barycentrics,
            'trilinears':   trilinears,
            'tripolars':    tripolars,
            'additional': {
                'trilinears':   trilinears,
                'barycentrics': barycentrics,
                'tripolars':    tripolars,
            },
            'search_text': ' | '.join([
                active['center_id'], active['name'], source_page,
                *trilinears, *barycentrics, *tripolars,
            ]),
        })
        active        = None
        awaiting_name = False

    for line in lines:
        # ── Stage 1: full header "X(n) = Name" ───────────────────────────
        m = HDR_FULL.match(line)
        if m:
            finish()
            center_id = f'X({int(m.group(1))})'
            name      = normalize(m.group(2)).lstrip('=:— ').strip() or center_id
            active        = {'center_id': center_id, 'name': name, 'lines': []}
            awaiting_name = False
            continue

        # ── Stage 2: partial header "X(n) =" or bare "X(n)" ─────────────
        m = HDR_PARTIAL.match(line)
        if m:
            finish()
            center_id     = f'X({int(m.group(1))})'
            active        = {'center_id': center_id, 'name': center_id, 'lines': []}
            awaiting_name = True
            continue

        if not active:
            continue

        # ── Capture name from line following a partial header ─────────────
        if awaiting_name:
            if line and not COORD_LABEL_LINE.match(line):
                active['name'] = normalize(line).lstrip('=:— ').strip() or active['name']
                awaiting_name  = False
                continue   # name line — do NOT add to coord block

        active['lines'].append(line)

    finish()
    return centers


def numeric_id(center_id: str) -> int:
    m = re.search(r'\d+', center_id)
    return int(m.group()) if m else 0


# Bug 1 / Bug 9 fix: id-only dedup — by_name removed entirely
def dedupe_centers(rows: list[dict]) -> list[dict]:
    by_id:   set[str]   = set()
    deduped: list[dict] = []
    for row in sorted(rows, key=lambda r: numeric_id(r['center_id'])):
        if row['center_id'] in by_id:
            continue
        by_id.add(row['center_id'])
        deduped.append(row)
    return deduped


def fetch_pages() -> tuple[list[dict], list[str]]:
    session          = make_session()
    pages_seen:  list[str]  = []
    all_rows:    list[dict] = []
    missing_run  = 0

    for part in range(1, MAX_PART + 1):
        page = page_name(part)
        url  = BASE + page
        try:
            resp = session.get(url, timeout=30)
        except requests.RequestException as exc:
            print(f'  WARNING: {page}: {exc} — skipping (not counting as missing)')
            continue

        if resp.status_code == 404:
            missing_run += 1
            if missing_run >= MAX_CONSECUTIVE_MISSING_PAGES:
                break
            continue

        resp.raise_for_status()
        missing_run = 0
        page_rows   = parse_page(resp.text, page)
        pages_seen.append(page)
        all_rows.extend(page_rows)
        print(f'  {page}: {len(page_rows):>5} centers  (running total: {len(all_rows):,})')

        if part < MAX_PART:
            time.sleep(INTER_PAGE_DELAY_SEC)

    return dedupe_centers(all_rows), pages_seen


def main() -> None:
    print(f'Fetching ETC pages from {BASE}')
    rows, pages_seen = fetch_pages()
    payload = {
        'meta': {
            'generated_by': 'scripts/build_docs_barycentric_index.py',
            'source':        BASE,
            'pages_present': pages_seen,
            'total_centers': len(rows),
            'notes': (
                'Fallback index for docs/barycentric_search.html. '
                'Generated by two-stage header detection to capture all 72k+ centers.'
            ),
        },
        'centers': rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    print(f'\nWrote {len(rows):,} centers from {len(pages_seen)} pages → {OUTPUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
