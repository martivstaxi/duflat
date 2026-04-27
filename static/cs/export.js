// CSV export modal — pick a window (7d / 30d / all) and download the
// currently loaded reviews as CSV. Uses `allReviews` from state (already
// year-scoped by the backend), so no extra fetch is needed. Output language
// follows the UI toggle: zh → Chinese title/body + Chinese headers + Chinese
// country names; en → English equivalents.

import { T, TC, TL, uiLang } from './i18n.js?v=37';
import { allReviews } from './state.js?v=37';

let currentPeriod = '7d';
let modalEl = null;
let tabEls = {};
let titleEl = null;
let downloadBtn = null;
let summaryEl = null;

export function openExport() {
    ensureModal();
    refreshLabels();
    updateSummary();
    modalEl.classList.add('open');
    document.body.classList.add('export-open');
}

export function closeExport() {
    if (!modalEl) return;
    modalEl.classList.remove('open');
    document.body.classList.remove('export-open');
}

export function setExportPeriod(p) {
    if (!['7d', '30d', 'all'].includes(p)) return;
    currentPeriod = p;
    Object.entries(tabEls).forEach(([k, el]) => el.classList.toggle('active', k === p));
    updateSummary();
}

// Called from app.js renderAll — keep tooltip + open-modal labels in sync.
export function onLangChange() {
    if (!modalEl) return;
    refreshLabels();
    updateSummary();
}

export function triggerExportDownload() {
    const rows = filterRows(currentPeriod);
    if (!rows.length) return;
    const csv = buildCsv(rows);
    const filename = buildFilename(currentPeriod);
    downloadBlob(csv, filename);
    closeExport();
}

function ensureModal() {
    if (modalEl) return;
    const overlay = document.createElement('div');
    overlay.className = 'export-overlay';
    overlay.id = 'exportOverlay';
    overlay.innerHTML = `
      <div class="export-panel" role="dialog" aria-modal="true">
        <div class="export-header">
          <div class="export-title"></div>
          <button class="export-close" onclick="closeExport()" aria-label="close">&times;</button>
        </div>
        <div class="export-tabs">
          <button class="export-tab active" data-p="7d" onclick="setExportPeriod('7d')"></button>
          <button class="export-tab" data-p="30d" onclick="setExportPeriod('30d')"></button>
          <button class="export-tab" data-p="all" onclick="setExportPeriod('all')"></button>
        </div>
        <div class="export-summary"></div>
        <button class="export-download-btn" onclick="triggerExportDownload()"></button>
      </div>
    `;
    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeExport();
    });
    document.body.appendChild(overlay);
    modalEl = overlay;
    titleEl = overlay.querySelector('.export-title');
    summaryEl = overlay.querySelector('.export-summary');
    downloadBtn = overlay.querySelector('.export-download-btn');
    overlay.querySelectorAll('.export-tab').forEach(b => {
        tabEls[b.dataset.p] = b;
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && modalEl.classList.contains('open')) closeExport();
    });
}

function refreshLabels() {
    if (!modalEl) return;
    titleEl.textContent = T('exportTitle');
    tabEls['7d'].textContent = T('exportPeriod7d');
    tabEls['30d'].textContent = T('exportPeriod30d');
    tabEls['all'].textContent = T('exportPeriodAll');
    downloadBtn.textContent = T('exportDownload');
    const fab = document.getElementById('exportFab');
    if (fab) {
        const tip = T('exportTooltip');
        fab.setAttribute('aria-label', tip);
        fab.setAttribute('title', tip);
    }
}

function updateSummary() {
    if (!summaryEl) return;
    const n = filterRows(currentPeriod).length;
    summaryEl.textContent = T('exportSummary', n);
    downloadBtn.disabled = n === 0;
}

function filterRows(period) {
    if (period === 'all') return allReviews.slice();
    const days = period === '30d' ? 30 : 7;
    const cutoff = Date.now() - days * 24 * 3600 * 1000;
    return allReviews.filter(r => {
        const t = new Date(r.review_date || 0).getTime();
        return !isNaN(t) && t >= cutoff;
    });
}

function pickTitle(r) {
    if (uiLang === 'zh') return r.title_chinese || r.title_english || r.title || '';
    return r.title_english || r.title || '';
}

function pickContent(r) {
    if (uiLang === 'zh') return r.content_chinese || r.content_english || r.content || '';
    return r.content_english || r.content || '';
}

function platformLabel(p) {
    if (p === 'apple') return uiLang === 'zh' ? '苹果' : 'Apple';
    if (p === 'google_play') return 'Google Play';
    return p || '';
}

function isoDate(s) {
    if (!s) return '';
    return String(s).slice(0, 10);
}

function csvCell(v) {
    if (v == null) return '';
    // Collapse line breaks so each review reads as one row in Sheets/Excel.
    // Multi-paragraph reviews otherwise render as multiline cells, which the
    // user finds awkward to scan side-by-side with single-line ones.
    let s = String(v).replace(/[\r\n]+/g, ' ').replace(/[ \t]{2,}/g, ' ').trim();
    // Excel/Numbers treat leading =,+,-,@ as formulas — neutralize.
    if (/^[=+\-@]/.test(s)) s = "'" + s;
    if (/[",]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
}

function buildCsv(rows) {
    // Country sits between Rating and Version on purpose — both Rating and
    // Version are numeric, so Country (text) separates them visually.
    const headers = [
        T('csvDate'), T('csvPlatform'), T('csvRating'), T('csvCountry'),
        T('csvVersion'), T('csvUsername'), T('csvLanguage'),
        T('csvTitle'), T('csvContent'), T('csvOriginal'),
    ];
    const lines = [headers.map(csvCell).join(',')];
    for (const r of rows) {
        const cells = [
            isoDate(r.review_date),
            platformLabel(r.platform),
            r.rating == null ? '' : String(r.rating),
            TC(r.country) || (r.country || '').toUpperCase(),
            r.app_version || '',
            r.author || '',
            TL(r.language) || '',
            pickTitle(r),
            pickContent(r),
            r.content || '',
        ];
        lines.push(cells.map(csvCell).join(','));
    }
    // CRLF line endings + UTF-8 BOM so Excel detects the encoding correctly.
    return '﻿' + lines.join('\r\n');
}

function buildFilename(period) {
    const today = new Date().toISOString().slice(0, 10);
    return `bilibili-comments-${period}-${uiLang}-${today}.csv`;
}

function downloadBlob(text, filename) {
    const blob = new Blob([text], {type: 'text/csv;charset=utf-8;'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
