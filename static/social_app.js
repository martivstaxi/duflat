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
let currentSensitivity = 'all';
let currentSourceType = 'all';
let showMonths = false; // whether month list is expanded

const CACHE_KEY = 'social_mentions_cache';
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

// ─────────────────────────────────────────────
// I18N — English + Simplified Chinese UI
// Mention content itself (content_english / content_original) is NEVER translated.
// ─────────────────────────────────────────────
const I18N = {
    en: {
        title: 'Social Listening',
        testBuild: 'TEST BUILD',
        loading: 'Loading mentions...',
        failedLoad: 'Failed to load.',
        retry: 'Retry',
        noMentions: 'No mentions found.',
        tryClearing: ' Try clearing filters.',
        browseByDate: 'Browse by date',
        all: 'All',
        positive: 'Positive',
        negative: 'Negative',
        neutral: 'Neutral',
        filterLanguage: 'Language',
        filterPriority: 'Priority',
        filterDate: 'Date',
        filterMonth: 'Month',
        unknownDate: 'Unknown date',
        unknownLang: 'Unknown',
        close: 'Close',
        original: 'Original',
        olderTitle: 'Older',
        newerTitle: 'Newer',
        allDatesTop: 'All',
        allDatesBottom: 'dates',
        months: ['January','February','March','April','May','June','July','August','September','October','November','December'],
        dayShort: ['S','M','T','W','T','F','S'],
        langs: {},
        dateLocale: 'en-US',
    },
    zh: {
        title: '社交聆听',
        testBuild: '测试版',
        loading: '正在加载内容...',
        failedLoad: '加载失败。',
        retry: '重试',
        noMentions: '未找到内容。',
        tryClearing: '请尝试清除筛选条件。',
        browseByDate: '按日期浏览',
        all: '全部',
        positive: '正面',
        negative: '负面',
        neutral: '中性',
        filterLanguage: '语言',
        filterPriority: '优先级',
        filterDate: '日期',
        filterMonth: '月份',
        unknownDate: '未知日期',
        unknownLang: '未知',
        close: '关闭',
        original: '原文',
        olderTitle: '较新',
        newerTitle: '较旧',
        allDatesTop: '全部',
        allDatesBottom: '日期',
        months: ['一月','二月','三月','四月','五月','六月','七月','八月','九月','十月','十一月','十二月'],
        dayShort: ['日','一','二','三','四','五','六'],
        langs: {
            English: '英语', Japanese: '日语', Arabic: '阿拉伯语',
            'Traditional Chinese': '繁体中文', 'Simplified Chinese': '简体中文',
            Chinese: '中文', Turkish: '土耳其语', Russian: '俄语',
            Spanish: '西班牙语', Portuguese: '葡萄牙语', Korean: '韩语',
            French: '法语', German: '德语', Italian: '意大利语',
            Hindi: '印地语', Thai: '泰语', Vietnamese: '越南语',
            Indonesian: '印尼语', Dutch: '荷兰语', Polish: '波兰语',
            Unknown: '未知',
        },
        dateLocale: 'zh-CN',
    },
};

function detectInitialLang() {
    try {
        const saved = localStorage.getItem('ui_lang');
        if (saved === 'zh' || saved === 'en') return saved;
    } catch (e) {}
    const nav = ((navigator.language || navigator.userLanguage || 'en') + '').toLowerCase();
    return nav.startsWith('zh') ? 'zh' : 'en';
}

let uiLang = detectInitialLang();
document.documentElement.lang = (uiLang === 'zh' ? 'zh-CN' : 'en');

function T(k) {
    const v = I18N[uiLang] && I18N[uiLang][k];
    if (v !== undefined) return v;
    return (I18N.en[k] !== undefined ? I18N.en[k] : k);
}

function TL(lang) {
    if (!lang || lang === 'Unknown') return T('unknownLang');
    if (uiLang === 'zh') {
        return I18N.zh.langs[lang] || lang;
    }
    return lang;
}

function setUILang(l) {
    if (l !== 'en' && l !== 'zh') return;
    uiLang = l;
    try { localStorage.setItem('ui_lang', l); } catch (e) {}
    document.documentElement.lang = (l === 'zh' ? 'zh-CN' : 'en');
    document.title = 'Duflat — ' + T('title') + ' TEST';
    // Refresh static header texts too
    const titleEl = document.getElementById('siteTitle');
    if (titleEl) titleEl.textContent = T('title');
    const badgeEl = document.getElementById('testBuildBadge');
    if (badgeEl) badgeEl.textContent = T('testBuild');
    const archTitle = document.getElementById('archiveTitle');
    if (archTitle) archTitle.textContent = T('browseByDate');
    renderLangToggle();
    renderAll();
}

