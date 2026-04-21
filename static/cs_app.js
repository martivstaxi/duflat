const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? ''
    : 'https://duflat-production.up.railway.app';

if (API) fetch(API + '/ping').catch(() => {});

const CACHE_KEY = 'cs_reviews_cache';
const CACHE_TTL = 5 * 60 * 1000;

let allReviews = [];
let lastPollMeta = null;
let appInfo = null;

let currentRating = 'all';     // 'all' | 1..5
let currentPlatform = 'all';   // 'all' | 'apple' | 'google_play'
let currentCountry = 'all';    // 'all' | 'us' | 'jp' | ...
let currentYear = new Date().getFullYear().toString();
let filterOpen = false;

const els = {
    ratingBtns: document.getElementById('ratingBtns'),
    filterAnchor: document.getElementById('filterDropdownAnchor'),
    activeChips: document.getElementById('activeChips'),
    content: document.getElementById('content'),
    footer: document.getElementById('footerInfo'),
    pollBtn: document.getElementById('btnPoll'),
    subLine: document.getElementById('subLine'),
};

function escapeHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function starStr(n) {
    n = Math.max(0, Math.min(5, parseInt(n) || 0));
    return '★'.repeat(n) + '☆'.repeat(5 - n);
}

function relTime(iso) {
    if (!iso) return '';
    const t = new Date(iso).getTime();
    if (isNaN(t)) return '';
    const d = Math.floor((Date.now() - t) / 1000);
    if (d < 60)     return d + ' sn once';
    if (d < 3600)   return Math.floor(d / 60)   + ' dk once';
    if (d < 86400)  return Math.floor(d / 3600) + ' sa once';
    if (d < 2592000) return Math.floor(d / 86400) + ' gun once';
    return new Date(iso).toISOString().slice(0, 10);
}

function fmtDateLong(d) {
    if (!d || d === 'Unknown') return 'Tarih yok';
    const dt = new Date(d + 'T00:00:00');
    return dt.toLocaleDateString('tr-TR', {
        weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
    });
}

function platformLabel(p) {
    return p === 'apple' ? 'Apple' : (p === 'google_play' ? 'Google Play' : p || '');
}

function applyData(data) {
    const rows = (data.reviews || []).slice();
    rows.sort((a, b) => (b.review_date || '').localeCompare(a.review_date || ''));
    allReviews = rows;
    lastPollMeta = data.last_poll || null;
    appInfo = data.app || null;
    if (appInfo && appInfo.name) {
        els.subLine.textContent = `${appInfo.name} · Apple App Store & Google Play`;
    }
    renderAll();
}

async function loadReviews() {
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
            els.content.innerHTML = `<div class="empty">Yukleme hatasi: ${escapeHtml(e.message)} · <a href="#" onclick="loadReviews();return false">tekrar dene</a></div>`;
        }
    }
}

// ── Filtering ──────────────────────────────
function getFiltered() {
    return allReviews.filter(r => {
        if (currentRating !== 'all' && r.rating !== currentRating) return false;
        if (currentPlatform !== 'all' && r.platform !== currentPlatform) return false;
        if (currentCountry !== 'all' && (r.country || '').toLowerCase() !== currentCountry) return false;
        return true;
    });
}

function getRatingBase() {
    return allReviews.filter(r => {
        if (currentPlatform !== 'all' && r.platform !== currentPlatform) return false;
        if (currentCountry !== 'all' && (r.country || '').toLowerCase() !== currentCountry) return false;
        return true;
    });
}

// ── Renderers ──────────────────────────────
function renderAll() {
    renderRatingBtns();
    renderFilterDropdown();
    renderActiveChips();
    renderReviews();
    renderFooter();
}

function renderRatingBtns() {
    const base = getRatingBase();
    const counts = {1:0, 2:0, 3:0, 4:0, 5:0};
    base.forEach(r => {
        const n = parseInt(r.rating) || 0;
        if (counts[n] !== undefined) counts[n]++;
    });
    const klass = {1:'r-bad', 2:'r-bad', 3:'r-mid', 4:'r-good', 5:'r-good'};

    let html = `<button class="rating-btn ${currentRating==='all'?'active':''}" onclick="setRating('all')">Tumu <span class="count">${base.length}</span></button>`;
    [5, 4, 3, 2, 1].forEach(n => {
        const active = currentRating === n ? 'active' : '';
        html += `<button class="rating-btn ${klass[n]} ${active}" onclick="setRating(${n})">
            <span class="stars">${starStr(n)}</span>
            <span class="count">${counts[n]}</span>
        </button>`;
    });
    html += `<button class="filter-toggle" id="filterToggle" onclick="toggleFilterPanel(event)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="7" y1="12" x2="17" y2="12"/><line x1="10" y1="18" x2="14" y2="18"/></svg>
    </button>`;
    els.ratingBtns.innerHTML = html;
    updateFilterToggle();
}

