const API_BASE = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? ''
    : 'https://duflat-production.up.railway.app';

const els = {
    platform:  document.getElementById('fPlatform'),
    rating:    document.getElementById('fRating'),
    days:      document.getElementById('fDays'),
    country:   document.getElementById('fCountry'),
    search:    document.getElementById('fSearch'),
    refresh:   document.getElementById('btnRefresh'),
    poll:      document.getElementById('btnPoll'),
    list:      document.getElementById('reviewList'),
    loader:    document.getElementById('loader'),
    loaderTxt: document.getElementById('loaderText'),
    status:    document.getElementById('statusMsg'),
    lastPoll:  document.getElementById('lastPoll'),
    statTotal: document.getElementById('statTotal'),
    statApple: document.getElementById('statApple'),
    statGplay: document.getElementById('statGplay'),
    statAvg:   document.getElementById('statAvg'),
    appPill:   document.getElementById('appPill'),
};

let _searchTimer = null;

function showStatus(msg, kind = '') {
    els.status.textContent = msg || '';
    els.status.className = 'cs-status' + (kind ? ' ' + kind : '');
}

function setLoading(flag, text = 'Yukleniyor...') {
    els.loader.hidden = !flag;
    els.loaderTxt.textContent = text;
}

function relativeTime(iso) {
    if (!iso) return '';
    const t = new Date(iso).getTime();
    if (isNaN(t)) return '';
    const diffSec = Math.floor((Date.now() - t) / 1000);
    if (diffSec < 60)   return diffSec + ' sn once';
    if (diffSec < 3600) return Math.floor(diffSec / 60) + ' dk once';
    if (diffSec < 86400) return Math.floor(diffSec / 3600) + ' sa once';
    if (diffSec < 2592000) return Math.floor(diffSec / 86400) + ' gun once';
    return new Date(iso).toISOString().slice(0, 10);
}

function stars(n) {
    n = Math.max(0, Math.min(5, parseInt(n) || 0));
    let s = '';
    for (let i = 0; i < 5; i++) s += i < n ? '★' : '<span class="off">★</span>';
    return s;
}

function escapeHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderReviews(rows) {
    if (!rows || !rows.length) {
        els.list.innerHTML = '<div class="cs-empty">Kriterlere uyan yorum yok.</div>';
        return;
    }
    const html = rows.map(r => {
        const title = r.title ? `<div class="cs-card-title">${escapeHtml(r.title)}</div>` : '';
        return `
        <article class="cs-card">
            <div class="cs-card-head">
                <div class="cs-card-meta">
                    <span class="platform ${r.platform}">${r.platform === 'apple' ? 'Apple' : 'Google Play'}</span>
                    <span class="country">${escapeHtml(r.country || '')}</span>
                    <span class="author">${escapeHtml(r.author || 'anonim')}</span>
                    ${r.app_version ? `<span class="version">v${escapeHtml(r.app_version)}</span>` : ''}
                    <span class="date" title="${escapeHtml(r.review_date || '')}">${relativeTime(r.review_date)}</span>
                </div>
                <div class="cs-stars">${stars(r.rating)}</div>
            </div>
            ${title}
            <div class="cs-card-content">${escapeHtml(r.content || '')}</div>
        </article>`;
    }).join('');
    els.list.innerHTML = html;
}

function renderStats(stats, lastPoll, app) {
    els.statTotal.textContent = stats?.total ?? 0;
    els.statApple.textContent = stats?.by_platform?.apple || 0;
    els.statGplay.textContent = stats?.by_platform?.google_play || 0;
    const byR = stats?.by_rating || {};
    let total = 0, sum = 0;
    for (const [k, v] of Object.entries(byR)) {
        const r = parseInt(k) || 0;
        if (r >= 1 && r <= 5) { total += v; sum += r * v; }
    }
    els.statAvg.textContent = total ? (sum / total).toFixed(2) : '—';

    if (app && app.name) {
        els.appPill.textContent = app.name + ' · ' + (app.android_package || '');
    }

    if (lastPoll) {
        const t = lastPoll.finished_at || lastPoll.started_at;
        els.lastPoll.textContent = 'Son tarama: ' + (t ? relativeTime(t) : '—')
            + (lastPoll.reviews_new != null ? ` · ${lastPoll.reviews_new} yeni` : '');
    } else {
        els.lastPoll.textContent = 'Henuz tarama yapilmadi.';
    }
}

async function load() {
    setLoading(true, 'Yorumlar yukleniyor...');
    showStatus('');
    try {
        const params = new URLSearchParams();
        if (els.platform.value) params.set('platform', els.platform.value);
        if (els.rating.value)   params.set('rating',   els.rating.value);
        if (els.days.value)     params.set('days',     els.days.value);
        if (els.country.value)  params.set('country',  els.country.value.trim().toLowerCase());
        if (els.search.value)   params.set('search',   els.search.value.trim());
        params.set('limit', '200');

        const res = await fetch(API_BASE + '/cs/reviews?' + params.toString());
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        renderReviews(data.reviews || []);
        renderStats(data.stats, data.last_poll, data.app);
    } catch (e) {
        showStatus('Yukleme hatasi: ' + e.message, 'err');
        els.list.innerHTML = '';
    } finally {
        setLoading(false);
    }
}

async function triggerPoll() {
    if (!confirm('Tum ulkelerden yeni yorumlari tara? 1–2 dakika surebilir.')) return;
    els.poll.disabled = true;
    setLoading(true, 'Dunyadaki yorumlar taraniyor...');
    showStatus('Tarama basladi...');
    try {
        const res = await fetch(API_BASE + '/cs/poll', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({}),
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        showStatus(`Tarama bitti · ${data.total_new || 0} yeni yorum · ${data.duration_sec || 0}s`, 'ok');
        await load();
    } catch (e) {
        showStatus('Tarama hatasi: ' + e.message, 'err');
    } finally {
        setLoading(false);
        els.poll.disabled = false;
    }
}

function debouncedReload() {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(load, 300);
}

els.refresh.addEventListener('click', load);
els.poll.addEventListener('click', triggerPoll);
els.platform.addEventListener('change', load);
els.rating.addEventListener('change', load);
els.days.addEventListener('change', load);
els.country.addEventListener('input', debouncedReload);
els.search.addEventListener('input', debouncedReload);

load();
