const API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? '' : 'https://duflat-production.up.railway.app';

// Warm up Railway immediately — fire-and-forget, no await
if (API) fetch(API + '/ping').catch(() => {});

let allMentions = [];
let allDates = [];
let currentFilter = 'all';
let currentLang = 'all';
let currentDateFilter = null;
let filterOpen = false;
let archivePage = 0;
const DATES_PER_PAGE = 4;
let filterMonth = null; // null = collapsed, 0-11 = show day picker for that month
let showMonths = false; // whether month list is expanded

const CACHE_KEY = 'social_mentions_cache';
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

function _applyData(data) {
    const today = new Date().toISOString().slice(0, 10);
    const mentions = (data.mentions || []).filter(m => !m.content_date || m.content_date <= today);
    mentions.sort((a, b) => (b.content_date || '').localeCompare(a.content_date || ''));
    allMentions = mentions;
    const raw = (data.available_dates || []).filter(d => d <= today);
    allDates = raw.sort((a, b) => b.localeCompare(a));
    renderAll();
}

async function loadMentions() {
    // Show cached data instantly if available
    try {
        const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null');
        if (cached && cached.data && (Date.now() - cached.ts) < CACHE_TTL) {
            _applyData(cached.data);
        } else if (cached && cached.data) {
            // Stale cache — show it while fetching fresh
            _applyData(cached.data);
        } else {
            document.getElementById('content').innerHTML = '<div class="loading"><div class="spinner"></div>Loading mentions...</div>';
        }
    } catch (e) {
        document.getElementById('content').innerHTML = '<div class="loading"><div class="spinner"></div>Loading mentions...</div>';
    }

    // Fetch fresh data in background
    try {
        const resp = await fetch(`${API}/social/mentions?days=365`);
        const data = await resp.json();
        localStorage.setItem(CACHE_KEY, JSON.stringify({ ts: Date.now(), data }));
        _applyData(data);
    } catch (e) {
        if (!allMentions.length) {
            document.getElementById('content').innerHTML = `<div class="empty">Failed to load. <a href="#" onclick="loadMentions();return false">Retry</a></div>`;
        }
    }
}

function renderAll() {
    renderSentimentBtns();
    renderFilterDropdown();
    renderActiveChips();
    renderMentions();
    renderArchive();
    updateFilterToggle();
}

function renderSentimentBtns() {
    const base = currentDateFilter ? allMentions.filter(m => m.content_date === currentDateFilter) : allMentions;
    const filtered = currentLang !== 'all' ? base.filter(m => (m.language || 'Unknown') === currentLang) : base;
    const pos = filtered.filter(m => m.sentiment === 'positive').length;
    const neg = filtered.filter(m => m.sentiment === 'negative').length;
    const neu = filtered.filter(m => m.sentiment === 'neutral').length;

    document.getElementById('sentimentBtns').innerHTML =
        `<button class="sent-btn all-btn ${currentFilter==='all'?'active':''}" onclick="setFilter('all')">All <span class="count">${filtered.length}</span></button>` +
        `<button class="sent-btn pos ${currentFilter==='positive'?'active':''}" onclick="setFilter('positive')">
            <span class="dot" style="background:var(--positive)"></span>Positive <span class="count">${pos}</span>
        </button>` +
        `<button class="sent-btn neg ${currentFilter==='negative'?'active':''}" onclick="setFilter('negative')">
            <span class="dot" style="background:var(--negative)"></span>Negative <span class="count">${neg}</span>
        </button>` +
        `<button class="sent-btn neu ${currentFilter==='neutral'?'active':''}" onclick="setFilter('neutral')">
            <span class="dot" style="background:var(--neutral)"></span>Neutral <span class="count">${neu}</span>
        </button>` +
        `<button class="filter-toggle" id="filterToggle" onclick="toggleFilterPanel(event)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="7" y1="12" x2="17" y2="12"/><line x1="10" y1="18" x2="14" y2="18"/></svg>
        </button>`;
}

function toggleFilterPanel(e) {
    if (e) e.stopPropagation();
    filterOpen = !filterOpen;
    const anchor = document.getElementById('filterDropdownAnchor');
    anchor.classList.toggle('open', filterOpen);
}

