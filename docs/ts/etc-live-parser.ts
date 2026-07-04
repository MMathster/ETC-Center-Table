// etc-live-parser.ts
// Optimized for 72 k+ unique ETC triangle centers.
//
// ROOT CAUSE FIX (this revision)
// ─────────────────────────────────────────────────────────────────────────
// Only 18,686 of ~72,000 centers were parsed because the header regex
// required "X(n) = Name" on a SINGLE LINE. In later ETC pages the name
// appears on the NEXT line after a <br>:
//
//   <b>X(<i>50000</i>) =</b><br>
//   Some center description<br>
//   <b>Barycentrics</b> ...
//
// After DOMParser + splitEtcLines, this becomes:
//   Line 1: "X( 50000 ) ="          ← (.+) fails → center SKIPPED
//   Line 2: "Some center description"
//   Line 3: "Barycentrics ..."
//
// FIX: two-stage header detection in parseEtcHtml:
//   Stage 1 – Full header "X(n) = Name" on one line → captured directly.
//   Stage 2 – Partial header "X(n) =" or bare "X(n)" → set awaitingName=true.
//             The next non-coordinate line becomes the center's name.
//
// Previously fixed bugs (retained)
// ─────────────────────────────────────────────────────────────────────────
// Bug 1  dedupeCenters: byName removed; id-only dedup (was ~57% data loss)
// Bug 2  ETC_MAX_PART: 150 → 200
// Bug 3  MAX_CONSECUTIVE_MISSING_PAGES: 3 → 5
// Bug 4  fetch cache: 'no-store' → 'default'
// Bug 5  candidateUrls: proxy first, direct last (CORS)
// Bug 6  PAGE_FETCH_RETRIES + INTER_PAGE_DELAY_MS
// Bug 7  stripEtcTail: removed over-broad stop-words
// Bug 8  extractCoordinateRuns: [\s\S]+ → [\s\S]*? (non-greedy)
// Bug 9  loadFallbackCenters: cache 'no-store' → 'default'
// Bug 10 boundary regex: \sX\( → \s+X\(

interface AdditionalCenterInfo {
  trilinears: string[];
  barycentrics: string[];
  tripolars: string[];
}

interface EtcCenter {
  center_id: string;
  name: string;
  source_page?: string;
  source_url?: string;
  barycentrics: string[];
  trilinears: string[];
  tripolars: string[];
  additional: AdditionalCenterInfo;
  search_text: string;
}

interface FallbackPayload {
  centers?: Partial<EtcCenter>[];
}

interface ParseAccumulator {
  center_id: string;
  name: string;
  lines: string[];
}

interface LoadProgress {
  message: string;
  count: number;
  source: 'Live ETC' | 'Fallback';
}

interface LiveLoadResult {
  centers: EtcCenter[];
  pages: string[];
  pageErrors: string[];
}

interface CenterLoadResult extends LiveLoadResult {
  source: 'Live ETC' | 'Fallback';
  warning?: string;
}

interface LoadOptions {
  onProgress?: (progress: LoadProgress) => void;
  fallbackUrl?: string;
}

interface EtcLiveParserApi {
  ETC_BASE_URL: string;
  pageNameForPart: (part: number) => string;
  normalizeSpace: (text?: string | null) => string;
  escapeHtml: (text?: unknown) => string;
  parseEtcHtml: (html: string, sourcePage: string) => EtcCenter[];
  dedupeCenters: (centers: Partial<EtcCenter>[]) => EtcCenter[];
  fetchLiveEtcCenters: (onProgress?: LoadOptions['onProgress']) => Promise<LiveLoadResult>;
  loadFallbackCenters: (fallbackUrl?: string) => Promise<EtcCenter[]>;
  loadCenters: (options?: LoadOptions) => Promise<CenterLoadResult>;
}

interface Window {
  EtcLiveParser: EtcLiveParserApi;
}

