// etc-live-parser.ts
//
// Complete rebuild incorporating structural findings from direct inspection of
// ETC.html and ETCPart2.html (see etc_barycentric_notation_notes.html for the
// full write-up). Every rule below is backed by a real example collected during
// inspection and individually verified before being wired into the pipeline.
// This TypeScript source is the type-annotated origin of etc-live-parser.js --
// logic is kept in exact lockstep between the two; port carefully if editing.
//
// FIX 1 [CRITICAL] Monotonic-id header guard.
//   Every center's own descriptive block contains dozens of sentences that
//   BEGIN with its own header syntax, e.g. inside X(1)'s block:
//     "X(1) = 3R*X(2) + r*X(3) + s*cot(w)*X(6)"
//     "X(1) = isogonal conjugate of X(1)"
//   A naive header regex treats every one of these as a NEW center, silently
//   fragmenting real data. Because ETC lists centers in strictly increasing
//   numeric order, a header is only genuine if its id is STRICTLY GREATER
//   than the currently active center's id.
//
// FIX 2 [CRITICAL] Two-stage header detection.
//   Stage 1: "X(n) = Name" on one line.
//   Stage 2: "X(n) =" or bare "X(n)" -- name is on the NEXT non-coordinate
//   line (ETC's HTML often places a <br> between the id and the name).
//
// FIX 3 [CRITICAL] f(a,b,c):f(b,c,a):f(c,a,b), where f(a,b,c)=<expr>
//   Resolved by simultaneous cyclic substitution of a,b,c (or A,B,C) into
//   the definition to produce 3 concrete weights.
//
// FIX 4 [CRITICAL] Trilinear -> Barycentric derivation (ax:by:cz) applied
//   automatically when a center has Trilinears but no Barycentrics line.
//
// FIX 5 [CRITICAL] Bare-digit exponent disambiguation ("b2" = b^2), skipped
//   entirely when '^' already appears anywhere in the string.
//
// FIX 6 [CRITICAL] Trig space/no-space disambiguation.
//   "sin 2A" (space) = sin(2*A).  "cos2B" (no space) = (cosB)^2.
//
// FIX 7 [MODERATE] Conway SA/SB/SC squaring + concatenated-product split
//   ("SASBSC" -> SA*SB*SC, "SA2" -> SA^2).
//
// FIX 8 [MODERATE] Sqrt[...]/Abs[...]/bare[...] bracket normalization.
//
// FIX 9 [MODERATE] Attribution-comment stripping ("(Name, date)").
//
// FIX 10 [MODERATE] insertMultiplyBeforeParen -- math.js treats "a(b+c)" as
//   a FUNCTION CALL attempt (throws "'a' is not a function"), not implicit
//   multiplication. Every letter/digit/close-paren directly touching an
//   opening paren must get an explicit '*' inserted, EXCEPT for recognized
//   function names (sin/cos/tan/cot/sec/csc/sqrt/abs), which are protected.
//
// TIER 3 (flagged, not automated -- see notes document):
//   - Auxiliary cross-center references ("u : v : w = X(n)")
//   - Fractional/irrational superscript collapse ("31/2" = 3^(1/2)?)
//   - Ambiguous signed-exponent trailing digit ("(expr)- 2")

// ── Type declarations ──────────────────────────────────────────────────────

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
  /** True when barycentrics were mechanically derived from Trilinears
   *  (ax:by:cz rule) because the center provided no native Barycentrics
   *  line -- see FIX 4. */
  derived_from_trilinear: boolean;
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

interface EtcLiveParserInternal {
  normalizeCoordinateExpr: (raw: string) => string;
  cyclicTriple: (expr: string, useAngles: boolean) => [string, string, string];
  resolveNamedCyclicFunction: (rawLine: string, blockText: string) => [string, string, string] | null;
  deriveBarycentricsFromTrilinears: (trilinears: string[]) => string[];
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
  _internal: EtcLiveParserInternal;
}

interface Window {
  EtcLiveParser: EtcLiveParserApi;
}