document.addEventListener('click', function(e) {
    if (!filterOpen) return;
    const anchor = document.getElementById('filterDropdownAnchor');
    const toggle = document.getElementById('filterToggle');
    if (anchor.contains(e.target) || (toggle && toggle.contains(e.target))) return;
    filterOpen = false;
    anchor.classList.remove('open');
});

function updateFilterToggle() {
    const btn = document.getElementById('filterToggle');
    const count = (currentLang !== 'all' ? 1 : 0) + (currentDateFilter ? 1 : 0);
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
    const base = currentDateFilter ? allMentions.filter(m => m.content_date === currentDateFilter) : allMentions;

    // Languages
    const langs = {};
    base.forEach(m => {
        const lang = m.language || 'Unknown';
        langs[lang] = (langs[lang] || 0) + 1;
    });
    const langKeys = Object.keys(langs).sort();

    let html = `<div class="filter-section">
        <div class="filter-section-title">Language</div>
        <div class="filter-options">
            <button class="filter-option ${currentLang==='all'?'active':''}" onclick="setLang('all')">All<span class="opt-count">${base.length}</span></button>`;
    langKeys.forEach(lang => {
        html += `<button class="filter-option ${currentLang===lang?'active':''}" onclick="setLang('${escapeHtml(lang)}')">${escapeHtml(lang)}<span class="opt-count">${langs[lang]}</span></button>`;
    });
    html += `</div></div>`;

    // Date section — 3 levels: 2026 → Month picker → Day list
    const dateSet = new Set(allDates);
    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];

    html += `<div class="filter-section">
        <div class="filter-section-title">Date</div>
        <div class="filter-options">
            <button class="filter-option ${!currentDateFilter && filterMonth===null?'active':''}" onclick="filterSelectYear()">2026<span class="opt-count">${allMentions.length}</span></button>`;

    // "Month" toggle button
    html += `<button class="filter-option${showMonths && filterMonth===null?' active':''}" onclick="toggleMonths(event)" style="padding-left:20px">Month</button>`;

    if (showMonths && filterMonth === null) {
        // Month list — 12 months, disable months with no content
        const monthCounts = {};
        allMentions.forEach(m => {
            if (!m.content_date) return;
            const mo = parseInt(m.content_date.slice(5, 7), 10) - 1;
            monthCounts[mo] = (monthCounts[mo] || 0) + 1;
        });
        const currentMonth = new Date().getMonth(); // 0-11
        for (let mo = 0; mo < 12; mo++) {
            const isFuture = mo > currentMonth;
            const cls = isFuture ? 'filter-option disabled' : 'filter-option';
            html += `<button class="${cls}" onclick="filterSelectMonth(event,${mo})" style="padding-left:36px">${monthNames[mo]}</button>`;
        }
    } else if (filterMonth !== null) {
        // Calendar for selected month
        const mo = filterMonth;
        const daysInMonth = new Date(2026, mo + 1, 0).getDate();
        const firstDay = new Date(2026, mo, 1).getDay(); // 0=Sun
        html += `</div>
        <div class="cal-header">
            <button onclick="filterCalPrev(event)">&#8249;</button>
            <span class="cal-title">${monthNames[mo]} 2026</span>
            <button onclick="filterCalNext(event)">&#8250;</button>
        </div>
        <div class="cal-grid">`;
        ['S','M','T','W','T','F','S'].forEach(d => { html += `<div class="cal-day-name">${d}</div>`; });
        for (let i = 0; i < firstDay; i++) html += `<div></div>`;
        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `2026-${String(mo + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
            const hasContent = dateSet.has(dateStr);
            const isActive = currentDateFilter === dateStr;
            let cls = 'cal-day';
            if (!hasContent) cls += ' disabled';
            else cls += ' has-content';
            if (isActive) cls += ' active';
            html += `<button class="${cls}" onclick="filterPickDate('${dateStr}')">${d}</button>`;
        }
        html += `</div>`;
    }
    html += `</div>`;

    const anchor = document.getElementById('filterDropdownAnchor');
    let dropdown = anchor.querySelector('.filter-dropdown');
    if (!dropdown) {
        anchor.innerHTML = '<div class="filter-dropdown"></div>';
        dropdown = anchor.querySelector('.filter-dropdown');
    }
    dropdown.innerHTML = html;
    if (filterOpen) anchor.classList.add('open');
}

function renderActiveChips() {
    let html = '';
    if (currentLang !== 'all') {
        html += `<span class="chip">${escapeHtml(currentLang)}<button class="chip-remove" onclick="setLang('all')">&times;</button></span>`;
    }
    if (currentDateFilter) {
        const dt = new Date(currentDateFilter + 'T00:00:00');
        const label = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        html += `<span class="chip">${label}<button class="chip-remove" onclick="selectDate(null)">&times;</button></span>`;
    }
    document.getElementById('activeChips').innerHTML = html;
}

function getFilteredMentions() {
    let list = allMentions;
    if (currentDateFilter) list = list.filter(m => m.content_date === currentDateFilter);
    if (currentFilter !== 'all') list = list.filter(m => m.sentiment === currentFilter);
    if (currentLang !== 'all') list = list.filter(m => (m.language || 'Unknown') === currentLang);
    return list;
}

function renderMentions() {
    const el = document.getElementById('content');
    const filtered = getFilteredMentions();

    if (filtered.length === 0) {
        const hint = currentFilter !== 'all' || currentLang !== 'all'
            ? ' Try clearing filters.' : '';
        el.innerHTML = `<div class="empty">No mentions found.${hint}</div>`;
        return;
    }

    const items = currentDateFilter ? filtered : filtered.slice(0, 10);

    const grouped = {};
    items.forEach(m => {
        const d = m.content_date || 'Unknown';
        if (!grouped[d]) grouped[d] = [];
        grouped[d].push(m);
    });

    let html = '<div class="mentions">';
    const dates = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

    dates.forEach(date => {
        html += `<div class="date-divider"><span class="line"></span><span class="label">${formatDateLong(date)}</span><span class="line"></span></div>`;
        grouped[date].forEach((m, i) => {
            html += renderCard(m, `${date}-${i}`);
        });
    });

    html += '</div>';
    el.innerHTML = html;
}

function renderCard(m, uid) {
    const s = m.sentiment || 'neutral';
    const hasOriginal = m.content_original && m.content_original !== m.content_english;
    const detailsHtml = hasOriginal
        ? `<div class="card-details" id="det-${uid}"><div class="original-label">Original (${escapeHtml(m.language || 'Unknown')})</div>${escapeHtml(m.content_original)}</div>`
        : '';
    const lang = m.language || 'Original';
    const detailsBtn = hasOriginal
        ? `<button class="details-btn" data-lang="${escapeHtml(lang)}" onclick="toggleDetails('det-${uid}',this,'${escapeHtml(lang)}')">${escapeHtml(lang)}</button>`
        : '';

    const tagsHtml = (m.keywords || []).map(k => `<span class="tag">#${escapeHtml(k)}</span>`).join('');

    return `<div class="mention-card ${s}">
        <div class="card-top">
            <span class="sentiment-dot"></span>
            <span class="card-meta"><a href="${escapeHtml(m.url)}" target="_blank" rel="noopener">${escapeHtml(m.platform || '')}</a></span>
            <span style="flex:1"></span>
            ${detailsBtn}
        </div>
        <div class="card-quote">${escapeHtml(m.content_english || m.content_original)}</div>
        ${detailsHtml}
        ${tagsHtml ? `<div class="card-bottom">${tagsHtml}</div>` : ''}
    </div>`;
}