function updateFilterToggle() {
    const btn = document.getElementById('filterToggle');
    if (!btn) return;
    let count = 0;
    if (currentPlatform !== 'all') count++;
    if (currentCountry !== 'all') count++;
    btn.classList.toggle('has-filter', count > 0);
    const existing = btn.querySelector('.filter-badge');
    if (existing) existing.remove();
    if (count > 0) {
        const badge = document.createElement('span');
        badge.className = 'filter-badge';
        badge.textContent = count;
        btn.appendChild(badge);
    }
}

function renderFilterDropdown() {
    const apple = allReviews.filter(r => r.platform === 'apple').length;
    const gplay = allReviews.filter(r => r.platform === 'google_play').length;

    const countryCounts = {};
    allReviews.forEach(r => {
        const c = (r.country || '').toLowerCase();
        if (!c) return;
        countryCounts[c] = (countryCounts[c] || 0) + 1;
    });
    const countryKeys = Object.keys(countryCounts).sort((a, b) => countryCounts[b] - countryCounts[a]);

    let html = `<div class="filter-section">

        <div class="filter-section-title">Platform</div>
        <div class="filter-options">
            <button class="filter-option ${currentPlatform==='all'?'active':''}" onclick="setPlatform('all')">Tumu<span class="opt-count">${allReviews.length}</span></button>
            <button class="filter-option ${currentPlatform==='apple'?'active':''}" onclick="setPlatform('apple')">Apple<span class="opt-count">${apple}</span></button>
            <button class="filter-option ${currentPlatform==='google_play'?'active':''}" onclick="setPlatform('google_play')">Google Play<span class="opt-count">${gplay}</span></button>
        </div>
    </div>`;

    html += `<div class="filter-section">
        <div class="filter-section-title">Ulke</div>
        <div class="filter-options">
            <button class="filter-option ${currentCountry==='all'?'active':''}" onclick="setCountry('all')">Tum ulkeler<span class="opt-count">${allReviews.length}</span></button>`;
    countryKeys.forEach(c => {
        html += `<button class="filter-option ${currentCountry===c?'active':''}" onclick="setCountry('${escapeHtml(c)}')">${escapeHtml(c.toUpperCase())}<span class="opt-count">${countryCounts[c]}</span></button>`;
    });
    html += `</div></div>`;

    let dropdown = els.filterAnchor.querySelector('.filter-dropdown');
    if (!dropdown) {
        els.filterAnchor.innerHTML = '<div class="filter-dropdown"></div>';
        dropdown = els.filterAnchor.querySelector('.filter-dropdown');
    }
    dropdown.innerHTML = html;
    if (filterOpen) els.filterAnchor.classList.add('open');
}

function renderActiveChips() {
    let html = '';
    if (currentRating !== 'all') {
        html += `<span class="chip">${starStr(currentRating)}<button class="chip-remove" onclick="setRating('all')">&times;</button></span>`;
    }
    if (currentPlatform !== 'all') {
        html += `<span class="chip">${platformLabel(currentPlatform)}<button class="chip-remove" onclick="setPlatform('all')">&times;</button></span>`;
    }
    if (currentCountry !== 'all') {
        html += `<span class="chip">${escapeHtml(currentCountry.toUpperCase())}<button class="chip-remove" onclick="setCountry('all')">&times;</button></span>`;
    }
    els.activeChips.innerHTML = html;
}