function renderLangToggle() {
    const el = document.getElementById('langToggle');
    if (!el) return;
    el.innerHTML =
        `<button class="lang-btn ${uiLang==='en'?'active':''}" onclick="setUILang('en')">EN</button>` +
        `<button class="lang-btn ${uiLang==='zh'?'active':''}" onclick="setUILang('zh')">中文</button>`;
}

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
            document.getElementById('content').innerHTML = `<div class="loading"><div class="spinner"></div>${escapeHtml(T('loading'))}</div>`;
        }
    } catch (e) {
        document.getElementById('content').innerHTML = `<div class="loading"><div class="spinner"></div>${escapeHtml(T('loading'))}</div>`;
    }

    // Fetch fresh data in background
    try {
        const resp = await fetch(`${API}/social/mentions?days=365`);
        const data = await resp.json();
        localStorage.setItem(CACHE_KEY, JSON.stringify({ ts: Date.now(), data }));
        _applyData(data);
    } catch (e) {
        if (!allMentions.length) {
            document.getElementById('content').innerHTML = `<div class="empty">${escapeHtml(T('failedLoad'))} <a href="#" onclick="loadMentions();return false">${escapeHtml(T('retry'))}</a></div>`;
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
        `<button class="sent-btn all-btn ${currentFilter==='all'?'active':''}" onclick="setFilter('all')">${escapeHtml(T('all'))} <span class="count">${filtered.length}</span></button>` +
        `<button class="sent-btn pos ${currentFilter==='positive'?'active':''}" onclick="setFilter('positive')">
            <span class="dot" style="background:var(--positive)"></span>${escapeHtml(T('positive'))} <span class="count">${pos}</span>
        </button>` +
        `<button class="sent-btn neg ${currentFilter==='negative'?'active':''}" onclick="setFilter('negative')">
            <span class="dot" style="background:var(--negative)"></span>${escapeHtml(T('negative'))} <span class="count">${neg}</span>
        </button>` +
        `<button class="sent-btn neu ${currentFilter==='neutral'?'active':''}" onclick="setFilter('neutral')">
            <span class="dot" style="background:var(--neutral)"></span>${escapeHtml(T('neutral'))} <span class="count">${neu}</span>
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
    const count = (currentLang !== 'all' ? 1 : 0) + (currentDateFilter ? 1 : 0) + (currentSensitivity !== 'all' ? 1 : 0) + (currentSourceType !== 'all' ? 1 : 0);
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
        <div class="filter-section-title">${escapeHtml(T('filterLanguage'))}</div>
        <div class="filter-options">
            <button class="filter-option ${currentLang==='all'?'active':''}" onclick="setLang('all')">${escapeHtml(T('all'))}<span class="opt-count">${base.length}</span></button>`;
    langKeys.forEach(lang => {
        html += `<button class="filter-option ${currentLang===lang?'active':''}" onclick="setLang('${escapeHtml(lang)}')">${escapeHtml(TL(lang))}<span class="opt-count">${langs[lang]}</span></button>`;
    });
    html += `</div></div>`;

    // Priority (P0/P1/P2) — merges critical→P0, high→P1, medium+low→P2
    const priorityCounts = { p0: 0, p1: 0, p2: 0 };
    base.forEach(m => {
        priorityCounts[sensToPriority(m.sensitivity)]++;
    });
    const priOrder = ['p0','p1','p2'];
    const priLabels = {p0:'P0',p1:'P1',p2:'P2'};
    html += `<div class="filter-section">
        <div class="filter-section-title">${escapeHtml(T('filterPriority'))}</div>
        <div class="filter-options">
            <button class="filter-option ${currentSensitivity==='all'?'active':''}" onclick="setSensitivity('all')">${escapeHtml(T('all'))}<span class="opt-count">${base.length}</span></button>`;
    priOrder.forEach(p => {
        if (priorityCounts[p]) {
            html += `<button class="filter-option ${currentSensitivity===p?'active':''}" onclick="setSensitivity('${p}')">${priLabels[p]}<span class="opt-count">${priorityCounts[p]}</span></button>`;
        }
    });
    html += `</div></div>`;

    // Date section — 3 levels: 2026 → Month picker → Day list
    const dateSet = new Set(allDates);
    const monthNames = I18N[uiLang].months;
    const dayShort = I18N[uiLang].dayShort;

    html += `<div class="filter-section">
        <div class="filter-section-title">${escapeHtml(T('filterDate'))}</div>
        <div class="filter-options">
            <button class="filter-option ${!currentDateFilter && filterMonth===null?'active':''}" onclick="filterSelectYear()">2026<span class="opt-count">${allMentions.length}</span></button>`;

    // "Month" toggle button
    html += `<button class="filter-option${showMonths && filterMonth===null?' active':''}" onclick="toggleMonths(event)" style="padding-left:20px">${escapeHtml(T('filterMonth'))}</button>`;

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
            html += `<button class="${cls}" onclick="filterSelectMonth(event,${mo})" style="padding-left:36px">${escapeHtml(monthNames[mo])}</button>`;
        }
    } else if (filterMonth !== null) {
        // Calendar for selected month
        const mo = filterMonth;
        const daysInMonth = new Date(2026, mo + 1, 0).getDate();
        const firstDay = new Date(2026, mo, 1).getDay(); // 0=Sun
        html += `</div>
        <div class="cal-header">
            <button onclick="filterCalPrev(event)">&#8249;</button>
            <span class="cal-title">${escapeHtml(monthNames[mo])} 2026</span>
            <button onclick="filterCalNext(event)">&#8250;</button>
        </div>
        <div class="cal-grid">`;
        dayShort.forEach(d => { html += `<div class="cal-day-name">${escapeHtml(d)}</div>`; });
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
        html += `<span class="chip">${escapeHtml(TL(currentLang))}<button class="chip-remove" onclick="setLang('all')">&times;</button></span>`;
    }
    if (currentDateFilter) {
        const dt = new Date(currentDateFilter + 'T00:00:00');
        const label = dt.toLocaleDateString(I18N[uiLang].dateLocale, { month: 'short', day: 'numeric' });
        html += `<span class="chip">${escapeHtml(label)}<button class="chip-remove" onclick="selectDate(null)">&times;</button></span>`;
    }
    if (currentSensitivity !== 'all') {
        const priLabels = {p0:'P0',p1:'P1',p2:'P2'};
        html += `<span class="chip">${priLabels[currentSensitivity] || currentSensitivity}<button class="chip-remove" onclick="setSensitivity('all')">&times;</button></span>`;
    }
    document.getElementById('activeChips').innerHTML = html;
}