function renderArchive() {
    if (allDates.length === 0) {
        document.getElementById('archiveSection').style.display = 'none';
        return;
    }
    document.getElementById('archiveSection').style.display = '';
    const container = document.getElementById('archiveDates');

    const totalPages = Math.ceil(allDates.length / DATES_PER_PAGE);
    const start = archivePage * DATES_PER_PAGE;
    const end = Math.min(start + DATES_PER_PAGE, allDates.length);
    const pageDates = allDates.slice(start, end);
    const hasPrev = archivePage > 0;
    const hasNext = end < allDates.length;

    const prevSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`;
    const nextSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>`;

    let html = '';

    // Prev button
    html += `<button class="archive-nav ${hasPrev ? '' : 'disabled'}" onclick="archivePrev()" title="Newer">${prevSvg}</button>`;

    // "All" button — always visible
    html += `<button class="archive-date-btn ${!currentDateFilter?'active':''}" onclick="selectDate(null)">
        <span class="day">All</span><span class="month">dates</span>
    </button>`;

    // Date buttons
    pageDates.forEach(d => {
        const dt = new Date(d + 'T00:00:00');
        const day = dt.getDate();
        const month = dt.toLocaleDateString('en-US', { month: 'short' });
        html += `<button class="archive-date-btn ${currentDateFilter===d?'active':''}" onclick="selectDate('${d}')">
            <span class="day">${day}</span><span class="month">${month}</span>
        </button>`;
    });

    // Next button
    html += `<button class="archive-nav ${hasNext ? '' : 'disabled'}" onclick="archiveNext()" title="Older">${nextSvg}</button>`;

    container.innerHTML = html;
}