function renderReviews() {
    const filtered = getFiltered();
    if (!filtered.length) {
        els.content.innerHTML = `<div class="empty">Kriterlere uyan yorum yok.</div>`;
        return;
    }

    const grouped = {};
    filtered.forEach(r => {
        const d = (r.review_date || '').slice(0, 10) || 'Unknown';
        if (!grouped[d]) grouped[d] = [];
        grouped[d].push(r);
    });
    const dates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

    let html = '<div class="reviews">';
    dates.forEach(d => {
        html += `<div class="date-divider"><span class="line"></span><span class="label">${escapeHtml(fmtDateLong(d))}</span><span class="line"></span></div>`;
        grouped[d].forEach(r => { html += renderCard(r); });
    });
    html += '</div>';
    els.content.innerHTML = html;
}

function renderCard(r) {
    const rating = Math.max(1, Math.min(5, parseInt(r.rating) || 1));
    const marker = `<div class="rating-marker r${rating}" title="${rating} yildiz">${rating}</div>`;
    const title = r.title ? `<div class="card-title">${escapeHtml(r.title)}</div>` : '';
    const author = r.author ? `<span class="author">${escapeHtml(r.author)}</span>` : '';
    const version = r.app_version ? `<span class="version">v${escapeHtml(r.app_version)}</span>` : '';
    const platform = r.platform || '';
    return `<div class="review-card">
        ${marker}
        <div class="card-top">
            <span class="platform-badge ${platform}">${escapeHtml(platformLabel(platform))}</span>
            <span class="country-tag">${escapeHtml((r.country || '').toUpperCase())}</span>
            ${author}
            ${version ? `<span class="dot">·</span>${version}` : ''}
            <span class="date" title="${escapeHtml(r.review_date || '')}">${escapeHtml(relTime(r.review_date))}</span>
        </div>
        ${title}
        <div class="card-content">${escapeHtml(r.content || '')}</div>
    </div>`;
}

function renderFooter() {
    if (!lastPollMeta) {
        els.footer.textContent = 'Henuz tarama yapilmadi.';
        return;
    }
    const t = lastPollMeta.finished_at || lastPollMeta.started_at;
    const parts = ['Son tarama: ' + (t ? relTime(t) : '—')];
    if (lastPollMeta.reviews_new != null) parts.push(`${lastPollMeta.reviews_new} yeni yorum`);
    if (lastPollMeta.countries_scanned != null) {
        const skip = lastPollMeta.countries_skipped ? ` (${lastPollMeta.countries_skipped} pas)` : '';
        parts.push(`${lastPollMeta.countries_scanned} ulke${skip}`);
    }
    if (lastPollMeta.full_scan) parts.push('tam tarama');
    els.footer.textContent = parts.join(' · ');
}

// ── State setters ──────────────────────────
function setRating(v) {
    currentRating = v === 'all' ? 'all' : parseInt(v);
    renderAll();
}
function setPlatform(v) {
    currentPlatform = v;
    filterOpen = false;
    els.filterAnchor.classList.remove('open');
    renderAll();
}
function setCountry(v) {
    currentCountry = v;
    filterOpen = false;
    els.filterAnchor.classList.remove('open');
    renderAll();
}
function toggleFilterPanel(e) {
    if (e) e.stopPropagation();
    filterOpen = !filterOpen;
    els.filterAnchor.classList.toggle('open', filterOpen);
}

document.addEventListener('click', e => {
    if (!filterOpen) return;
    const toggle = document.getElementById('filterToggle');
    if (els.filterAnchor.contains(e.target) || (toggle && toggle.contains(e.target))) return;
    filterOpen = false;
    els.filterAnchor.classList.remove('open');
});

// ── Poll ───────────────────────────────────
async function triggerPoll() {
    if (!confirm('Tum ulkelerden yeni yorumlari tara? 1-2 dakika surebilir.')) return;
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
        const parts = [`${data.total_new || 0} yeni yorum`];
        if (data.countries_scanned != null) {
            const skip = data.countries_skipped ? ` (${data.countries_skipped} pas)` : '';
            parts.push(`${data.countries_scanned} ulke${skip}`);
        }
        if (data.full_scan) parts.push('tam tarama');
        parts.push(`${data.duration_sec || 0}s`);
        els.footer.textContent = 'Tarama bitti · ' + parts.join(' · ');
        // Invalidate cache so the fresh data is shown
        try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
        await loadReviews();
    } catch (e) {
        els.footer.textContent = 'Tarama hatasi: ' + e.message;
    } finally {
        els.pollBtn.disabled = false;
        els.pollBtn.classList.remove('is-loading');
    }
}

els.pollBtn.addEventListener('click', triggerPoll);

loadReviews();
