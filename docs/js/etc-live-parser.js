"use strict";
(() => {
    const ETC_BASE_URL = 'https://faculty.evansville.edu/ck6/encyclopedia/';
    const ETC_MAX_PART = 150;
    const MAX_CONSECUTIVE_MISSING_PAGES = 3;
    const COORDINATE_LABELS = ['Trilinears', 'Barycentrics', 'Tripolars'];
    function pageNameForPart(part) {
        return part === 1 ? 'ETC.html' : `ETCPart${part}.html`;
    }
    function normalizeSpace(text = '') {
        return (text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
    }
    function stripEtcTail(text) {
        return normalizeSpace(text)
            .replace(/\s+(?:where|for\b|which\b|See\s+also|Lines|Note|Also|Polar|Coordinates|equals?|Compare|The\s).*$/i, '')
            .replace(/[.;,]+$/g, '')
            .trim();
    }
    function escapeHtml(text = '') {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }
    function numericId(centerId) {
        const match = (centerId || '').match(/\d+/);
        return match ? Number.parseInt(match[0], 10) : 0;
    }
    function splitEtcLines(root) {
        const lines = [];
        const buffer = [];
        const flush = () => {
            const line = normalizeSpace(buffer.join(' '));
            if (line)
                lines.push(line);
            buffer.length = 0;
        };
        const visit = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                const text = normalizeSpace(node.nodeValue || '');
                if (text)
                    buffer.push(text);
                return;
            }
            if (node.nodeType !== Node.ELEMENT_NODE)
                return;
            const element = node;
            const tag = element.tagName.toLowerCase();
            if (['script', 'style', 'noscript'].includes(tag))
                return;
            if (['br', 'hr'].includes(tag)) {
                flush();
                return;
            }
            const isBlockBoundary = ['h1', 'h2', 'h3', 'h4', 'p', 'div', 'li', 'tr'].includes(tag);
            if (isBlockBoundary)
                flush();
            Array.from(element.childNodes).forEach(visit);
            if (isBlockBoundary)
                flush();
        };
        Array.from(root.childNodes).forEach(visit);
        flush();
        return lines;
    }
    function extractCoordinateRuns(blockText, label) {
        const results = [];
        const labelAlternation = COORDINATE_LABELS.join('|');
        const pattern = new RegExp(`(?:^|\\s)${label}\\s+([\\s\\S]*?)(?=(?:\\s+(?:${labelAlternation})\\s+)|(?:\\s+X\\(\\d+\\)\\s*=)|$)`, 'gi');
        let match;
        while ((match = pattern.exec(blockText)) !== null) {
            const cleaned = stripEtcTail(match[1]);
            if (cleaned && (label === 'Tripolars' || cleaned.includes(':')) && !results.includes(cleaned)) {
                results.push(cleaned);
            }
        }
        return results;
    }
    function buildCenter(active, sourcePage) {
        const blockText = normalizeSpace(active.lines.join(' '));
        const barycentrics = extractCoordinateRuns(blockText, 'Barycentrics');
        const trilinears = extractCoordinateRuns(blockText, 'Trilinears');
        const tripolars = extractCoordinateRuns(blockText, 'Tripolars');
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
            search_text: [active.center_id, active.name, sourcePage, ...trilinears, ...barycentrics, ...tripolars].join(' | '),
        };
    }
    function parseEtcHtml(html, sourcePage) {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const lines = splitEtcLines(doc.body || doc);
        const centers = [];
        let active = null;
        const finish = () => {
            if (!active)
                return;
            centers.push(buildCenter(active, sourcePage));
            active = null;
        };
        for (const line of lines) {
            const header = line.match(/^X\s*\(\s*(\d+)\s*\)\s*=\s*(.+)$/i);
            if (header) {
                finish();
                const centerId = `X(${Number.parseInt(header[1], 10)})`;
                const name = normalizeSpace(header[2]).replace(/^[=:—\-\s]+/, '') || centerId;
                active = { center_id: centerId, name, lines: [] };
            }
            else if (active) {
                active.lines.push(line);
            }
        }
        finish();
        return centers;
    }
    function normalizeCenter(center) {
        const centerId = center.center_id || '';
        const name = center.name || '';
        const barycentrics = center.barycentrics || center.additional?.barycentrics || [];
        if (!centerId || !name)
            return null;
        const trilinears = center.trilinears || center.additional?.trilinears || [];
        const tripolars = center.tripolars || center.additional?.tripolars || [];
        const sourcePage = center.source_page || '';
        return {
            center_id: centerId,
            name,
            source_page: sourcePage,
            source_url: center.source_url || (sourcePage ? ETC_BASE_URL + sourcePage : ''),
            barycentrics,
            trilinears,
            tripolars,
            additional: { trilinears, barycentrics, tripolars },
            search_text: center.search_text || [centerId, name, sourcePage, ...trilinears, ...barycentrics, ...tripolars].join(' | '),
        };
    }
    function dedupeCenters(centers) {
        const byId = new Set();
        const byName = new Set();
        const rows = [];
        centers
            .map(normalizeCenter)
            .filter((center) => center !== null)
            .sort((a, b) => numericId(a.center_id) - numericId(b.center_id))
            .forEach(center => {
            const nameKey = normalizeSpace(center.name).toLowerCase();
            if (byId.has(center.center_id) || byName.has(nameKey))
                return;
            byId.add(center.center_id);
            byName.add(nameKey);
            rows.push(center);
        });
        return rows;
    }
    function proxiedEtcUrl(page) {
        return `https://api.allorigins.win/raw?url=${encodeURIComponent(ETC_BASE_URL + page)}`;
    }
    async function fetchEtcPageText(page) {
        const urls = [ETC_BASE_URL + page, proxiedEtcUrl(page)];
        const errors = [];
        for (const url of urls) {
            try {
                const response = await fetch(url, { cache: 'no-store' });
                if (response.status === 404)
                    return null;
                if (!response.ok) {
                    errors.push(`${url}: HTTP ${response.status}`);
                    continue;
                }
                return await response.text();
            }
            catch (err) {
                errors.push(err instanceof Error ? err.message : String(err));
            }
        }
        throw new Error(`${page}: ${errors.join('; ')}`);
    }
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
            }
            catch (err) {
                pageErrors.push(err instanceof Error ? err.message : String(err));
                missingInARow += 1;
                if (missingInARow >= MAX_CONSECUTIVE_MISSING_PAGES)
                    break;
                continue;
            }
            if (html === null) {
                missingInARow += 1;
                if (missingInARow >= MAX_CONSECUTIVE_MISSING_PAGES)
                    break;
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
        }
        return { centers: dedupeCenters(centers), pages, pageErrors };
    }
    async function loadFallbackCenters(fallbackUrl = 'data/barycentric_index.json') {
        const response = await fetch(fallbackUrl, { cache: 'no-store' });
        if (!response.ok)
            throw new Error(`fallback JSON HTTP ${response.status}`);
        const payload = (await response.json());
        return dedupeCenters(payload.centers || []);
    }
    async function loadCenters(options = {}) {
        try {
            const live = await fetchLiveEtcCenters(options.onProgress);
            if (!live.centers.length)
                throw new Error('No barycentric centers found in live ETC pages.');
            return { ...live, source: 'Live ETC' };
        }
        catch (err) {
            const warning = err instanceof Error ? err.message : String(err);
            const centers = await loadFallbackCenters(options.fallbackUrl);
            return { centers, pages: [], pageErrors: [], source: 'Fallback', warning };
        }
    }
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
