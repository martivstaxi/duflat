// Health-check modal — fetches /cs/insights for a period window and
// renders a concise narrative (headline + metrics + summary + top issues
// + praise + anomaly). Three tabs: 7d (default) / 30d / year.
//
// Lazy DOM: the overlay is built on first open, reused thereafter.
// Language follows the UI toggle — tabs re-fetch when switched.

import { API } from './constants.js?v=33';
import { T, TC } from './i18n.js?v=33';
import { escapeHtml, relTime } from './utils.js?v=33';

let currentPeriod = '7d';
let modalEl = null;
let bodyEl = null;
let tabEls = {};
let titleEl = null;
let inflight = null;      // token used to ignore stale responses
let lastLoadedLang = null;

export function openInsights() {
    ensureModal();
    refreshStaticLabels();
    modalEl.classList.add('open');
    document.body.classList.add('insights-open');
    loadPeriod(currentPeriod);
}

export function closeInsights() {
    if (!modalEl) return;
    modalEl.classList.remove('open');
    document.body.classList.remove('insights-open');
}

export function setInsightsPeriod(p) {
    if (!['7d', '30d', 'year'].includes(p)) return;
    if (p === currentPeriod && bodyEl && !bodyEl.dataset.needsReload) {
        return;
    }
    currentPeriod = p;
    Object.entries(tabEls).forEach(([k, el]) => el.classList.toggle('active', k === p));
    loadPeriod(p);
}

// Called on every cs:render — cheap no-op unless the UI language actually
// changed while the modal is open (in which case we re-fetch so the
// narrative comes back in the new language). Filter/chip renders are
// ignored because `lastLoadedLang` is unchanged.
export function onLangChange() {
    if (!modalEl) return;
    refreshStaticLabels();
    const lang = currentLang();
    if (modalEl.classList.contains('open') && lastLoadedLang && lang !== lastLoadedLang) {
        loadPeriod(currentPeriod);
    }
}

function ensureModal() {
    if (modalEl) return;
    const overlay = document.createElement('div');
    overlay.className = 'insights-overlay';
    overlay.id = 'insightsOverlay';
    overlay.innerHTML = `
      <div class="insights-panel" role="dialog" aria-modal="true">
        <div class="insights-header">
          <div class="insights-title"></div>
          <button class="insights-close" onclick="closeInsights()" aria-label="close">&times;</button>
        </div>
        <div class="insights-tabs">
          <button class="insights-tab active" data-p="7d" onclick="setInsightsPeriod('7d')"></button>
          <button class="insights-tab" data-p="30d" onclick="setInsightsPeriod('30d')"></button>
          <button class="insights-tab" data-p="year" onclick="setInsightsPeriod('year')"></button>
        </div>
        <div class="insights-body" id="insightsBody"></div>
      </div>
    `;
    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeInsights();
    });
    document.body.appendChild(overlay);
    modalEl = overlay;
    bodyEl = overlay.querySelector('#insightsBody');
    titleEl = overlay.querySelector('.insights-title');
    overlay.querySelectorAll('.insights-tab').forEach(b => {
        tabEls[b.dataset.p] = b;
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && modalEl.classList.contains('open')) closeInsights();
    });
}

function refreshStaticLabels() {
    if (!modalEl) return;
    titleEl.textContent = T('insightsTitle');
    tabEls['7d'].textContent = T('period7d');
    tabEls['30d'].textContent = T('period30d');
    tabEls['year'].textContent = T('periodYear');
}