function sensToPriority(s) {
    if (s === 'critical') return 'p0';
    if (s === 'high') return 'p1';
    return 'p2';
}

function getFilteredMentions() {
    let list = allMentions;
    if (currentDateFilter) list = list.filter(m => m.content_date === currentDateFilter);
    if (currentFilter !== 'all') list = list.filter(m => m.sentiment === currentFilter);
    if (currentLang !== 'all') list = list.filter(m => (m.language || 'Unknown') === currentLang);
    if (currentSensitivity !== 'all') list = list.filter(m => sensToPriority(m.sensitivity) === currentSensitivity);
    if (currentSourceType !== 'all') list = list.filter(m => (m.source_type || 'news_minor') === currentSourceType);
    return list;
}

function renderMentions() {
    const el = document.getElementById('content');
    const filtered = getFilteredMentions();

    if (filtered.length === 0) {
        const hint = currentFilter !== 'all' || currentLang !== 'all' ? T('tryClearing') : '';
        el.innerHTML = `<div class="empty">${escapeHtml(T('noMentions'))}${escapeHtml(hint)}</div>`;
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
        html += `<div class="date-divider"><span class="line"></span><span class="label">${escapeHtml(formatDateLong(date))}</span><span class="line"></span></div>`;
        grouped[date].forEach((m, i) => {
            html += renderCard(m, `${date}-${i}`);
        });
    });

    html += '</div>';
    el.innerHTML = html;
}