(() => {

// ── Constants ────────────────────────────────────────────────────────────

const ETC_BASE_URL = 'https://faculty.evansville.edu/ck6/encyclopedia/';
const ETC_MAX_PART = 200;
const MAX_CONSECUTIVE_MISSING_PAGES = 5;
const PAGE_FETCH_RETRIES = 3;
const PAGE_FETCH_BASE_DELAY_MS = 250;
const INTER_PAGE_DELAY_MS = 120;
const COORDINATE_LABELS = ['Trilinears', 'Barycentrics', 'Tripolars'] as const;
const COORD_LABEL_LINE_RE = /^(?:Trilinears?|Barycentrics?|Tripolars?)\s+/i;

const HDR_FULL    = /^X\s*\(\s*(\d+)\s*\)\s*=\s*(.+)$/i;
const HDR_PARTIAL = /^X\s*\(\s*(\d+)\s*\)\s*=?\s*$/i;
const TRIG_FUNCS  = 'sin|cos|tan|cot|sec|csc';

// ── Pure text helpers ──────────────────────────────────────────────────────

function normalizeSpace(text: string | null | undefined): string {
  return (text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
}

function escapeHtml(text: unknown): string {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

function numericId(centerId: string | undefined): number {
  const m = (centerId || '').match(/\d+/);
  return m ? Number.parseInt(m[0], 10) : 0;
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// stripEtcTail: prose stop-words + attribution comments (FIX 9)
function stripEtcTail(text: string): string {
  let out = normalizeSpace(text);
  out = out.replace(/\s*\([A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*)*,\s*[^()]*\d[^()]*\)\s*$/, '');
  out = out.replace(
    /(?:[.;,]\s+|\s{2,})(?:where\b|which\b|See\s+also\b|Also\b|Note:\s|for\s+all\b|Lines\b(?=\s+through|\s+from)|equals?\s+X\(|Compare\s+ETC\b|The\s+point\b)[\s\S]*$/i,
    '',
  );
  out = out.replace(/[.;,]+$/g, '').trim();
  return out;
}

// ── HTML -> structured line list ────────────────────────────────────────────

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
    const isBlock = ['h1', 'h2', 'h3', 'h4', 'p', 'div', 'li', 'tr'].includes(tag);
    if (isBlock) flush();
    Array.from(element.childNodes).forEach(visit);
    if (isBlock) flush();
  };
  Array.from(root.childNodes).forEach(visit);
  flush();
  return lines;
}

// ════════════════════════════════════════════════════════════════════════════
//  NORMALIZATION PIPELINE
// ════════════════════════════════════════════════════════════════════════════

// FIX 8: Sqrt[...] -> sqrt(...), Abs[...] -> abs(...), bare [...] -> (...)
function normalizeBrackets(s: string): string {
  s = s.replace(/\bSqrt\[/gi, 'sqrt(').replace(/\bAbs\[/gi, 'abs(');
  let out = '';
  for (const ch of s) {
    if (ch === '[') out += '(';
    else if (ch === ']') out += ')';
    else out += ch;
  }
  return out;
}

// FIX 7a: SA2/SB2/SC2 -> SA^2/SB^2/SC^2 (must run BEFORE generic exponent rule)
function fixConwaySquares(s: string): string {
  return s.replace(/\bS([ABC])(\d)(?!\d)/g, 'S$1^$2');
}

// FIX 7b: SASBSC (concatenated, no separator) -> SA*SB*SC
function splitConwayProducts(s: string): string {
  return s.replace(/\b(?:S[ABC]){2,}\b/g, m => {
    const tokens = m.match(/S[ABC]/g) as string[];
    return tokens.join('*');
  });
}

// Split concatenated runs of side-length letters a/b/c (no space, no
// operator) into an explicit product: "bc" -> "b*c", "abc" -> "a*b*c".
// Must NEVER touch "sa"/"sb"/"sc" (semiperimeter-difference tokens, which
// start with lowercase 's' and are naturally excluded since 's' is not in
// the [abc] character class this regex matches against).
function splitConcatenatedSides(s: string): string {
  return s.replace(/\b([abc]{2,3})\b/g, m => m.split('').join('*'));
}

// Wrap bare trig arguments: "cos B" -> "cos(B)" (no digit involved -- digit-
// bearing cases like "sin 2A" and "cos2B" are handled separately by
// fixTrigDisambiguation, which runs before this and already inserts parens
// for those, so this only catches the remaining bare-letter form).
function wrapBareTrigArgs(s: string): string {
  return s.replace(new RegExp(`\\b(${TRIG_FUNCS})\\s+([ABC])\\b(?!\\()`, 'g'), '$1($2)');
}

// FIX 10: Insert '*' before an opening paren that directly follows an
// operand (letter/digit/closing-paren) with ZERO whitespace -- e.g.
// "a(b+c)" -> "a*(b+c)". Required because math.js treats "a(...)" as a
// FUNCTION CALL attempt (throwing "'a' is not a function") rather than
// silently inferring multiplication. Recognized function names are
// protected via placeholder substitution so their genuine call syntax
// (e.g. "sin(A)") is never touched.
function insertMultiplyBeforeParen(s: string): string {
  const FUNCS = 'sin|cos|tan|cot|sec|csc|sqrt|abs';
  const funcCallRe = new RegExp(`\\b(?:${FUNCS})\\(`, 'g');
  const PH = '\u0001FUNC\u0001';
  const marked: string[] = [];
  let temp = s.replace(funcCallRe, m => {
    marked.push(m);
    return PH + (marked.length - 1) + PH;
  });
  temp = temp.replace(/([A-Za-z0-9)])\(/g, '$1*(');
  temp = temp.replace(new RegExp(PH + '(\\d+)' + PH, 'g'), (_, i: string) => marked[Number(i)]);
  return temp;
}

// Insert explicit '*' for implicit multiplication. ETC's PRIMARY signal for
// multiplication in this domain is a plain SPACE between two operand tokens
// (e.g. "b c (b + c - a)" means b*c*(b+c-a)) -- unlike many other math-text
// domains, spaces here are not merely cosmetic. This must NOT fire around
// actual operators (+, -, /, ^, etc.), which is why the lookahead only
// checks for an upcoming operand character (letter/digit/open-paren),
// leaving operator-adjacent whitespace untouched.
//
// Uses a lookahead (not a capturing/consuming group) for the "after"
// character so consecutive gaps (e.g. "b c (") are ALL correctly handled in
// a single pass -- a naive consuming regex would only catch every other gap
// due to how global replace advances past matched text.
function addImplicitMultiply(s: string): string {
  s = wrapBareTrigArgs(s);
  s = s.replace(/([A-Za-z0-9)])\s+(?=[A-Za-z0-9(])/g, '$1*');
  s = insertMultiplyBeforeParen(s);
  return s;
}

// FIX 6: trig space/no-space disambiguation.
//   FUNC + digit + (arg) with NO space  -> (FUNC(arg))^digit
//   FUNC + digit + variable  with NO space  -> (FUNC(variable))^digit
//   FUNC + space + digit + variable  -> FUNC(digit*variable)
function fixTrigDisambiguation(s: string): string {
  const F = TRIG_FUNCS;
  s = s.replace(new RegExp(`\\b(${F})(\\d)\\(([^()]*)\\)`, 'g'), '($1($3))^$2');
  s = s.replace(new RegExp(`\\b(${F})(\\d)([A-Z](?:/\\d+)?)`, 'g'), '($1($3))^$2');
  s = s.replace(new RegExp(`\\b(${F})\\s+(\\d+)([A-Z])`, 'g'), '$1($2*$3)');
  return s;
}

// FIX 5: bare-digit exponent disambiguation. Skipped entirely if '^' present.
function fixBareExponents(s: string): string {
  if (s.includes('^')) return s;
  s = s.replace(/\)(\d)(?!\d)/g, ')^$1');
  s = s.replace(/(?<![A-Za-z])([abcRS])(?![A-Za-z])(\d)(?!\d)/g, '$1^$2');
  return s;
}

// Insert '*' for direct digit-to-letter adjacency with ZERO whitespace.
// Covers two distinct real cases with one rule:
//   (a) "2bc"     (bare coefficient prefix)      -> "2*bc"
//   (b) "b^2c^2"  (exponent digit touching the next term's letter,
//                  produced by fixBareExponents just above) -> "b^2*c^2"
// Must run AFTER fixBareExponents (so exponent digits already exist) and
// BEFORE splitConcatenatedSides (so tokens like "bc" gain a proper word-
// boundary once separated from a preceding digit).
function fixDigitLetterAdjacency(s: string): string {
  return s.replace(/(\d)(?=[A-Za-z])/g, '$1*');
}

// Full pipeline, applied to a single extracted coordinate-weight string.
function normalizeCoordinateExpr(raw: string): string {
  let s = raw;
  s = stripEtcTail(s);
  s = normalizeBrackets(s);
  s = fixConwaySquares(s);
  s = splitConwayProducts(s);
  s = fixTrigDisambiguation(s);
  s = fixBareExponents(s);
  s = fixDigitLetterAdjacency(s);
  // Split concatenated a/b/c side-length runs ("bc" -> "b*c") now that any
  // digit-adjacency has already been separated by a '*' above, giving these
  // tokens the word-boundaries the regex requires.
  s = splitConcatenatedSides(s);
  // CRITICAL: insert explicit '*' between remaining fused tokens (e.g.
  // space-separated juxtaposition "b c" -> "b*c", or "a(b+c)" -> "a*(b+c)").
  // Without this, two problems occur: (a) the expression is not valid
  // math.js syntax, and (b) cyclic substitution's \b-word-boundary matching
  // silently fails to find a letter directly adjacent to another token with
  // no separator.
  s = addImplicitMultiply(s);
  return s.trim();
}

// ════════════════════════════════════════════════════════════════════════════
//  CYCLIC SUBSTITUTION (used for ": :" shorthand AND named f(a,b,c) forms)
// ════════════════════════════════════════════════════════════════════════════

function cyclicSubstitute(expr: string, mapping: Record<string, string>): string {
  // Simultaneous substitution via placeholders (avoids double-substitution
  // when e.g. a->b and b->c would otherwise chain incorrectly).
  const placeholders: Record<string, string> = {};
  let temp = expr;
  Object.keys(mapping).forEach((k, i) => {
    const ph = `__PH${i}__`;
    placeholders[ph] = mapping[k];
    temp = temp.replace(new RegExp(`\\b${k}\\b`, 'g'), ph);
  });
  Object.entries(placeholders).forEach(([ph, val]) => {
    temp = temp.replace(new RegExp(ph, 'g'), val);
  });
  return temp;
}

const CYCLE_ABC = { fwd: { a: 'b', b: 'c', c: 'a' }, bwd: { a: 'c', b: 'a', c: 'b' } };
const CYCLE_ANG = { fwd: { A: 'B', B: 'C', C: 'A' }, bwd: { A: 'C', B: 'A', C: 'B' } };

function cyclicTriple(expr: string, useAngles: boolean): [string, string, string] {
  const cyc = useAngles ? CYCLE_ANG : CYCLE_ABC;
  return [expr, cyclicSubstitute(expr, cyc.fwd), cyclicSubstitute(expr, cyc.bwd)];
}

// ════════════════════════════════════════════════════════════════════════════
//  FIX 3: named cyclic-function pattern
//    "f(a,b,c) : f(b,c,a) : f(c,a,b), where f(a,b,c) = <expr>"
// ════════════════════════════════════════════════════════════════════════════

const NAMED_CYCLIC_REF = /^([a-zA-Z]\w*)\(([abcABC]),\s*([abcABC]),\s*([abcABC])\)\s*:/;

function findNamedFunctionDef(blockText: string, fnName: string, vars: [string, string, string]): string | null {
  const pat = new RegExp(
    `\\b${fnName}\\(\\s*${vars[0]}\\s*,\\s*${vars[1]}\\s*,\\s*${vars[2]}\\s*\\)\\s*=\\s*([^;]+?)` +
    `(?=\\bwhere\\b|\\.\\s|\\bTrilinears?\\b|\\bBarycentrics?\\b|\\bTripolars?\\b|\\s{2,}[A-Z]|$)`,
    'i',
  );
  const m = pat.exec(blockText);
  return m ? m[1].trim() : null;
}

function resolveNamedCyclicFunction(rawLine: string, blockText: string): [string, string, string] | null {
  const ref = NAMED_CYCLIC_REF.exec(rawLine.trim());
  if (!ref) return null;
  const fnName = ref[1];
  const v1 = ref[2];
  const useAngles = v1 === 'A' || v1 === 'B' || v1 === 'C';
  const vars: [string, string, string] = useAngles ? ['A', 'B', 'C'] : ['a', 'b', 'c'];
  const defExpr = findNamedFunctionDef(blockText, fnName, vars);
  if (!defExpr) return null;

  // Handle "g(a,b,c) = af(a,b,c)" -- barycentric-derived-from-trilinear idiom
  const innerRef = /^([a-z])\s*([a-zA-Z]\w*)\(([abcABC]),\s*([abcABC]),\s*([abcABC])\)$/.exec(defExpr.replace(/\*/g, ''));
  let resolvedExpr = defExpr;
  if (innerRef) {
    const coeffVar = innerRef[1];
    const innerFn = innerRef[2];
    const innerDef = findNamedFunctionDef(blockText, innerFn, vars);
    if (innerDef) resolvedExpr = `${coeffVar}*(${innerDef})`;
  }

  // CRITICAL: normalize (un-fuse bare-digit exponents, trig-function
  // notation, brackets, Conway products) BEFORE cyclic substitution. Fused
  // tokens like "a2" or "cos2B" have NO word-boundary around the inner
  // letter, so a naive substitution silently fails to touch them --
  // normalizing first inserts the separators that make substitution reliable.
  const normalizedExpr = normalizeCoordinateExpr(resolvedExpr);
  return cyclicTriple(normalizedExpr, useAngles);
}

// ════════════════════════════════════════════════════════════════════════════
//  Coordinate extraction (per label)
// ════════════════════════════════════════════════════════════════════════════

function extractCoordinateRuns(blockText: string, label: string): string[] {
  const results: string[] = [];
  const alt = COORDINATE_LABELS.join('|');
  const pattern = new RegExp(
    `(?:^|\\s)${label}\\s+([\\s\\S]*?)(?=(?:\\s+(?:${alt})\\s+)|(?:\\s+X\\s*\\(\\d+\\)\\s*=)|$)`,
    'gi',
  );

  let match: RegExpExecArray | null;
  while ((match = pattern.exec(blockText)) !== null) {
    const rawRun = match[1].trim();
    if (!rawRun) continue;

    const namedTriple = resolveNamedCyclicFunction(rawRun, blockText);
    if (namedTriple) {
      // Already normalized+substituted inside resolveNamedCyclicFunction
      const normalized = namedTriple.join(' : ');
      if (!results.includes(normalized)) results.push(normalized);
      continue;
    }

    const cleaned = stripEtcTail(rawRun);
    if (!cleaned) continue;
    if (label !== 'Tripolars' && !cleaned.includes(':')) continue;

    const parts = cleaned.split(':').map(p => p.trim());
    let weights: string[];
    if (parts.length >= 3 && parts[1] && parts[2]) {
      // Full three terms already given -- normalize each independently
      weights = parts.map(normalizeCoordinateExpr);
    } else if (parts.length >= 1 && parts[0]) {
      // ": :" cyclic shorthand -- normalize the SINGLE term FIRST (this
      // un-fuses bare exponents/trig notation so word-boundaries exist),
      // THEN cyclically substitute the already-normalized expression.
      const useAngles = /\b[ABC]\b/.test(parts[0]) && !/\b[abc]\b/.test(parts[0]);
      const normalizedFirst = normalizeCoordinateExpr(parts[0]);
      weights = cyclicTriple(normalizedFirst, useAngles);
    } else {
      continue;
    }

    const normalized = weights.join(' : ');
    if (!results.includes(normalized)) results.push(normalized);
  }
  return results;
}

// FIX 4: Trilinear -> Barycentric derivation (ax:by:cz)
function deriveBarycentricsFromTrilinears(trilinears: string[]): string[] {
  if (!trilinears.length) return [];
  return trilinears
    .map(tri => {
      const parts = tri.split(':').map(p => p.trim());
      if (parts.length !== 3) return null;
      return [`a*(${parts[0]})`, `b*(${parts[1]})`, `c*(${parts[2]})`].join(' : ');
    })
    .filter((v): v is string => v !== null);
}

// ── Center assembly ────────────────────────────────────────────────────────

function buildCenter(active: ParseAccumulator, sourcePage: string): EtcCenter {
  const blockText = normalizeSpace(active.lines.join(' '));
  let barycentrics = extractCoordinateRuns(blockText, 'Barycentrics');
  const trilinears = extractCoordinateRuns(blockText, 'Trilinears');
  const tripolars  = extractCoordinateRuns(blockText, 'Tripolars');

  let derivedFromTrilinear = false;
  if (!barycentrics.length && trilinears.length) {
    barycentrics = deriveBarycentricsFromTrilinears(trilinears);
    derivedFromTrilinear = barycentrics.length > 0;
  }

  const additional: AdditionalCenterInfo = { trilinears, barycentrics, tripolars };
  return {
    center_id: active.center_id,
    name: active.name,
    source_page: sourcePage,
    source_url: ETC_BASE_URL + sourcePage,
    barycentrics,
    trilinears,
    tripolars,
    additional,
    derived_from_trilinear: derivedFromTrilinear,
    search_text: [active.center_id, active.name, sourcePage, ...trilinears, ...barycentrics, ...tripolars].join(' | '),
  };
}

// ════════════════════════════════════════════════════════════════════════════
//  HTML PARSER -- two-stage header detection + monotonic-id guard
// ════════════════════════════════════════════════════════════════════════════

function parseEtcHtml(html: string, sourcePage: string): EtcCenter[] {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const lines = splitEtcLines(doc.body || doc);
  const result: EtcCenter[] = [];
  let active: ParseAccumulator | null = null;
  let activeNum = -1;          // FIX 1: tracks the currently-active center's numeric id
  let awaitingName = false;    // FIX 2: true when the name is expected on the next line

  const finish = (): void => {
    if (!active) return;
    result.push(buildCenter(active, sourcePage));
    active = null;
    awaitingName = false;
  };

  for (const line of lines) {
    let m = HDR_FULL.exec(line);
    if (m) {
      const n = Number.parseInt(m[1], 10);
      // FIX 1: only treat as a NEW header if n is strictly greater than the
      // currently active center's id (or no active center yet). Self-
      // referential relation lines inside a center's own block (e.g.
      // "X(1) = isogonal conjugate of X(1)") repeat the SAME id and must
      // NOT be treated as new headers.
      if (active === null || n > activeNum) {
        finish();
        activeNum = n;
        const name = normalizeSpace(m[2]).replace(/^[=:\u2014\-\s]+/, '') || `X(${n})`;
        active = { center_id: `X(${n})`, name, lines: [] };
        awaitingName = false;
        continue;
      }
      // else: self-referential -- falls through to be appended as content
    } else {
      m = HDR_PARTIAL.exec(line);
      if (m) {
        const n = Number.parseInt(m[1], 10);
        if (active === null || n > activeNum) {
          finish();
          activeNum = n;
          active = { center_id: `X(${n})`, name: `X(${n})`, lines: [] };
          awaitingName = true;
          continue;
        }
      }
    }

    if (!active) continue;

    // FIX 2: capture name from the line following a partial header
    if (awaitingName) {
      if (line.length > 0 && !COORD_LABEL_LINE_RE.test(line)) {
        active.name = normalizeSpace(line).replace(/^[=:\u2014\-\s]+/, '') || active.name;
        awaitingName = false;
        continue; // name line -- do not add to coordinate content
      }
    }

    active.lines.push(line);
  }
  finish();
  return result;
}

// ── Normalise + deduplicate (id-only; center_id is the true unique key) ────

function normalizeCenter(center: Partial<EtcCenter>): EtcCenter | null {
  const centerId = center.center_id || '';
  const name = center.name || '';
  if (!centerId || !name) return null;

  const barycentrics = center.barycentrics || center.additional?.barycentrics || [];
  const trilinears   = center.trilinears   || center.additional?.trilinears   || [];
  const tripolars    = center.tripolars    || center.additional?.tripolars    || [];
  const sourcePage   = center.source_page  || '';
  return {
    center_id: centerId,
    name,
    source_page: sourcePage,
    source_url: center.source_url || (sourcePage ? ETC_BASE_URL + sourcePage : ''),
    barycentrics,
    trilinears,
    tripolars,
    additional: { trilinears, barycentrics, tripolars },
    derived_from_trilinear: !!center.derived_from_trilinear,
    search_text: center.search_text || [centerId, name, sourcePage, ...trilinears, ...barycentrics, ...tripolars].join(' | '),
  };
}

function dedupeCenters(centers: Partial<EtcCenter>[]): EtcCenter[] {
  const byId = new Set<string>();
  const rows: EtcCenter[] = [];

  centers
    .map(normalizeCenter)
    .filter((c): c is EtcCenter => c !== null)
    .sort((a, b) => numericId(a.center_id) - numericId(b.center_id))
    .forEach(center => {
      if (byId.has(center.center_id)) return; // id-only uniqueness
      byId.add(center.center_id);
      rows.push(center);
    });

  return rows;
}

// ── Network helpers ──────────────────────────────────────────────────────

function proxiedEtcUrl(page: string): string {
  return `https://api.allorigins.win/raw?url=${encodeURIComponent(ETC_BASE_URL + page)}`;
}

async function fetchEtcPageText(page: string): Promise<string | null> {
  const urls = [proxiedEtcUrl(page), ETC_BASE_URL + page];
  const errors: string[] = [];

  for (const url of urls) {
    for (let attempt = 1; attempt <= PAGE_FETCH_RETRIES; attempt += 1) {
      try {
        const response = await fetch(url, { cache: 'default' });
        if (response.status === 404) return null;
        if (!response.ok) {
          errors.push(`${url}: HTTP ${response.status} (attempt ${attempt})`);
        } else {
          return await response.text();
        }
      } catch (err) {
        errors.push(`${url}: ${err instanceof Error ? err.message : String(err)} (attempt ${attempt})`);
      }
      if (attempt < PAGE_FETCH_RETRIES) {
        await sleep(PAGE_FETCH_BASE_DELAY_MS * 2 ** (attempt - 1));
      }
    }
  }

  throw new Error(`${page}: ${errors.join('; ')}`);
}

function pageNameForPart(part: number): string {
  return part === 1 ? 'ETC.html' : `ETCPart${part}.html`;
}

async function fetchLiveEtcCenters(onProgress?: LoadOptions['onProgress']): Promise<LiveLoadResult> {
  const pages: string[] = [];
  const centers: EtcCenter[] = [];
  const pageErrors: string[] = [];
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
      message: `Parsed ${centers.length.toLocaleString()} centers from ${pages.length} ETC page${pages.length === 1 ? '' : 's'}\u2026`,
      count: centers.length,
      source: 'Live ETC',
    });
    await sleep(INTER_PAGE_DELAY_MS);
  }

  return { centers: dedupeCenters(centers), pages, pageErrors };
}

async function loadFallbackCenters(fallbackUrl = 'data/barycentric_index.json'): Promise<EtcCenter[]> {
  const response = await fetch(fallbackUrl, { cache: 'default' });
  if (!response.ok) throw new Error(`fallback JSON HTTP ${response.status}`);
  const payload = (await response.json()) as FallbackPayload;
  return dedupeCenters(payload.centers || []);
}

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

// ── Export ──────────────────────────────────────────────────────────────

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
  // Exposed for testing / debugging the normalization pipeline directly
  _internal: {
    normalizeCoordinateExpr,
    cyclicTriple,
    resolveNamedCyclicFunction,
    deriveBarycentricsFromTrilinears,
  },
};

})();