(() => {

// ── Constants ─────────────────────────────────────────────────────────────

const ETC_BASE_URL = 'https://faculty.evansville.edu/ck6/encyclopedia/';
const ETC_MAX_PART = 200;
const MAX_CONSECUTIVE_MISSING_PAGES = 5;
const MAX_FETCH_RETRIES = 3;
const BASE_RETRY_DELAY_MS = 350;
const INTER_PAGE_DELAY_MS = 120;
const COORDINATE_LABELS = ['Trilinears', 'Barycentrics', 'Tripolars'] as const;
type CoordinateLabel = (typeof COORDINATE_LABELS)[number];

// Regex that matches the start of a coordinate label line
const COORD_LABEL_LINE_RE = /^(?:Trilinears?|Barycentrics?|Tripolars?)\s+/i;

// ── Pure helpers ──────────────────────────────────────────────────────────

function pageNameForPart(part: number): string {
  return part === 1 ? 'ETC.html' : `ETCPart${part}.html`;
}

function normalizeSpace(text: string | null | undefined = ''): string {
  return (text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
}

function stripEtcTail(text: string): string {
  return normalizeSpace(text)
    // Require prose-boundary before stop-words so math tokens aren't cut
    .replace(/(?:[.;,]\s+|\s{2,})(?:where\b|which\b|See\s+also\b|Also\b|Note:\s|for\s+all\b|Lines\b(?=\s+through|\s+from)|equals?\s+X\(|Compare\s+ETC\b|The\s+point\b)[\s\S]*$/i, '')
    .replace(/[.;,]+$/g, '')
    .trim();
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function escapeHtml(text: unknown = ''): string {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

function numericId(centerId: string | undefined): number {
  const match = (centerId || '').match(/\d+/);
  return match ? Number.parseInt(match[0], 10) : 0;
}

// ── HTML → structured line list ───────────────────────────────────────────

function splitEtcLines(root: ParentNode): string[] {
  const lines: string[] = [];
  const buffer: string[] = [];

  const flush = (): void => {
    const line = normalizeSpace(buffer.join(' '));
    if (line) lines.push(line);
    buffer.length = 0;
  };

  const visit = (node: Node): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = normalizeSpace(node.nodeValue || '');
      if (text) buffer.push(text);
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;

    const element = node as Element;
    const tag = element.tagName.toLowerCase();
    if (['script', 'style', 'noscript'].includes(tag)) return;
    if (['br', 'hr'].includes(tag)) { flush(); return; }

    const isBlock = ['h1','h2','h3','h4','p','div','li','tr'].includes(tag);
    if (isBlock) flush();
    Array.from(element.childNodes).forEach(visit);
    if (isBlock) flush();
  };

  Array.from(root.childNodes).forEach(visit);
  flush();
  return lines;
}

// ── Coordinate extraction ─────────────────────────────────────────────────

function extractCoordinateRuns(blockText: string, label: CoordinateLabel): string[] {
  const results: string[] = [];
  const alt = COORDINATE_LABELS.join('|');

  // Non-greedy *? with boundary that requires ≥1 space before next label
  // (Bug 8 fix: *? not +) and \s+ before X( (Bug 10 fix)
  const pattern = new RegExp(
    String.raw`\b${label}\s+([\s\S]*?)(?=(?:\s+(?:${alt})\s+)|\s+X\s*\(\d+\)\s*=|$)`,
    'gi',
  );

  let match: RegExpExecArray | null;
  while ((match = pattern.exec(blockText)) !== null) {
    const cleaned = stripEtcTail(match[1]);
    if (cleaned && (label === 'Tripolars' || cleaned.includes(':')) && !results.includes(cleaned)) {
      results.push(cleaned);
    }
  }
  return results;
}

// ── Center assembly ───────────────────────────────────────────────────────

function buildCenter(active: ParseAccumulator, sourcePage: string): EtcCenter {
  const blockText   = normalizeSpace(active.lines.join(' '));
  const barycentrics = extractCoordinateRuns(blockText, 'Barycentrics');
  const trilinears   = extractCoordinateRuns(blockText, 'Trilinears');
  const tripolars    = extractCoordinateRuns(blockText, 'Tripolars');
  const additional   = { trilinears, barycentrics, tripolars };
  return {
    center_id:   active.center_id,
    name:        active.name,
    source_page: sourcePage,
    source_url:  ETC_BASE_URL + sourcePage,
    barycentrics,
    trilinears,
    tripolars,
    additional,
    search_text: [
      active.center_id, active.name, sourcePage,
      ...trilinears, ...barycentrics, ...tripolars,
    ].join(' | '),
  };
}

// ── HTML parser ───────────────────────────────────────────────────────────
//
// ROOT CAUSE FIX: two-stage header detection.
//
// Stage 1 – FULL header "X(n) = Name" on one line:
//   Regex: /^X\s*\(\s*(\d+)\s*\)\s*=\s*(.+)$/i
//   Name extracted directly from the same line.
//
// Stage 2 – PARTIAL header "X(n) =" or bare "X(n)":
//   Regex: /^X\s*\(\s*(\d+)\s*\)\s*=?\s*$/i
//   Name is NOT on this line. Set awaitingName=true and look at
//   the NEXT non-coordinate, non-empty line to use as the name.
//   This handles the ~75% of centers in later ETC pages where a <br>
//   separates the center ID from its descriptive name.

// Full: "X(n) = Name"  (name present on same line)
const HDR_FULL    = /^X\s*\(\s*(\d+)\s*\)\s*=\s*(.+)$/i;
// Partial: "X(n) =" or bare "X(n)"  (name absent or on next line)
const HDR_PARTIAL = /^X\s*\(\s*(\d+)\s*\)\s*=?\s*$/i;

function parseEtcHtml(html: string, sourcePage: string): EtcCenter[] {
  const doc    = new DOMParser().parseFromString(html, 'text/html');
  const lines  = splitEtcLines(doc.body || doc);
  const result: EtcCenter[] = [];
  let active: ParseAccumulator | null = null;
  let awaitingName = false;   // true when we need the NEXT line as the name

  const finish = (): void => {
    if (!active) return;
    result.push(buildCenter(active, sourcePage));
    active       = null;
    awaitingName = false;
  };

  for (const line of lines) {

    // ── Stage 1: full "X(n) = Name" header ────────────────────────────
    const full = HDR_FULL.exec(line);
    if (full) {
      finish();
      const name = normalizeSpace(full[2]).replace(/^[=:—\-\s]+/, '') || `X(${full[1]})`;
      active       = { center_id: `X(${Number.parseInt(full[1], 10)})`, name, lines: [] };
      awaitingName = false;
      continue;
    }

    // ── Stage 2: partial "X(n) =" or bare "X(n)" header ──────────────
    const partial = HDR_PARTIAL.exec(line);
    if (partial) {
      finish();
      // Placeholder name; will be replaced by the next non-label line
      active       = { center_id: `X(${Number.parseInt(partial[1], 10)})`, name: `X(${partial[1]})`, lines: [] };
      awaitingName = true;
      continue;
    }

    if (!active) continue;

    // ── Capture name from the line following a partial header ─────────
    if (awaitingName) {
      // Skip blank lines; skip coordinate label lines
      if (line.length > 0 && !COORD_LABEL_LINE_RE.test(line)) {
        active.name  = normalizeSpace(line).replace(/^[=:—\-\s]+/, '') || active.name;
        awaitingName = false;
        // Do NOT push this line into active.lines — it's the name, not a coord
        continue;
      }
    }

    active.lines.push(line);
  }
  finish();
  return result;
}

// ── Normalise + deduplicate ───────────────────────────────────────────────

function normalizeCenter(center: Partial<EtcCenter>): EtcCenter | null {
  const centerId = center.center_id || '';
  const name     = center.name      || '';
  if (!centerId || !name) return null;

  const barycentrics = center.barycentrics || center.additional?.barycentrics || [];
  const trilinears   = center.trilinears   || center.additional?.trilinears   || [];
  const tripolars    = center.tripolars    || center.additional?.tripolars    || [];
  const sourcePage   = center.source_page  || '';

  return {
    center_id:   centerId,
    name,
    source_page: sourcePage,
    source_url:  center.source_url || (sourcePage ? ETC_BASE_URL + sourcePage : ''),
    barycentrics,
    trilinears,
    tripolars,
    additional: { trilinears, barycentrics, tripolars },
    search_text: center.search_text
      || [centerId, name, sourcePage, ...trilinears, ...barycentrics, ...tripolars].join(' | '),
  };
}

// Bug 1 fix: id-only dedup — byName removed (was ~57% data loss at scale)
function dedupeCenters(centers: Partial<EtcCenter>[]): EtcCenter[] {
  const byId = new Set<string>();
  const rows: EtcCenter[] = [];

  centers
    .map(normalizeCenter)
    .filter((c): c is EtcCenter => c !== null)
    .sort((a, b) => numericId(a.center_id) - numericId(b.center_id))
    .forEach(center => {
      if (byId.has(center.center_id)) return;
      byId.add(center.center_id);
      rows.push(center);
    });

  return rows;
}

// ── Network helpers ───────────────────────────────────────────────────────

// Bug 5 fix: proxy first — CORS blocks direct browser requests to ETC host
function proxiedEtcUrl(page: string): string {
  return `https://api.allorigins.win/raw?url=${encodeURIComponent(ETC_BASE_URL + page)}`;
}

// Bug 4 + 6 fix: cache:'default' + retry with exponential back-off
async function fetchEtcPageText(page: string): Promise<string | null> {
  const urls = [proxiedEtcUrl(page), ETC_BASE_URL + page];
  const errors: string[] = [];

  for (const url of urls) {
    for (let attempt = 0; attempt < MAX_FETCH_RETRIES; attempt += 1) {
      try {
        const response = await fetch(url, { cache: 'default' });
        if (response.status === 404) return null;
        if (!response.ok) {
          errors.push(`${url}: HTTP ${response.status} (attempt ${attempt + 1})`);
          await delay(BASE_RETRY_DELAY_MS * (attempt + 1));
          continue;
        }
        return await response.text();
      } catch (err) {
        errors.push(`${url}: ${err instanceof Error ? err.message : String(err)} (attempt ${attempt + 1})`);
        await delay(BASE_RETRY_DELAY_MS * (attempt + 1));
      }
    }
  }

  throw new Error(`${page}: ${errors.join('; ')}`);
}

// ── Main orchestrator ─────────────────────────────────────────────────────

async function fetchLiveEtcCenters(
  onProgress?: LoadOptions['onProgress'],
): Promise<LiveLoadResult> {
  const pages:      string[]    = [];
  const centers:    EtcCenter[] = [];
  const pageErrors: string[]    = [];
  let missingInARow = 0;

  for (let part = 1; part <= ETC_MAX_PART; part += 1) {
    const page = pageNameForPart(part);
    let html: string | null;

    try {
      html = await fetchEtcPageText(page);
    } catch (err) {
      pageErrors.push(err instanceof Error ? err.message : String(err));
      missingInARow += 1;
      if (missingInARow >= MAX_CONSECUTIVE_MISSING_PAGES) break;
      continue;
    }

    if (html === null) {
      missingInARow += 1;
      if (missingInARow >= MAX_CONSECUTIVE_MISSING_PAGES) break;
      continue;
    }

    missingInARow = 0;
    const parsed = parseEtcHtml(html, page);
    pages.push(page);
    centers.push(...parsed);

    onProgress?.({
      message: `Parsed ${centers.length.toLocaleString()} centers from ${pages.length} ETC page${pages.length === 1 ? '' : 's'}…`,
      count:   centers.length,
      source:  'Live ETC',
    });

    await delay(INTER_PAGE_DELAY_MS);
  }

  return { centers: dedupeCenters(centers), pages, pageErrors };
}

// ── Fallback JSON index ───────────────────────────────────────────────────

async function loadFallbackCenters(fallbackUrl = 'data/barycentric_index.json'): Promise<EtcCenter[]> {
  const response = await fetch(fallbackUrl, { cache: 'default' });
  if (!response.ok) throw new Error(`fallback JSON HTTP ${response.status}`);
  const payload = (await response.json()) as FallbackPayload;
  return dedupeCenters(payload.centers || []);
}

// ── Public entry point ────────────────────────────────────────────────────

async function loadCenters(options: LoadOptions = {}): Promise<CenterLoadResult> {
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

// ── Export ────────────────────────────────────────────────────────────────

window.EtcLiveParser = {
  ETC_BASE_URL,
  pageNameForPart,
  normalizeSpace,
  escapeHtml,
  parseEtcHtml,
  dedupeCenters,
  fetchLiveEtcCenters,
  loadFallbackCenters,
  loadCenters,
};

})();
