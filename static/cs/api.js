import { API, AUTO_POLL_THRESHOLD_MS, CACHE_KEY } from './constants.js?v=31';
import { T } from './i18n.js?v=31';
import { escapeHtml } from './utils.js?v=31';
import {
    allReviews, applyData, autoPolling, currentYear, lastPollMeta,
    setAutoPolling,
} from './state.js?v=31';
import { els } from './dom.js?v=31';
import { renderFooter } from './render/footer.js?v=31';

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
    params.set('limit', '5000');

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
