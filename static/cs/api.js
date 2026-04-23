import { API, AUTO_POLL_THRESHOLD_MS, CACHE_KEY } from './constants.js';
import { T } from './i18n.js';
import { escapeHtml } from './utils.js';
import {
    allReviews, appInfo, applyData, autoPolling, currentYear, lastPollMeta,
    setAutoPolling,
} from './state.js';
import { els } from './dom.js';
import { renderFooter } from './render/footer.js';

if (API) fetch(API + '/ping').catch(() => {});

// ── Initial load / refresh ───────────────────
export async function loadReviews(opts = {}) {
    // Warm from cache first for instant paint
    try {
        const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
        if (cached && cached.data && cached.year === currentYear) {
            applyData(cached.data);
        }
    } catch (e) {}

    const params = new URLSearchParams();
    params.set('year', currentYear);
    params.set('limit', '500');

    try {
        const res = await fetch(`${API}/cs/reviews?` + params.toString());
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        try {
            localStorage.setItem(CACHE_KEY, JSON.stringify({
                ts: Date.now(), year: currentYear, data,
            }));
        } catch (e) {}
        applyData(data);
    } catch (e) {
        if (!allReviews.length) {
            els.content.innerHTML = `<div class="empty">${escapeHtml(T('loadError', e.message))} · <a href="#" onclick="loadReviews();return false">${escapeHtml(T('tryAgain'))}</a></div>`;
        }
    }

    if (!opts.skipAutoPoll) maybeAutoPoll();
}

// ── Background auto-poll on page load ────────
// If the last poll is older than AUTO_POLL_THRESHOLD_MS (or already running),
// fire a silent fire-and-forget poll, wait for it to finish, then reload.
export async function maybeAutoPoll() {
    if (autoPolling) return;

    let status = null;
    try {
        const r = await fetch(API + '/cs/poll-status');
        if (r.ok) status = await r.json();
    } catch (e) {}

    if (status && status.active) {
        setAutoPolling(true);
        showAutoPollIndicator();
        await waitForPollDone();
        hideAutoPollIndicator();
        try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
        await loadReviews({skipAutoPoll: true});
        setAutoPolling(false);
        return;
    }

    if (!lastPollMeta) return;
    const t = lastPollMeta.finished_at || lastPollMeta.started_at;
    if (!t) return;
    const age = Date.now() - new Date(t).getTime();
    if (isNaN(age) || age < AUTO_POLL_THRESHOLD_MS) return;

    setAutoPolling(true);
    showAutoPollIndicator();
    try {
        const startRes = await fetch(API + '/cs/poll', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({}),
        });
        if (!startRes.ok) { hideAutoPollIndicator(); setAutoPolling(false); return; }
        await waitForPollDone();
    } finally {
        hideAutoPollIndicator();
    }
    try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
    await loadReviews({skipAutoPoll: true});
    setAutoPolling(false);
}

async function waitForPollDone(maxMs = 180000, intervalMs = 8000) {
    const started = Date.now();
    // First tick is longer so we don't hammer the API instantly
    await new Promise(r => setTimeout(r, 4000));
    while (Date.now() - started < maxMs) {
        try {
            const r = await fetch(API + '/cs/poll-status');
            if (r.ok) {
                const st = await r.json();
                if (!st.active) return;
            }
        } catch (e) {}
        await new Promise(r => setTimeout(r, intervalMs));
    }
}

function showAutoPollIndicator() {
    els.footer.textContent = T('scanning');
}

function hideAutoPollIndicator() {
    renderFooter();
}

// ── Manual poll (FAB button) ─────────────────
export async function triggerPoll() {
    if (!confirm(T('scanConfirm'))) return;
    els.pollBtn.disabled = true;
    els.pollBtn.classList.add('is-loading');
    try {
        const res = await fetch(API + '/cs/poll', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({wait: true}),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const parts = [T('scanNewComments', data.total_new || 0)];
        if (data.countries_scanned != null) {
            parts.push(T('scanCountries', data.countries_scanned, data.countries_skipped || 0));
        }
        if (data.full_scan) parts.push(T('scanFull'));
        parts.push(T('scanSeconds', data.duration_sec || 0));
        els.footer.textContent = T('scanCompletePrefix') + parts.join(' · ');
        try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
        await loadReviews();
    } catch (e) {
        els.footer.textContent = T('scanError', e.message);
    } finally {
        els.pollBtn.disabled = false;
        els.pollBtn.classList.remove('is-loading');
    }
}
