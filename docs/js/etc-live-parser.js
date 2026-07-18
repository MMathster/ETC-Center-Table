"use strict";
// etc-live-parser.js
//
// Complete implementation built from direct inspection of ETC.html and
// ETCPart2.html (structural findings) plus the University of Evansville's
// current 42-part page structure (verified directly: Part 42 is a
// placeholder -- "Part X(42) will be started in the future" -- while real
// content currently extends somewhat beyond X(72800) and continues to grow
// periodically). See notes for the full narrative; this header summarizes
// every fix implemented.
//
// FIX 1 [CRITICAL] Monotonic-id header guard.
//   Every center's own descriptive block contains sentences that BEGIN
//   with its own header syntax, e.g. inside X(1)'s block:
//     "X(1) = 3R*X(2) + r*X(3) + s*cot(w)*X(6)"
//     "X(1) = isogonal conjugate of X(1)"
//   A naive header regex treats every one of these as a NEW center,
//   fragmenting real data. Since ETC lists centers in strictly increasing
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
// FIX 5 [CRITICAL] Bare-digit exponent disambiguation ("b2" = b^2). The
//   whole-string "skip if any ^ present" gate has been REMOVED (it was
//   overly broad and silently failed on MIXED-style expressions where
//   some terms are already explicit and others are still bare-digit --
//   the regex's own local adjacency requirement already prevents
//   double-processing of a term that already has "^" directly after its
//   letter, making the string-wide gate both unnecessary and harmful).
//
// FIX 6 [CRITICAL] Trig space/no-space disambiguation.
//   "sin 2A" (space) = sin(2*A).  "cos2B" (no space) = (cosB)^2.
//
// FIX 7 [MODERATE] Conway SA/SB/SC squaring + concatenated-product split.
//   "SASBSC" -> SA*SB*SC, "SA2" -> SA^2. splitConwayProducts now runs
//   BEFORE fixConwaySquares, and its trailing boundary was changed from
//   \b to (?![A-Za-z]) -- the strict \b failed whenever the concatenated
//   run was immediately followed by a digit with no separator (letters
//   and digits are both \w, so no boundary exists between them), which
//   silently left terms like "SASBSC2" completely unsplit.
//
// FIX 8 [MODERATE] Sqrt[...]/Abs[...]/bare[...] bracket normalization.
//
// FIX 9 [MODERATE] Attribution-comment stripping ("(Name, date)").
//
// FIX 10 [MODERATE] insertMultiplyBeforeParen -- math.js treats "a(b+c)"
//   as a FUNCTION CALL attempt (throws "'a' is not a function"), not
//   implicit multiplication. Every letter/digit/close-paren directly
//   touching an opening paren gets an explicit '*' inserted, except
//   recognized function names, which are protected.
//
// FIX 11 [NEW] Unicode superscript character handling. ETC's HTML encodes
//   exponents in at least three different ways depending on how each
//   entry was authored/rendered: (a) an actual <sup>2</sup> tag, which
//   text-extraction flattens to a bare ASCII digit fused to the preceding
//   letter (already handled by FIX 5); (b) a literal/entity Unicode
//   superscript character (e.g. "b²", possibly from &sup2; or a directly
//   pasted glyph), which is NOT an ASCII digit and was previously invisible
//   to every existing rule; (c) an explicitly typed "^2" (already correct).
//   normalizeUnicodeSuperscripts() converts case (b) to a PLAIN ASCII
//   digit (deliberately WITHOUT inserting a caret itself), letting the
//   existing, already-tested bare-digit pipeline (Conway squares, trig
//   disambiguation, bare exponents) handle caret-insertion exactly as it
//   already does for case (a) -- this correctly distinguishes "sin²A"
//   (function-squared) from "b²" (variable-squared) using the SAME logic,
//   without special-casing. Negative superscript exponents (e.g. "a⁻²")
//   are converted directly to an explicit "^(-2)" form, since the Unicode
//   superscript minus is UNAMBIGUOUS -- unlike a bare ASCII "- 2" trailing
//   a term, which is indistinguishable from ordinary subtraction and
//   remains a documented, deliberately unresolved Tier-3 case.
//
// FIX 12 [NEW] Relations/formulas extraction. Self-referential
//   "X(<active id>) = ..." lines inside a center's own block (linear
//   combinations, conjugate/transform notes, midpoint relations, etc.)
//   are captured into a dedicated `relations` array (deduped, capped at
//   30 per center) in addition to remaining in the general content
//   buffer -- exposed for UI features such as a hover-window "other
//   formulas" section.
//
// FIX 13 [NEW] No hardcoded maximum center id. ETC is updated periodically
//   by the University of Evansville and has already grown past prior
//   known counts; earlier revisions of this parser used a fixed ceiling
//   (72800) to reject implausible header matches, but this was explicitly
//   removed per instruction, since it would incorrectly reject genuine new
//   centers as ETC continues to expand. Protection against spurious
//   header-like matches instead relies on: (a) strict line-start anchoring
//   in HDR_FULL/HDR_PARTIAL (verified directly against real ETC
//   placeholder/stub text -- e.g. "Part X(42) will be started in the
//   future." and "X(84001) etc." -- neither of which matches either
//   pattern, since both lack a trailing "=" immediately after the closing
//   parenthesis followed by real content, or reaching line-end right
//   after the parenthesis); (b) the monotonic-id guard (FIX 1), which
//   scales automatically with however far ETC has grown.
//
// FIX 14 [NEW] Empty-page-as-miss heuristic. ETC pre-creates placeholder
//   page files ahead of real content -- verified directly: a page can
//   return HTTP 200 while containing zero actual "X(n) = Name" entries.
//   Such a page is now treated the same as a missing (404) page for the
//   early-stopping counter, so page discovery correctly halts soon after
//   reaching ETC's current growth frontier instead of grinding through
//   every placeholder page up to the loop's generous outer ceiling. This
//   requires no fixed page-count or center-id constant -- it reacts to
//   actual page content.
(() => {

  // ── Constants ────────────────────────────────────────────────────────────
  const ETC_BASE_URL = 'https://faculty.evansville.edu/ck6/encyclopedia/';
  const ETC_MAX_PART = 200; // generous outer loop ceiling, not a real limit
  const MAX_CONSECUTIVE_MISSING_PAGES = 5;
  const PAGE_FETCH_RETRIES = 3;
  const PAGE_FETCH_BASE_DELAY_MS = 250;
  const INTER_PAGE_DELAY_MS = 120;
  const COORDINATE_LABELS = ['Trilinears', 'Barycentrics', 'Tripolars'];
  const COORD_LABEL_LINE_RE = /^(?:Trilinears?|Barycentrics?|Tripolars?)\s+/i;
  const RELATIONS_CAP = 30;

  // See FIX 13: no hardcoded maximum center id is used. Protection against
  // spurious header matches relies purely on regex anchoring (below) and
  // the monotonic-id guard in parseEtcHtml.
  const HDR_FULL    = /^X\s*\(\s*(\d+)\s*\)\s*=\s*(.+)$/i;
  const HDR_PARTIAL = /^X\s*\(\s*(\d+)\s*\)\s*=?\s*$/i;
  const TRIG_FUNCS  = 'sin|cos|tan|cot|sec|csc';

  // ── Pure text helpers ────────────────────────────────────────────────────
  function normalizeSpace(text) {
    return (text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  }
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }
  function numericId(centerId) {
    const m = (centerId || '').match(/\d+/);
    return m ? Number.parseInt(m[0], 10) : 0;
  }
  function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

  // stripEtcTail: prose stop-words + attribution comments (FIX 9)
  function stripEtcTail(text) {
    let out = normalizeSpace(text);
    out = out.replace(/\s*\([A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*)*,\s*[^()]*\d[^()]*\)\s*$/, '');
    out = out.replace(/(?:[.;,]\s+|\s{2,})(?:where\b|which\b|See\s+also\b|Also\b|Note:\s|for\s+all\b|Lines\b(?=\s+through|\s+from)|equals?\s+X\(|Compare\s+ETC\b|The\s+point\b)[\s\S]*$/i, '');
    out = out.replace(/[.;,]+$/g, '').trim();
    return out;
  }

  // ── HTML -> structured line list ─────────────────────────────────────────
  function splitEtcLines(root) {
    const lines = [];
    const buffer = [];
    const flush = () => {
      const line = normalizeSpace(buffer.join(' '));
      if (line) lines.push(line);
      buffer.length = 0;
    };
    const visit = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const text = normalizeSpace(node.nodeValue || '');
        if (text) buffer.push(text);
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag = node.tagName.toLowerCase();
      if (['script', 'style', 'noscript'].includes(tag)) return;
      if (['br', 'hr'].includes(tag)) { flush(); return; }
      const isBlock = ['h1', 'h2', 'h3', 'h4', 'p', 'div', 'li', 'tr'].includes(tag);
      if (isBlock) flush();
      Array.from(node.childNodes).forEach(visit);
      if (isBlock) flush();
    };
    Array.from(root.childNodes).forEach(visit);
    flush();
    return lines;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  NORMALIZATION PIPELINE
  // ════════════════════════════════════════════════════════════════════════

  // FIX 11: convert Unicode superscript glyphs to plain ASCII digits (no
  // caret inserted here except for the unambiguous negative-exponent case).
  function normalizeUnicodeSuperscripts(s) {
    const supDigitMap = { '⁰':'0','¹':'1','²':'2','³':'3','⁴':'4','⁵':'5','⁶':'6','⁷':'7','⁸':'8','⁹':'9' };
    // Negative superscript exponents are unambiguous (unlike bare ASCII
    // "- 2", which could be ordinary subtraction) -- convert directly.
    s = s.replace(/([A-Za-z0-9)])⁻([⁰¹²³⁴⁵⁶⁷⁸⁹]+)/g, (full, prefix, digits) => {
      const ascii = digits.split('').map(ch => supDigitMap[ch]).join('');
      return `${prefix}^(-${ascii})`;
    });
    // Positive superscripts: glyph -> plain digit only. Downstream steps
    // (fixConwaySquares, fixTrigDisambiguation, fixBareExponents) handle
    // caret-insertion exactly as they already do for tag-stripped bare
    // digits, correctly distinguishing e.g. "sin²A" from "b²" for free.
    s = s.replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹]/g, ch => supDigitMap[ch]);
    return s;
  }

  // FIX 8: Sqrt[...] -> sqrt(...), Abs[...] -> abs(...), bare [...] -> (...)
  function normalizeBrackets(s) {
    s = s.replace(/\bSqrt\[/gi, 'sqrt(').replace(/\bAbs\[/gi, 'abs(');
    let out = '';
    for (const ch of s) {
      if (ch === '[') out += '(';
      else if (ch === ']') out += ')';
      else out += ch;
    }
    return out;
  }

  // FIX 7: SASBSC (concatenated, no separator) -> SA*SB*SC. Trailing
  // boundary uses (?![A-Za-z]) rather than \b so the match correctly ends
  // even when immediately followed by a digit (e.g. the "2" in "SASBSC2"),
  // which fixConwaySquares handles on the next step once properly isolated.
  function splitConwayProducts(s) {
    return s.replace(/\b(?:S[ABC]){2,}(?![A-Za-z])/g, m => {
      const tokens = m.match(/S[ABC]/g);
      return tokens.join('*');
    });
  }

  // FIX 7: SA2/SB2/SC2 -> SA^2/SB^2/SC^2. Must run AFTER splitConwayProducts
  // so a trailing squared term within a longer concatenated run has a
  // proper word-boundary to match against.
  function fixConwaySquares(s) {
    return s.replace(/\bS([ABC])(\d)(?!\d)/g, 'S$1^$2');
  }

  // Split concatenated runs of side-length letters a/b/c (no space, no
  // operator) into an explicit product: "bc" -> "b*c", "abc" -> "a*b*c".
  // Must NEVER touch "sa"/"sb"/"sc" (semiperimeter-difference tokens,
  // which start with lowercase 's' and are excluded since 's' is not in
  // the [abc] character class this regex matches against).
  function splitConcatenatedSides(s) {
    return s.replace(/\b([abc]{2,3})\b/g, m => m.split('').join('*'));
  }

  // Wrap bare trig arguments: "cos B" -> "cos(B)" (no digit involved --
  // digit-bearing cases like "sin 2A" and "cos2B" are handled separately
  // by fixTrigDisambiguation, which runs before this and already inserts
  // parens for those, so this only catches the remaining bare-letter form).
  function wrapBareTrigArgs(s) {
    return s.replace(new RegExp(`\\b(${TRIG_FUNCS})\\s+([ABC])\\b(?!\\()`, 'g'), '$1($2)');
  }

  // FIX 10: insert '*' before an opening paren that directly follows an
  // operand (letter/digit/closing-paren) with ZERO whitespace -- e.g.
  // "a(b+c)" -> "a*(b+c)". Required because math.js treats "a(...)" as a
  // FUNCTION CALL attempt (throwing "'a' is not a function") rather than
  // silently inferring multiplication. Recognized function names are
  // protected via placeholder substitution so their genuine call syntax
  // (e.g. "sin(A)") is never touched.
  function insertMultiplyBeforeParen(s) {
    const FUNCS = 'sin|cos|tan|cot|sec|csc|sqrt|abs';
    const funcCallRe = new RegExp(`\\b(?:${FUNCS})\\(`, 'g');
    const PH = '\u0001FUNC\u0001';
    const marked = [];
    let temp = s.replace(funcCallRe, m => {
      marked.push(m);
      return PH + (marked.length - 1) + PH;
    });
    temp = temp.replace(/([A-Za-z0-9)])\(/g, '$1*(');
    temp = temp.replace(new RegExp(PH + '(\\d+)' + PH, 'g'), (_, i) => marked[Number(i)]);
    return temp;
  }

  // Insert explicit '*' for implicit multiplication. ETC's PRIMARY signal
  // for multiplication in this domain is a plain SPACE between two operand
  // tokens (e.g. "b c (b + c - a)" means b*c*(b+c-a)) -- spaces here are
  // not merely cosmetic. Must NOT fire around actual operators, which is
  // why the lookahead only checks for an upcoming operand character.
  function addImplicitMultiply(s) {
    s = wrapBareTrigArgs(s);
    s = s.replace(/([A-Za-z0-9)])\s+(?=[A-Za-z0-9(])/g, '$1*');
    s = insertMultiplyBeforeParen(s);
    return s;
  }

  // FIX 6: trig space/no-space disambiguation.
  //   FUNC + digit + (arg) with NO space  -> (FUNC(arg))^digit
  //   FUNC + digit + variable  with NO space  -> (FUNC(variable))^digit
  //   FUNC + space + digit + variable  -> FUNC(digit*variable)
  function fixTrigDisambiguation(s) {
    const F = TRIG_FUNCS;
    s = s.replace(new RegExp(`\\b(${F})(\\d)\\(([^()]*)\\)`, 'g'), '($1($3))^$2');
    s = s.replace(new RegExp(`\\b(${F})(\\d)([A-Z](?:/\\d+)?)`, 'g'), '($1($3))^$2');
    s = s.replace(new RegExp(`\\b(${F})\\s+(\\d+)([A-Z])`, 'g'), '$1($2*$3)');
    return s;
  }

  // FIX 5: bare-digit exponent disambiguation. The whole-string "skip if
  // includes ^" gate has been REMOVED -- the regex's own local adjacency
  // requirement (the digit must be immediately adjacent to the letter,
  // not separated by an existing "^") already makes an already-explicit
  // term like "a^2" naturally immune, without needing a string-wide check
  // that would otherwise skip processing OTHER, still-bare terms in a
  // mixed-style expression.
  function fixBareExponents(s) {
    s = s.replace(/\)(\d)(?!\d)/g, ')^$1');
    s = s.replace(/(?<![A-Za-z])([abcRS])(?![A-Za-z])(\d)(?!\d)/g, '$1^$2');
    return s;
  }

  // Insert '*' for direct digit-to-letter adjacency with ZERO whitespace.
  // Covers two distinct real cases with one rule:
  //   (a) "2bc"     (bare coefficient prefix)      -> "2*bc"
  //   (b) "b^2c^2"  (exponent digit touching the next term's letter,
  //                  produced by fixBareExponents just above) -> "b^2*c^2"
  function fixDigitLetterAdjacency(s) {
    return s.replace(/(\d)(?=[A-Za-z])/g, '$1*');
  }

  // Full pipeline, applied to a single extracted coordinate-weight string.
  function normalizeCoordinateExpr(raw) {
    let s = raw;
    s = stripEtcTail(s);
    s = normalizeUnicodeSuperscripts(s);          // FIX 11
    s = normalizeBrackets(s);
    s = splitConwayProducts(s);                   // FIX 7 (reordered)
    s = fixConwaySquares(s);                      // FIX 7
    s = fixTrigDisambiguation(s);                 // FIX 6
    s = fixBareExponents(s);                      // FIX 5 (gate removed)
    s = fixDigitLetterAdjacency(s);
    s = splitConcatenatedSides(s);
    s = addImplicitMultiply(s);                   // FIX 10
    return s.trim();
  }

  // ════════════════════════════════════════════════════════════════════════
  //  CYCLIC SUBSTITUTION
  // ════════════════════════════════════════════════════════════════════════

  function cyclicSubstitute(expr, mapping) {
    const placeholders = {};
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

  function cyclicTriple(expr, useAngles) {
    const cyc = useAngles ? CYCLE_ANG : CYCLE_ABC;
    return [expr, cyclicSubstitute(expr, cyc.fwd), cyclicSubstitute(expr, cyc.bwd)];
  }

  // ════════════════════════════════════════════════════════════════════════
  //  FIX 3: named cyclic-function pattern
  // ════════════════════════════════════════════════════════════════════════

  const NAMED_CYCLIC_REF = /^([a-zA-Z]\w*)\(([abcABC]),\s*([abcABC]),\s*([abcABC])\)\s*:/;

  function findNamedFunctionDef(blockText, fnName, vars) {
    const pat = new RegExp(
      `\\b${fnName}\\(\\s*${vars[0]}\\s*,\\s*${vars[1]}\\s*,\\s*${vars[2]}\\s*\\)\\s*=\\s*([^;]+?)` +
      `(?=\\bwhere\\b|\\.\\s|\\bTrilinears?\\b|\\bBarycentrics?\\b|\\bTripolars?\\b|\\s{2,}[A-Z]|$)`,
      'i',
    );
    const m = pat.exec(blockText);
    return m ? m[1].trim() : null;
  }

  function resolveNamedCyclicFunction(rawLine, blockText) {
    const ref = NAMED_CYCLIC_REF.exec(rawLine.trim());
    if (!ref) return null;
    const fnName = ref[1];
    const v1 = ref[2];
    const useAngles = v1 === 'A' || v1 === 'B' || v1 === 'C';
    const vars = useAngles ? ['A', 'B', 'C'] : ['a', 'b', 'c'];
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

    // Normalize BEFORE cyclic substitution -- fused tokens like "a2" or
    // "cos2B" have no word-boundary around the inner letter until
    // normalized, so substitution would silently miss them otherwise.
    const normalizedExpr = normalizeCoordinateExpr(resolvedExpr);
    return cyclicTriple(normalizedExpr, useAngles);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  Coordinate extraction (per label)
  // ════════════════════════════════════════════════════════════════════════

  function extractCoordinateRuns(blockText, label) {
    const results = [];
    const alt = COORDINATE_LABELS.join('|');
    const pattern = new RegExp(
      `(?:^|\\s)${label}\\s+([\\s\\S]*?)(?=(?:\\s+(?:${alt})\\s+)|(?:\\s+X\\s*\\(\\d+\\)\\s*=)|$)`,
      'gi',
    );

    let match;
    while ((match = pattern.exec(blockText)) !== null) {
      const rawRun = match[1].trim();
      if (!rawRun) continue;

      const namedTriple = resolveNamedCyclicFunction(rawRun, blockText);
      if (namedTriple) {
        const normalized = namedTriple.join(' : ');
        if (!results.includes(normalized)) results.push(normalized);
        continue;
      }

      const cleaned = stripEtcTail(rawRun);
      if (!cleaned) continue;
      if (label !== 'Tripolars' && !cleaned.includes(':')) continue;

      const parts = cleaned.split(':').map(p => p.trim());
      let weights;
      if (parts.length >= 3 && parts[1] && parts[2]) {
        weights = parts.map(normalizeCoordinateExpr);
      } else if (parts.length >= 1 && parts[0]) {
        // Normalize the SINGLE term first (un-fuses bare exponents/trig
        // notation so word-boundaries exist), THEN cyclically substitute.
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
  function deriveBarycentricsFromTrilinears(trilinears) {
    if (!trilinears.length) return [];
    return trilinears.map(tri => {
      const parts = tri.split(':').map(p => p.trim());
      if (parts.length !== 3) return null;
      return [`a*(${parts[0]})`, `b*(${parts[1]})`, `c*(${parts[2]})`].join(' : ');
    }).filter(Boolean);
  }

  // ── Center assembly ──────────────────────────────────────────────────────
  function buildCenter(active, sourcePage) {
    const blockText = normalizeSpace(active.lines.join(' '));
    let barycentrics = extractCoordinateRuns(blockText, 'Barycentrics');
    const trilinears = extractCoordinateRuns(blockText, 'Trilinears');
    const tripolars  = extractCoordinateRuns(blockText, 'Tripolars');

    let derivedFromTrilinear = false;
    if (!barycentrics.length && trilinears.length) {
      barycentrics = deriveBarycentricsFromTrilinears(trilinears);
      derivedFromTrilinear = barycentrics.length > 0;
    }

    // FIX 12: relations/formulas -- dedupe and cap for storage efficiency
    // at large scale (some centers have 50+ relation lines).
    const seenRelations = new Set();
    const relations = [];
    for (const r of active.relations || []) {
      if (seenRelations.has(r)) continue;
      seenRelations.add(r);
      relations.push(r);
      if (relations.length >= RELATIONS_CAP) break;
    }

    const additional = { trilinears, barycentrics, tripolars };
    return {
      center_id: active.center_id,
      name: active.name,
      source_page: sourcePage,
      source_url: ETC_BASE_URL + sourcePage,
      barycentrics,
      trilinears,
      tripolars,
      additional,
      relations,
      derived_from_trilinear: derivedFromTrilinear,
      search_text: [active.center_id, active.name, sourcePage, ...trilinears, ...barycentrics, ...tripolars].join(' | '),
    };
  }

  // ════════════════════════════════════════════════════════════════════════
  //  HTML PARSER -- two-stage header detection + monotonic-id guard
  //                + relations/formulas extraction
  // ════════════════════════════════════════════════════════════════════════

  function parseEtcHtml(html, sourcePage) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const lines = splitEtcLines(doc.body || doc);
    const result = [];
    let active = null;
    let activeNum = -1;
    let awaitingName = false;

    const finish = () => {
      if (!active) return;
      result.push(buildCenter(active, sourcePage));
      active = null;
      awaitingName = false;
    };

    for (const line of lines) {
      let m = HDR_FULL.exec(line);
      if (m) {
        const n = Number.parseInt(m[1], 10);
        // FIX 1: only treat as a NEW header if n is strictly greater than
        // the currently active center's id (or no active center yet). No
        // fixed numeric ceiling is used (FIX 13) -- ETC grows periodically
        // and a hardcoded maximum would incorrectly reject genuine centers.
        if (active === null || n > activeNum) {
          finish();
          activeNum = n;
          const name = normalizeSpace(m[2]).replace(/^[=:\u2014\-\s]+/, '') || `X(${n})`;
          active = { center_id: `X(${n})`, name, lines: [], relations: [] };
          awaitingName = false;
          continue;
        }
        // FIX 12: self-referential (same id as active) -- capture as a
        // relation/formula, then fall through to also keep it in the
        // general content buffer (unchanged behaviour for coordinate scans).
        if (active && n === activeNum) {
          const desc = normalizeSpace(m[2]).replace(/^[=:\u2014\-\s]+/, '');
          if (desc) active.relations.push(desc);
        }
      } else {
        m = HDR_PARTIAL.exec(line);
        if (m) {
          const n = Number.parseInt(m[1], 10);
          if (active === null || n > activeNum) {
            finish();
            activeNum = n;
            active = { center_id: `X(${n})`, name: `X(${n})`, lines: [], relations: [] };
            awaitingName = true;
            continue;
          }
        }
      }

      if (!active) continue;

      if (awaitingName) {
        if (line.length > 0 && !COORD_LABEL_LINE_RE.test(line)) {
          active.name = normalizeSpace(line).replace(/^[=:\u2014\-\s]+/, '') || active.name;
          awaitingName = false;
          continue;
        }
      }

      active.lines.push(line);
    }
    finish();
    return result;
  }

  // ── Normalise + deduplicate (id-only; center_id is the true unique key) ──
  function normalizeCenter(center) {
    const centerId = center.center_id || '';
    const name = center.name || '';
    if (!centerId || !name) return null;

    const barycentrics = center.barycentrics || (center.additional && center.additional.barycentrics) || [];
    const trilinears   = center.trilinears   || (center.additional && center.additional.trilinears)   || [];
    const tripolars    = center.tripolars    || (center.additional && center.additional.tripolars)    || [];
    const relations    = center.relations    || [];
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
      relations,
      derived_from_trilinear: !!center.derived_from_trilinear,
      search_text: center.search_text || [centerId, name, sourcePage, ...trilinears, ...barycentrics, ...tripolars].join(' | '),
    };
  }

  // FIX 13: no fixed maximum id/count is enforced here by design.
  function dedupeCenters(centers) {
    const byId = new Set();
    const rows = [];
    centers
      .map(normalizeCenter)
      .filter(c => c !== null)
      .sort((a, b) => numericId(a.center_id) - numericId(b.center_id))
      .forEach(center => {
        if (byId.has(center.center_id)) return;
        byId.add(center.center_id);
        rows.push(center);
      });
    return rows;
  }

  // ── Network helpers ──────────────────────────────────────────────────────
  function proxiedEtcUrl(page) {
    return `https://api.allorigins.win/raw?url=${encodeURIComponent(ETC_BASE_URL + page)}`;
  }

  async function fetchEtcPageText(page) {
    const urls = [proxiedEtcUrl(page), ETC_BASE_URL + page];
    const errors = [];
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

  function pageNameForPart(part) {
    return part === 1 ? 'ETC.html' : `ETCPart${part}.html`;
  }

  // FIX 14: empty-page-as-miss heuristic.
  async function fetchLiveEtcCenters(onProgress) {
    const pages = [];
    const centers = [];
    const pageErrors = [];
    let missingInARow = 0;

    for (let part = 1; part <= ETC_MAX_PART; part += 1) {
      const page = pageNameForPart(part);
      let html;
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
      const parsed = parseEtcHtml(html, page);
      pages.push(page);
      centers.push(...parsed);

      // FIX 14: a page can return HTTP 200 while containing no real
      // "X(n) = Name" entries (verified: ETC pre-creates placeholder page
      // files ahead of real content, e.g. Part 42's "will be started in
      // the future" stub). Treat this the same as a missing page for the
      // early-stopping counter.
      if (parsed.length === 0) {
        pageErrors.push(`${page}: fetched successfully but contained no parseable centers (likely a placeholder page)`);
        missingInARow += 1;
        if (missingInARow >= MAX_CONSECUTIVE_MISSING_PAGES) break;
        continue;
      }
      missingInARow = 0;

      if (onProgress) {
        onProgress({
          message: `Parsed ${centers.length.toLocaleString()} centers from ${pages.length} ETC page${pages.length === 1 ? '' : 's'}\u2026`,
          count: centers.length,
          source: 'Live ETC',
        });
      }
      await sleep(INTER_PAGE_DELAY_MS);
    }
    return { centers: dedupeCenters(centers), pages, pageErrors };
  }

  async function loadFallbackCenters(fallbackUrl) {
    if (!fallbackUrl) fallbackUrl = 'data/barycentric_index.json';
    const response = await fetch(fallbackUrl, { cache: 'default' });
    if (!response.ok) throw new Error(`fallback JSON HTTP ${response.status}`);
    const payload = await response.json();
    return dedupeCenters(payload.centers || []);
  }

  async function loadCenters(options) {
    options = options || {};
    try {
      const live = await fetchLiveEtcCenters(options.onProgress);
      if (!live.centers.length) throw new Error('No barycentric centers found in live ETC pages.');
      return Object.assign({}, live, { source: 'Live ETC' });
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
    _internal: {
      normalizeCoordinateExpr,
      normalizeUnicodeSuperscripts,
      cyclicTriple,
      resolveNamedCyclicFunction,
      deriveBarycentricsFromTrilinears,
    },
  };
})();