function currentLang() {
    return document.documentElement.lang.toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

async function loadPeriod(period) {
    const lang = currentLang();
    bodyEl.dataset.needsReload = '';
    bodyEl.innerHTML = `
      <div class="insights-loading">
        <div class="spinner"></div>
        <span>${escapeHtml(T('insightsLoading'))}</span>
      </div>`;
    const token = Symbol();
    inflight = token;
    try {
        const res = await fetch(`${API}/cs/insights?period=${encodeURIComponent(period)}&lang=${lang}`);
        if (inflight !== token) return;
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (inflight !== token) return;
        bodyEl.innerHTML = renderInsights(data);
        lastLoadedLang = lang;
    } catch (e) {
        if (inflight !== token) return;
        bodyEl.dataset.needsReload = '1';
        bodyEl.innerHTML = `<div class="insights-error">${escapeHtml(T('insightsError'))}</div>`;
    }
}

function renderInsights(d) {
    const cur = d.current || {};
    const prior = d.prior || {};
    const nar = d.narrative || {};

    // Polarity: 'higher_better' (rating) → +delta is green, -delta is red.
    // 'lower_better' (1-2★ count) → -delta is green, +delta is red.
    // 'neutral' (total volume) → muted.
    const fmtDelta = (diff, polarity, render) => {
        if (!diff) return '';
        let tone = 'neutral';
        if (polarity === 'higher_better') tone = diff > 0 ? 'good' : 'bad';
        else if (polarity === 'lower_better') tone = diff > 0 ? 'bad' : 'good';
        const sign = diff > 0 ? '+' : '';
        return ` <span class="delta ${tone}">${sign}${render(diff)}</span>`;
    };
    const intDelta = (c, p, polarity = 'neutral') => {
        if (p == null || c == null) return '';
        return fmtDelta(c - p, polarity, v => v);
    };
    const ratingDeltaHtml = (() => {
        if (cur.avg_rating == null || prior.avg_rating == null) return '';
        const diff = +(cur.avg_rating - prior.avg_rating).toFixed(2);
        return fmtDelta(diff, 'higher_better', v => v.toFixed(2));
    })();

    const low = (cur.rating_dist?.['1'] || 0) + (cur.rating_dist?.['2'] || 0);
    const priorLow = (prior.rating_dist?.['1'] || 0) + (prior.rating_dist?.['2'] || 0);

    const headlineHtml = nar.headline
        ? `<div class="insights-headline">${escapeHtml(nar.headline)}</div>`
        : '';

    const metricsHtml = `
      <div class="insights-metrics">
        <div class="metric">
          <div class="metric-label">${escapeHtml(T('metricTotal'))}</div>
          <div class="metric-value">${cur.total || 0}${intDelta(cur.total, prior.total, 'neutral')}</div>
        </div>
        <div class="metric">
          <div class="metric-label">${escapeHtml(T('metricAvg'))}</div>
          <div class="metric-value">${cur.avg_rating == null ? '—' : cur.avg_rating.toFixed(2)}${ratingDeltaHtml}</div>
        </div>
        <div class="metric">
          <div class="metric-label">${escapeHtml(T('metricLow'))}</div>
          <div class="metric-value">${low}${intDelta(low, priorLow, 'lower_better')}</div>
        </div>
      </div>
    `;

    const summaryHtml = nar.summary ? `
      <div class="insights-section">
        <div class="insights-section-label">${escapeHtml(T('summaryLabel'))}</div>
        <div class="insights-section-body">${escapeHtml(nar.summary)}</div>
      </div>` : '';

    let issuesHtml = '';
    if (nar.top_issues && nar.top_issues.length) {
        issuesHtml = `
          <div class="insights-section">
            <div class="insights-section-label">${escapeHtml(T('issuesLabel'))}</div>
            <ul class="insights-list">
              ${nar.top_issues.map(i => `
                <li class="insights-issue sev-${escapeHtml(i.severity || 'medium')}">
                  <div class="issue-theme">${escapeHtml(i.theme || '')}</div>
                  <div class="issue-meta">
                    ${i.count != null ? `<span class="issue-count">${escapeHtml(String(i.count))}</span>` : ''}
                    ${(i.example_countries || []).slice(0,3).map(c =>
                        `<span class="issue-country">${escapeHtml(TC(c))}</span>`
                    ).join('')}
                  </div>
                </li>`).join('')}
            </ul>
          </div>`;
    } else if (low === 0) {
        issuesHtml = `
          <div class="insights-section">
            <div class="insights-section-label">${escapeHtml(T('issuesLabel'))}</div>
            <div class="insights-section-body insights-empty">${escapeHtml(T('noIssues'))}</div>
          </div>`;
    }

    let praiseHtml = '';
    if (nar.top_praise && nar.top_praise.length) {
        praiseHtml = `
          <div class="insights-section">
            <div class="insights-section-label">${escapeHtml(T('praiseLabel'))}</div>
            <ul class="insights-list">
              ${nar.top_praise.map(p => `
                <li class="insights-praise">
                  <span class="praise-theme">${escapeHtml(p.theme || '')}</span>
                  ${p.count != null ? `<span class="praise-count">${escapeHtml(String(p.count))}</span>` : ''}
                </li>`).join('')}
            </ul>
          </div>`;
    }

    const anomalyHtml = nar.anomaly ? `
      <div class="insights-section insights-anomaly">
        <div class="insights-section-label">${escapeHtml(T('anomalyLabel'))}</div>
        <div class="insights-section-body">${escapeHtml(nar.anomaly)}</div>
      </div>` : '';

    const offline = !d.haiku_ok ? `
      <div class="insights-offline">${escapeHtml(T('insightsOffline'))}</div>
    ` : '';

    const generatedHtml = d.generated_at ? `
      <div class="insights-generated">${escapeHtml(T('insightsGenerated', relTime(d.generated_at)))}</div>
    ` : '';

    if ((cur.total || 0) === 0) {
        return `
          <div class="insights-empty-state">${escapeHtml(T('insightsNoData'))}</div>
          ${metricsHtml}
          ${generatedHtml}
        `;
    }

    return headlineHtml + metricsHtml + summaryHtml + issuesHtml + praiseHtml + anomalyHtml + offline + generatedHtml;
}
