#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTRO = ROOT / 'docs' / 'intro.html'
OUTPUT = ROOT / 'docs' / 'data' / 'barycentric_index.json'

CENTER_RE = re.compile(
    r'C\("(?P<center_id>X\(\d+\))","(?P<name>(?:[^"\\]|\\.)*)","(?P<bary>(?:[^"\\]|\\.)*)"',
    re.DOTALL,
)

PAGE_MANIFEST = ['ETC.html', *[f'ETCPart{i}.html' for i in range(2, 37)]]


def _decode_js_string(raw: str) -> str:
    return raw.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').strip()


def build_index() -> dict:
    text = INTRO.read_text(encoding='utf-8')
    centers = []
    for match in CENTER_RE.finditer(text):
        center_id = _decode_js_string(match.group('center_id'))
        name = _decode_js_string(match.group('name'))
        bary = _decode_js_string(match.group('bary'))
        bary_list = [bary] if bary else []
        centers.append(
            {
                'center_id': center_id,
                'name': name,
                'source_page': 'ETC.html',
                'barycentrics': bary_list,
                'search_text': ' | '.join([center_id, name, *bary_list]),
            }
        )

    return {
        'meta': {
            'generated_from': 'docs/intro.html',
            'generated_by': 'scripts/build_docs_barycentric_index.py',
            'notes': 'Fallback index used when live ETC pages are unavailable from the browser; live parsing still runs in docs/barycentric_search.html when the source pages are reachable.',
            'page_manifest': PAGE_MANIFEST,
            'total_centers': len(centers),
            'pages_present': sorted({row['source_page'] for row in centers}),
        },
        'centers': centers,
    }


def main() -> None:
    payload = build_index()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {len(payload["centers"])} centers to {OUTPUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