function archiveNext() {
    const totalPages = Math.ceil(allDates.length / DATES_PER_PAGE);
    if (archivePage < totalPages - 1) {
        const archive = document.getElementById('archiveSection');
        const y = archive.getBoundingClientRect().top;
        archivePage++;
        renderArchive();
        const drift = archive.getBoundingClientRect().top - y;
        if (Math.abs(drift) > 2) window.scrollBy(0, drift);
    }
}

function archivePrev() {
    if (archivePage > 0) {
        const archive = document.getElementById('archiveSection');
        const y = archive.getBoundingClientRect().top;
        archivePage--;
        renderArchive();
        const drift = archive.getBoundingClientRect().top - y;
        if (Math.abs(drift) > 2) window.scrollBy(0, drift);
    }
}

function selectDate(date) {
    const archive = document.getElementById('archiveSection');
    const archiveViewY = archive.getBoundingClientRect().top;

    currentDateFilter = date;
    currentFilter = 'all';
    currentLang = 'all';
    if (!date) { archivePage = 0; filterMonth = null; }
    else { filterMonth = parseInt(date.slice(5, 7), 10) - 1; }
    renderAll();

    const newArchiveY = archive.getBoundingClientRect().top;
    const drift = newArchiveY - archiveViewY;
    if (Math.abs(drift) > 2) {
        window.scrollBy(0, drift);
    }
}

function setFilter(sentiment) {
    currentFilter = sentiment;
    renderAll();
}

function setLang(lang) {
    currentLang = lang;
    filterOpen = false;
    document.getElementById('filterDropdownAnchor').classList.remove('open');
    renderAll();
}

function filterSelectYear() {
    filterMonth = null;
    showMonths = false;
    filterOpen = false;
    document.getElementById('filterDropdownAnchor').classList.remove('open');
    selectDate(null);
}

function toggleMonths(e) {
    if (e) e.stopPropagation();
    showMonths = !showMonths;
    filterMonth = null;
    renderFilterDropdown();
}

function filterSelectMonth(e, mo) {
    if (e) e.stopPropagation();
    filterMonth = mo;
    showMonths = false;
    renderFilterDropdown();
}

function filterBackToMonths() {
    filterMonth = null;
    showMonths = true;
    renderFilterDropdown();
}

function filterCalPrev(e) {
    if (e) e.stopPropagation();
    if (filterMonth > 0) { filterMonth--; renderFilterDropdown(); }
}

function filterCalNext(e) {
    if (e) e.stopPropagation();
    const currentMonth = new Date().getMonth();
    if (filterMonth < currentMonth) { filterMonth++; renderFilterDropdown(); }
}

function filterPickDate(dateStr) {
    filterOpen = false;
    document.getElementById('filterDropdownAnchor').classList.remove('open');
    selectDate(dateStr);
}

function toggleDetails(id, btn, lang) {
    const panel = document.getElementById(id);
    if (!panel) return;
    const isOpen = panel.classList.toggle('open');
    btn.classList.toggle('open', isOpen);
    btn.textContent = isOpen ? 'Close' : lang;
}

function formatDateLong(d) {
    if (!d || d === 'Unknown') return 'Unknown date';
    const dt = new Date(d + 'T00:00:00');
    return dt.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

loadMentions();