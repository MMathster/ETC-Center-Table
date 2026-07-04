"use strict";
// etc-live-parser.js — compiled from etc-live-parser.ts
// ROOT CAUSE FIX: two-stage header detection captures all 72k+ centers.
// Only 18,686 were parsed before because "X(n) = Name" on SEPARATE lines
// after a <br> was never matched. The awaitingName flag now grabs the name
// from the NEXT non-coordinate line when the header line has no inline name.
(() => {
  const ETC_BASE_URL = 'https://faculty.evansville.edu/ck6/encyclopedia/';
  const ETC_MAX_PART = 200;
  const MAX_CONSECUTIVE_MISSING_PAGES = 5;
  const MAX_FETCH_RETRIES = 3;
  const BASE_RETRY_DELAY_MS = 350;
  const INTER_PAGE_DELAY_MS = 120;
  const COORDINATE_LABELS = ['Trilinears', 'Barycentrics', 'Tripolars'];

  // Matches the start of a coordinate label line
  const COORD_LABEL_LINE_RE = /^(?:Trilinears?|Barycentrics?|Tripolars?)\s+/i;
  // Full header: "X(n) = Name" on one line
  const HDR_FULL    = /^X\s*\(\s*(\d+)\s*\)\s*=\s*(.+)$/i;
  // Partial header: "X(n) =" or bare "X(n)" — name is on the next line
  const HDR_PARTIAL = /^X\s*\(\s*(\d+)\s*\)\s*=?\s*$/i;

  // ── Pure helpers ────────────────────────────────────────────────────────
  function pageNameForPart(part) {
    return part === 1 ? 'ETC.html' : `ETCPart${part}.html`;
  }
  function normalizeSpace(text = '') {
    return (text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  }
  function stripEtcTail(text) {
    return normalizeSpace(text)
      .replace(/(?:[.;,]\s+|\s{2,})(?:where\b|which\b|See\s+also\b|Also\b|Note:\s|for\s+all\b|Lines\b(?=\s+through|\s+from)|equals?\s+X\(|Compare\s+ETC\b|The\s+point\b)[\s\S]*$/i, '')
      .replace(/[.;,]+$/g, '')
      .trim();
  }
  function delay(ms) { return new Promise(r => setTimeout(r, ms)); }
  function escapeHtml(text = '') {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }
  function numericId(centerId) {
    const m = (centerId || '').match(/\d+/);
    return m ? Number.parseInt(m[0], 10) : 0;
  }

  // ── HTML → structured line list ─────────────────────────────────────────
  function splitEtcLines(root) {
    const lines = [], buffer = [];
    const flush = () => {
      const line = normalizeSpace(buffer.join(' '));
      if (line) lines.push(line);
      buffer.length = 0;
    };
    const visit = node => {
      if (node.nodeType === 3) {
        const t = normalizeSpace(node.nodeValue || '');
        if (t) buffer.push(t);
        return;
      }
      if (node.nodeType !== 1) return;
      const tag = (node.tagName || '').toLowerCase();
      if (['script','style','noscript'].includes(tag)) return;
      if (['br','hr'].includes(tag)) { flush(); return; }
      const isBlock = ['h1','h2','h3','h4','p','div','li','tr'].includes(tag);
      if (isBlock) flush();
      Array.from(node.childNodes).forEach(visit);
      if (isBlock) flush();
    };
    Array.from(root.childNodes).forEach(visit);
    flush();
    return lines;
  }

  // ── Coordinate extraction ────────────────────────────────────────────────
  function extractCoordinateRuns(blockText, label) {
    const results = [];
    const alt = COORDINATE_LABELS.join('|');
    // Non-greedy *? (Bug 8 fix); \s+ before X( (Bug 10 fix)
    const pattern = new RegExp(
      `\\b${label}\\s+([\\s\\S]*?)(?=(?:\\s+(?:${alt})\\s+)|\\s+X\\s*\\(\\d+\\)\\s*=|$)`,
      'gi'
    );
    let match;
    while ((match = pattern.exec(blockText)) !== null) {
      const cleaned = stripEtcTail(match[1]);
      if (cleaned && (label === 'Tripolars' || cleaned.includes(':')) && !results.includes(cleaned)) {
        results.push(cleaned);
      }
    }
    return results;
  }

  // ── Center assembly ──────────────────────────────────────────────────────
  function buildCenter(active, sourcePage) {
    const block        = normalizeSpace(active.lines.join(' '));
    const barycentrics = extractCoordinateRuns(block, 'Barycentrics');
    const trilinears   = extractCoordinateRuns(block, 'Trilinears');
    const tripolars    = extractCoordinateRuns(block, 'Tripolars');
    return {
      center_id:   active.center_id,
      name:        active.name,
      source_page: sourcePage,
      source_url:  ETC_BASE_URL + sourcePage,
      barycentrics,
      trilinears,
      tripolars,
      additional: { trilinears, barycentrics, tripolars },
      search_text: [active.center_id, active.name, sourcePage,
                    ...trilinears, ...barycentrics, ...tripolars].join(' | '),
    };
  }

  // ── HTML parser — TWO-STAGE HEADER DETECTION ─────────────────────────────
  // Stage 1: "X(n) = Name" on one line  → captured directly.
  // Stage 2: "X(n) =" or "X(n)"         → awaitingName=true; next
  //          non-coordinate line becomes the center name.
  function parseEtcHtml(html, sourcePage) {
    const doc    = new DOMParser().parseFromString(html, 'text/html');
    const lines  = splitEtcLines(doc.body || doc);
    const result = [];
    let active = null;
    let awaitingName = false;

    const finish = () => {
      if (!active) return;
      result.push(buildCenter(active, sourcePage));
      active = null;
      awaitingName = false;
    };

    for (const line of lines) {
      // Stage 1 ─ full header
      let m = HDR_FULL.exec(line);
      if (m) {
        finish();
        const name = normalizeSpace(m[2]).replace(/^[=:—\-\s]+/, '') || `X(${m[1]})`;
        active       = { center_id: `X(${Number.parseInt(m[1], 10)})`, name, lines: [] };
        awaitingName = false;
        continue;
      }

      // Stage 2 ─ partial header
      m = HDR_PARTIAL.exec(line);
      if (m) {
        finish();
        active       = { center_id: `X(${Number.parseInt(m[1], 10)})`, name: `X(${m[1]})`, lines: [] };
        awaitingName = true;
        continue;
      }

      if (!active) continue;

      // Grab name from next non-coordinate line after a partial header
      if (awaitingName) {
        if (line.length > 0 && !COORD_LABEL_LINE_RE.test(line)) {
          active.name  = normalizeSpace(line).replace(/^[=:—\-\s]+/, '') || active.name;
          awaitingName = false;
          continue;   // name line — don't add to coord lines
        }
      }

      active.lines.push(line);
    }
    finish();
    return result;
  }

  // ── Normalise + deduplicate (Bug 1 fix: id-only, byName removed) ─────────
  function normalizeCenter(center) {
    const centerId = center.center_id || '';
    const name     = center.name      || '';
    if (!centerId || !name) return null;
    const barycentrics = center.barycentrics || center.additional?.barycentrics || [];
    const trilinears   = center.trilinears   || center.additional?.trilinears   || [];
    const tripolars    = center.tripolars    || center.additional?.tripolars    || [];
    const sourcePage   = center.source_page  || '';
    return {
      center_id: centerId, name, source_page: sourcePage,
      source_url: center.source_url || (sourcePage ? ETC_BASE_URL + sourcePage : ''),
      barycentrics, trilinears, tripolars,
      additional: { trilinears, barycentrics, tripolars },
      search_text: center.search_text ||
        [centerId, name, sourcePage, ...trilinears, ...barycentrics, ...tripolars].join(' | '),
    };
  }
  function dedupeCenters(centers) {
    const byId = new Set();
    const rows = [];
    centers.map(normalizeCenter).filter(c => c !== null)
      .sort((a, b) => numericId(a.center_id) - numericId(b.center_id))
      .forEach(center => {
        if (byId.has(center.center_id)) return;
        byId.add(center.center_id);
        rows.push(center);
      });
    return rows;
  }

  // ── Network helpers ──────────────────────────────────────────────────────
  // Bug 5 fix: proxy first (CORS); Bug 4 fix: cache:'default'
  function proxiedEtcUrl(page) {
    return `https://api.allorigins.win/raw?url=${encodeURIComponent(ETC_BASE_URL + page)}`;
  }
  async function fetchEtcPageText(page) {
    const urls = [proxiedEtcUrl(page), ETC_BASE_URL + page];
    const errors = [];
    for (const url of urls) {
      for (let attempt = 0; attempt < MAX_FETCH_RETRIES; attempt++) {
        try {
          const res = await fetch(url, { cache: 'default' });
          if (res.status === 404) return null;
          if (!res.ok) {
            errors.push(`${url}: HTTP ${res.status} (attempt ${attempt+1})`);
            await delay(BASE_RETRY_DELAY_MS * (attempt + 1));
            continue;
          }
          return await res.text();
        } catch (err) {
          errors.push(`${url}: ${err instanceof Error ? err.message : String(err)} (attempt ${attempt+1})`);
          await delay(BASE_RETRY_DELAY_MS * (attempt + 1));
        }
      }
    }
    throw new Error(`${page}: ${errors.join('; ')}`);
  }

  // ── Main orchestrator ────────────────────────────────────────────────────
  async function fetchLiveEtcCenters(onProgress) {
    const pages = [], centers = [], pageErrors = [];
    let missingInARow = 0;
    for (let part = 1; part <= ETC_MAX_PART; part++) {
      const page = pageNameForPart(part);
      let html;
      try {
        html = await fetchEtcPageText(page);
      } catch (err) {
        pageErrors.push(err instanceof Error ? err.message : String(err));
        if (++missingInARow >= MAX_CONSECUTIVE_MISSING_PAGES) break;
        continue;
      }
      if (html === null) {
        if (++missingInARow >= MAX_CONSECUTIVE_MISSING_PAGES) break;
        continue;
      }
      missingInARow = 0;
      const parsed = parseEtcHtml(html, page);
      pages.push(page);
      centers.push(...parsed);
      onProgress?.({
        message: `Parsed ${centers.length.toLocaleString()} centers from ${pages.length} ETC page${pages.length === 1 ? '' : 's'}…`,
        count: centers.length,
        source: 'Live ETC',
      });
      await delay(INTER_PAGE_DELAY_MS);
    }
    return { centers: dedupeCenters(centers), pages, pageErrors };
  }

  // ── Fallback ─────────────────────────────────────────────────────────────
  async function loadFallbackCenters(fallbackUrl = 'data/barycentric_index.json') {
    const res = await fetch(fallbackUrl, { cache: 'default' });
    if (!res.ok) throw new Error(`fallback JSON HTTP ${res.status}`);
    const payload = await res.json();
    return dedupeCenters(payload.centers || []);
  }
  async function loadCenters(options = {}) {
    try {
      const live = await fetchLiveEtcCenters(options.onProgress);
      if (!live.centers.length) throw new Error('No barycentric centers found in live ETC pages.');
      return { ...live, source: 'Live ETC' };
    } catch (err) {
      const warning = err instanceof Error ? err.message : String(err);
      const centers = await loadFallbackCenters(options.fallbackUrl);
      return { centers, pages: [], pageErrors: [], source: 'Fallback', warning };
    }
  }

  // ── Export ───────────────────────────────────────────────────────────────
  window.EtcLiveParser = {
    ETC_BASE_URL, pageNameForPart, normalizeSpace, escapeHtml,
    parseEtcHtml, dedupeCenters, fetchLiveEtcCenters, loadFallbackCenters, loadCenters,
  };
})();