function renderCard(m, uid) {
    const s = m.sentiment || 'neutral';
    const sensitivity = m.sensitivity || 'low';
    const rawLang = m.language || 'Unknown';
    const langDisplay = TL(rawLang);
    const closeLabel = T('close');

    // Card quote: localized Chinese translation if UI is zh and it exists, else English summary.
    // content_original is never shown here — it lives inside the details panel only.
    const displayQuote = (uiLang === 'zh' && m.content_chinese)
        ? m.content_chinese
        : (m.content_english || m.content_original || '');

    const hasOriginal = m.content_original && m.content_original !== m.content_english;
    const detailsHtml = hasOriginal
        ? `<div class="card-details" id="det-${uid}"><div class="original-label">${escapeHtml(T('original'))} (${escapeHtml(langDisplay)})</div>${escapeHtml(m.content_original)}</div>`
        : '';
    const detailsBtn = hasOriginal
        ? `<button class="details-btn" onclick="toggleDetails('det-${uid}',this,'${escapeHtml(langDisplay)}','${escapeHtml(closeLabel)}')">${escapeHtml(langDisplay)}</button>`
        : '';

    const priorityMap = { critical: 'p0', high: 'p1', medium: 'p2', low: 'p2' };
    const priorityLabels = { critical: 'P0', high: 'P1', medium: 'P2', low: 'P2' };
    const priorityClass = priorityMap[sensitivity] || 'p2';
    const priorityLabel = priorityLabels[sensitivity] || 'P2';
    const priorityMarker = `<div class="priority-marker ${priorityClass}" title="${sensitivity || 'low'}">${priorityLabel}</div>`;

    const tagsHtml = (m.keywords || []).slice(0, 3).map(k => `<span class="tag">#${escapeHtml(k)}</span>`).join('');

    return `<div class="mention-card ${s}">
        ${priorityMarker}
        <div class="card-top">
            <span class="sentiment-dot"></span>
            <span class="card-meta"><a href="${escapeHtml(m.url)}" target="_blank" rel="noopener">${escapeHtml(m.platform || '')}</a></span>
            <span style="flex:1"></span>
            ${detailsBtn}
        </div>
        <div class="card-quote">${escapeHtml(displayQuote)}</div>
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
    const archTitle = document.getElementById('archiveTitle');
    if (archTitle) archTitle.textContent = T('browseByDate');
    const container = document.getElementById('archiveDates');

    const start = archivePage * DATES_PER_PAGE;
    const end = Math.min(start + DATES_PER_PAGE, allDates.length);
    const pageDates = allDates.slice(start, end);
    const hasPrev = archivePage > 0;
    const hasNext = end < allDates.length;

    const prevSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`;
    const nextSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>`;

    let html = '';

    // Prev button (visually left = newer dates)
    html += `<button class="archive-nav ${hasPrev ? '' : 'disabled'}" onclick="archivePrev()" title="${escapeHtml(T('newerTitle'))}">${prevSvg}</button>`;

    // "All" button — always visible
    html += `<button class="archive-date-btn ${!currentDateFilter?'active':''}" onclick="selectDate(null)">
        <span class="day">${escapeHtml(T('allDatesTop'))}</span><span class="month">${escapeHtml(T('allDatesBottom'))}</span>
    </button>`;

    // Date buttons
    pageDates.forEach(d => {
        const dt = new Date(d + 'T00:00:00');
        const day = dt.getDate();
        const month = dt.toLocaleDateString(I18N[uiLang].dateLocale, { month: 'short' });
        html += `<button class="archive-date-btn ${currentDateFilter===d?'active':''}" onclick="selectDate('${d}')">
            <span class="day">${day}</span><span class="month">${escapeHtml(month)}</span>
        </button>`;
    });

    // Next button (visually right = older dates)
    html += `<button class="archive-nav ${hasNext ? '' : 'disabled'}" onclick="archiveNext()" title="${escapeHtml(T('olderTitle'))}">${nextSvg}</button>`;

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

function setSensitivity(val) {
    currentSensitivity = val;
    filterOpen = false;
    document.getElementById('filterDropdownAnchor').classList.remove('open');
    renderAll();
}

function setSourceType(val) {
    currentSourceType = val;
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

function toggleDetails(id, btn, label, closeLabel) {
    const panel = document.getElementById(id);
    if (!panel) return;
    const isOpen = panel.classList.toggle('open');
    btn.classList.toggle('open', isOpen);
    btn.textContent = isOpen ? closeLabel : label;
}

function formatDateLong(d) {
    if (!d || d === 'Unknown') return T('unknownDate');
    const dt = new Date(d + 'T00:00:00');
    return dt.toLocaleDateString(I18N[uiLang].dateLocale, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return (str + '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── Init ───
document.title = 'Duflat — ' + T('title') + ' TEST';
const _titleEl = document.getElementById('siteTitle');
if (_titleEl) _titleEl.textContent = T('title');
const _badgeEl = document.getElementById('testBuildBadge');
if (_badgeEl) _badgeEl.textContent = T('testBuild');
const _loadingTxt = document.getElementById('loadingText');
if (_loadingTxt) _loadingTxt.textContent = T('loading');
const _archTitle = document.getElementById('archiveTitle');
if (_archTitle) _archTitle.textContent = T('browseByDate');

renderLangToggle();
loadMentions();
