const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? ''
    : 'https://duflat-production.up.railway.app';

if (API) fetch(API + '/ping').catch(() => {});

const CACHE_KEY = 'cs_reviews_cache_v2';
const CACHE_TTL = 5 * 60 * 1000;

const DATES_PER_PAGE = 4;
const DEFAULT_RECENT_DAYS = 5;  // initial view window; user can drill deeper via archive/calendar
const AUTO_POLL_THRESHOLD_MS = 3 * 60 * 60 * 1000;  // page load → bg-tara if last poll > 3h

// ─────────────────────────────────────────────
// I18N — English + Simplified Chinese UI
// Card body/title: uiLang='zh' && content_chinese available → Chinese, else English.
// Original content (in the Details panel) is NEVER translated.
// ─────────────────────────────────────────────
const I18N = {
    en: {
        siteTitle: 'User Comments',
        pageTitle: 'Duflat — User Comments',
        subTemplate: (app) => `${app} · App Store & Play`,
        loading: 'Loading comments...',
        loadError: (msg) => `Load error: ${msg}`,
        tryAgain: 'try again',
        noMatch: 'No comments match the filters.',
        noDate: 'No date',
        all: 'All',
        allCountries: 'All countries',
        platform: 'Platform',
        country: 'Country',
        date: 'Date',
        lastNDays: (n) => `Last ${n} days`,
        selectMonth: 'Select month',
        archiveTitle: 'Browse by date',
        lastN: 'Last',
        days: 'days',
        olderTitle: 'Older',
        newerTitle: 'Newer',
        original: 'Original',
        detailsFallback: 'Details',
        close: 'Close',
        scanNow: 'Scan now',
        scanTooltip: 'Scan for new comments (~1-2 min)',
        scanConfirm: 'Scan all countries for new comments? May take 1-2 minutes.',
        scanning: 'Scanning for fresh comments in background…',
        scanCompletePrefix: 'Scan complete · ',
        scanNewComments: (n) => `${n} new comments`,
        scanCountries: (n, skipped) => `${n} countries${skipped ? ` (${skipped} skipped)` : ''}`,
        scanFull: 'full scan',
        scanSeconds: (s) => `${s}s`,
        scanError: (msg) => `Scan error: ${msg}`,
        months: ['January','February','March','April','May','June','July','August','September','October','November','December'],
        dayShort: ['Su','Mo','Tu','We','Th','Fr','Sa'],
        relTime: (d) => {
            if (d < 60) return d + 's ago';
            if (d < 3600) return Math.floor(d / 60) + 'm ago';
            if (d < 86400) return Math.floor(d / 3600) + 'h ago';
            return Math.floor(d / 86400) + 'd ago';
        },
        dateLocale: 'en-US',
        langs: {},
    },
    zh: {
        siteTitle: '用户评论',
        pageTitle: 'Duflat — 用户评论',
        subTemplate: (app) => `${app} · App Store 与 Google Play`,
        loading: '正在加载评论...',
        loadError: (msg) => `加载失败：${msg}`,
        tryAgain: '重试',
        noMatch: '没有符合筛选条件的评论。',
        noDate: '无日期',
        all: '全部',
        allCountries: '全部国家',
        platform: '平台',
        country: '国家',
        date: '日期',
        lastNDays: (n) => `最近 ${n} 天`,
        selectMonth: '选择月份',
        archiveTitle: '按日期浏览',
        lastN: '最近',
        days: '天',
        olderTitle: '较旧',
        newerTitle: '较新',
        original: '原文',
        detailsFallback: '详情',
        close: '关闭',
        scanNow: '立即扫描',
        scanTooltip: '扫描新评论（约 1-2 分钟）',
        scanConfirm: '扫描所有国家的新评论？可能需要 1-2 分钟。',
        scanning: '正在后台扫描最新评论…',
        scanCompletePrefix: '扫描完成 · ',
        scanNewComments: (n) => `${n} 条新评论`,
        scanCountries: (n, skipped) => `${n} 个国家${skipped ? `（跳过 ${skipped}）` : ''}`,
        scanFull: '完整扫描',
        scanSeconds: (s) => `${s}秒`,
        scanError: (msg) => `扫描失败：${msg}`,
        months: ['一月','二月','三月','四月','五月','六月','七月','八月','九月','十月','十一月','十二月'],
        dayShort: ['日','一','二','三','四','五','六'],
        relTime: (d) => {
            if (d < 60) return d + ' 秒前';
            if (d < 3600) return Math.floor(d / 60) + ' 分钟前';
            if (d < 86400) return Math.floor(d / 3600) + ' 小时前';
            return Math.floor(d / 86400) + ' 天前';
        },
        dateLocale: 'zh-CN',
        langs: {
            English: '英语', Spanish: '西班牙语', Portuguese: '葡萄牙语',
            French: '法语', German: '德语', Italian: '意大利语',
            Dutch: '荷兰语', Polish: '波兰语', Czech: '捷克语',
            Slovak: '斯洛伐克语', Hungarian: '匈牙利语', Romanian: '罗马尼亚语',
            Greek: '希腊语', Swedish: '瑞典语', Norwegian: '挪威语',
            Danish: '丹麦语', Finnish: '芬兰语',
            Japanese: '日语', Korean: '韩语',
            'Traditional Chinese': '繁体中文', 'Simplified Chinese': '简体中文',
            Chinese: '中文',
            Arabic: '阿拉伯语', Turkish: '土耳其语', Russian: '俄语',
            Ukrainian: '乌克兰语', Hebrew: '希伯来语',
            Indonesian: '印尼语', Malay: '马来语', Thai: '泰语',
            Vietnamese: '越南语', Hindi: '印地语', Bengali: '孟加拉语',
            Tagalog: '他加禄语', Other: '其他', Unknown: '未知',
        },
    },
};

function detectInitialLang() {
    try {
        const saved = localStorage.getItem('cs_ui_lang');
        if (saved === 'zh' || saved === 'en') return saved;
    } catch (e) {}
    const nav = ((navigator.language || navigator.userLanguage || 'en') + '').toLowerCase();
    return nav.startsWith('zh') ? 'zh' : 'en';
}

let uiLang = detectInitialLang();
document.documentElement.lang = (uiLang === 'zh' ? 'zh-CN' : 'en');

function T(k, ...args) {
    const src = I18N[uiLang] && I18N[uiLang][k] !== undefined ? I18N[uiLang][k] : I18N.en[k];
    if (typeof src === 'function') return src(...args);
    return src === undefined ? k : src;
}

function TL(lang) {
    if (!lang) return '';
    if (uiLang === 'zh') return I18N.zh.langs[lang] || lang;
    return lang;
}

function setUILang(l) {
    if (l !== 'en' && l !== 'zh') return;
    uiLang = l;
    try { localStorage.setItem('cs_ui_lang', l); } catch (e) {}
    document.documentElement.lang = (l === 'zh' ? 'zh-CN' : 'en');
    applyStaticLabels();
    renderLangToggle();
    renderAll();
}

function applyStaticLabels() {
    document.title = T('pageTitle');
    const titleEl = document.getElementById('siteTitle');
    if (titleEl) titleEl.textContent = T('siteTitle');
    const archTitle = document.getElementById('archiveTitle');
    if (archTitle) archTitle.textContent = T('archiveTitle');
    const scanLabel = document.getElementById('scanNowLabel');
    if (scanLabel) scanLabel.textContent = T('scanNow');
    const pollBtn = document.getElementById('btnPoll');
    if (pollBtn) pollBtn.title = T('scanTooltip');
    const loadingText = document.getElementById('loadingText');
    if (loadingText) loadingText.textContent = T('loading');
    if (els && els.subLine && appInfo && appInfo.name) {
        els.subLine.textContent = T('subTemplate', appInfo.name);
    }
}

function renderLangToggle() {
    const el = document.getElementById('langToggle');
    if (!el) return;
    el.innerHTML =
        `<button class="lang-btn ${uiLang==='en'?'active':''}" onclick="setUILang('en')">EN</button>` +
        `<button class="lang-btn ${uiLang==='zh'?'active':''}" onclick="setUILang('zh')">中文</button>`;
}

let allReviews = [];
let allDates = [];
let lastPollMeta = null;
let appInfo = null;

let currentRating = 'all';         // 'all' | 1..5
let currentPlatform = 'all';       // 'all' | 'apple' | 'google_play'
let currentCountry = 'all';        // 'all' | 'us' | 'jp' | ...
let currentYear = new Date().getFullYear().toString();
let currentDateFilter = null;      // 'YYYY-MM-DD' or null
let archivePage = 0;               // bottom navigator page
let filterMonth = null;            // 0..11 when a month is being browsed in dropdown
let showMonths = false;            // month-list visible inside dropdown
let filterOpen = false;
let autoPolling = false;           // background auto-poll in-flight guard

const els = {
    ratingBtns: document.getElementById('ratingBtns'),
    filterAnchor: document.getElementById('filterDropdownAnchor'),
    activeChips: document.getElementById('activeChips'),
    content: document.getElementById('content'),
    footer: document.getElementById('footerInfo'),
    pollBtn: document.getElementById('btnPoll'),
    subLine: document.getElementById('subLine'),
    archive: document.getElementById('archiveSection'),
    archiveDates: document.getElementById('archiveDates'),
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
    if (d < 2592000) return T('relTime', d);
    return new Date(iso).toISOString().slice(0, 10);
}

function fmtDateLong(d) {
    if (!d || d === 'Unknown') return T('noDate');
    const dt = new Date(d + 'T00:00:00');
    return dt.toLocaleDateString(T('dateLocale'), {
        weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
    });
}

function platformLabel(p) {
    return p === 'apple' ? 'Apple' : (p === 'google_play' ? 'Google' : p || '');
}

function applyData(data) {
    const rows = (data.reviews || []).slice();
    rows.sort((a, b) => (b.review_date || '').localeCompare(a.review_date || ''));
    allReviews = rows;
    allDates = (data.available_dates || []).slice().sort((a, b) => b.localeCompare(a));
    lastPollMeta = data.last_poll || null;
    appInfo = data.app || null;
    if (appInfo && appInfo.name) {
        els.subLine.textContent = T('subTemplate', appInfo.name);
    }
    renderAll();
}

async function loadReviews(opts = {}) {
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

// ── Background auto-poll on page load ──────
// If the last poll is older than AUTO_POLL_THRESHOLD_MS (or already running),
// fire a silent fire-and-forget poll, wait for it to finish, then reload.
async function maybeAutoPoll() {
    if (autoPolling) return;

    let status = null;
    try {
        const r = await fetch(API + '/cs/poll-status');
        if (r.ok) status = await r.json();
    } catch (e) {}

    if (status && status.active) {
        autoPolling = true;
        showAutoPollIndicator();
        await waitForPollDone();
        hideAutoPollIndicator();
        try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
        await loadReviews({skipAutoPoll: true});
        autoPolling = false;
        return;
    }

    if (!lastPollMeta) return;
    const t = lastPollMeta.finished_at || lastPollMeta.started_at;
    if (!t) return;
    const age = Date.now() - new Date(t).getTime();
    if (isNaN(age) || age < AUTO_POLL_THRESHOLD_MS) return;

    autoPolling = true;
    showAutoPollIndicator();
    try {
        const startRes = await fetch(API + '/cs/poll', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({}),
        });
        if (!startRes.ok) { hideAutoPollIndicator(); autoPolling = false; return; }
        await waitForPollDone();
    } finally {
        hideAutoPollIndicator();
    }
    try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
    await loadReviews({skipAutoPoll: true});
    autoPolling = false;
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

// ── Filtering ──────────────────────────────
function dateOf(r) { return (r.review_date || '').slice(0, 10); }

function isWithinRecent(dateStr) {
    if (!dateStr) return false;
    const cutoff = new Date();
    cutoff.setHours(0, 0, 0, 0);
    cutoff.setDate(cutoff.getDate() - (DEFAULT_RECENT_DAYS - 1));
    return new Date(dateStr + 'T00:00:00') >= cutoff;
}

function matchesDate(r) {
    const d = dateOf(r);
    if (currentDateFilter) return d === currentDateFilter;
    // Picking any non-date filter (rating/platform/country) implicitly widens
    // the date view to the full year — otherwise narrow slices look empty
    // against the 5-day default even when they have reviews.
    if (currentRating !== 'all' || currentPlatform !== 'all' || currentCountry !== 'all') return true;
    return isWithinRecent(d);
}

function getFiltered() {
    return allReviews.filter(r => {
        if (currentRating !== 'all' && r.rating !== currentRating) return false;
        if (currentPlatform !== 'all' && r.platform !== currentPlatform) return false;
        if (currentCountry !== 'all' && (r.country || '').toLowerCase() !== currentCountry) return false;
        return matchesDate(r);
    });
}

// ── Renderers ──────────────────────────────
function renderAll() {
    renderRatingBtns();
    renderFilterDropdown();
    renderActiveChips();
    renderReviews();
    renderArchive();
    renderFooter();
}

function renderRatingBtns() {
    // All rating chip counts reflect the full-year total, scoped only by
    // platform/country. The date window is intentionally ignored so users
    // see true rating breakdowns regardless of which days are visible.
    const fullYearBase = allReviews.filter(r => {
        if (currentPlatform !== 'all' && r.platform !== currentPlatform) return false;
        if (currentCountry !== 'all' && (r.country || '').toLowerCase() !== currentCountry) return false;
        return true;
    });
    const counts = {1:0, 2:0, 3:0, 4:0, 5:0};
    fullYearBase.forEach(r => {
        const n = parseInt(r.rating) || 0;
        if (counts[n] !== undefined) counts[n]++;
    });

    let html = `<button class="rating-btn ${currentRating==='all'?'active':''}" onclick="setRating('all')">${escapeHtml(T('all'))} <span class="count">${fullYearBase.length}</span></button>`;
    [5, 4, 3, 2, 1].forEach(n => {
        const active = currentRating === n ? 'active' : '';
        html += `<button class="rating-btn ${active}" onclick="setRating(${n})">
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
    if (currentDateFilter) count++;
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

        <div class="filter-section-title">${escapeHtml(T('platform'))}</div>
        <div class="filter-options">
            <button class="filter-option ${currentPlatform==='all'?'active':''}" onclick="setPlatform('all')">${escapeHtml(T('all'))}<span class="opt-count">${allReviews.length}</span></button>
            <button class="filter-option ${currentPlatform==='apple'?'active':''}" onclick="setPlatform('apple')">Apple<span class="opt-count">${apple}</span></button>
            <button class="filter-option ${currentPlatform==='google_play'?'active':''}" onclick="setPlatform('google_play')">Google<span class="opt-count">${gplay}</span></button>
        </div>
    </div>`;

    html += `<div class="filter-section">
        <div class="filter-section-title">${escapeHtml(T('country'))}</div>
        <div class="filter-options">
            <button class="filter-option ${currentCountry==='all'?'active':''}" onclick="setCountry('all')">${escapeHtml(T('allCountries'))}<span class="opt-count">${allReviews.length}</span></button>`;
    countryKeys.forEach(c => {
        html += `<button class="filter-option ${currentCountry===c?'active':''}" onclick="setCountry('${escapeHtml(c)}')">${escapeHtml(c.toUpperCase())}<span class="opt-count">${countryCounts[c]}</span></button>`;
    });
    html += `</div></div>`;

    // ── Date section: default (son N gun) → month list → calendar
    const dateSet = new Set(allDates);
    const defaultActive = !currentDateFilter && filterMonth === null && !showMonths;
    const recentCount = allReviews.filter(r => isWithinRecent(dateOf(r))).length;
    const months = T('months');
    const dayShort = T('dayShort');
    html += `<div class="filter-section">
        <div class="filter-section-title">${escapeHtml(T('date'))}</div>
        <div class="filter-options">
            <button class="filter-option ${defaultActive?'active':''}" onclick="filterSelectYear()">${escapeHtml(T('lastNDays', DEFAULT_RECENT_DAYS))}<span class="opt-count">${recentCount}</span></button>
            <button class="filter-option${showMonths && filterMonth===null?' active':''}" onclick="toggleMonths(event)" style="padding-left:20px">${escapeHtml(T('selectMonth'))}</button>`;

    if (showMonths && filterMonth === null) {
        const monthCounts = {};
        allReviews.forEach(r => {
            const d = dateOf(r);
            if (!d) return;
            const mo = parseInt(d.slice(5, 7), 10) - 1;
            if (mo >= 0 && mo < 12) monthCounts[mo] = (monthCounts[mo] || 0) + 1;
        });
        const currentMonth = new Date().getMonth();
        for (let mo = 0; mo < 12; mo++) {
            const cnt = monthCounts[mo] || 0;
            const disabled = mo > currentMonth || cnt === 0;
            const cls = disabled ? 'filter-option disabled' : 'filter-option';
            html += `<button class="${cls}" onclick="filterSelectMonth(event,${mo})" style="padding-left:36px">${escapeHtml(months[mo])}<span class="opt-count">${cnt}</span></button>`;
        }
        html += `</div>`;
    } else if (filterMonth !== null) {
        const mo = filterMonth;
        const year = parseInt(currentYear, 10);
        const daysInMonth = new Date(year, mo + 1, 0).getDate();
        const firstDay = new Date(year, mo, 1).getDay();
        const currentMonth = new Date().getMonth();
        html += `</div>
        <div class="cal-header">
            <button onclick="filterCalPrev(event)" ${filterMonth===0?'disabled':''}>&#8249;</button>
            <span class="cal-title">${escapeHtml(months[mo])} ${year}</span>
            <button onclick="filterCalNext(event)" ${filterMonth>=currentMonth?'disabled':''}>&#8250;</button>
        </div>
        <div class="cal-grid">`;
        dayShort.forEach(d => { html += `<div class="cal-day-name">${escapeHtml(d)}</div>`; });
        for (let i = 0; i < firstDay; i++) html += `<div></div>`;
        for (let d = 1; d <= daysInMonth; d++) {
            const dateStr = `${year}-${String(mo + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
            const hasContent = dateSet.has(dateStr);
            const isActive = currentDateFilter === dateStr;
            let cls = 'cal-day';
            if (!hasContent) cls += ' disabled';
            else cls += ' has-content';
            if (isActive) cls += ' active';
            html += `<button class="${cls}" onclick="filterPickDate('${dateStr}')">${d}</button>`;
        }
        html += `</div>`;
    } else {
        html += `</div>`;
    }
    html += `</div>`;

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
    if (currentDateFilter) {
        const dt = new Date(currentDateFilter + 'T00:00:00');
        const label = dt.toLocaleDateString(T('dateLocale'), { month: 'short', day: 'numeric' });
        html += `<span class="chip">${escapeHtml(label)}<button class="chip-remove" onclick="selectDate(null)">&times;</button></span>`;
    }
    els.activeChips.innerHTML = html;
}

function renderReviews() {
    const filtered = getFiltered();
    if (!filtered.length) {
        els.content.innerHTML = `<div class="empty">${escapeHtml(T('noMatch'))}</div>`;
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
    const marker = `<div class="rating-marker" title="${rating} star${rating===1?'':'s'}">
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
        <span class="num">${rating}</span>
    </div>`;
    const platform = r.platform || '';

    // Card title + body: pick the display language based on uiLang.
    // zh mode → content_chinese / title_chinese when present, else english, else raw.
    // en mode → content_english / title_english when present, else raw.
    const titleEn = (r.title_english || '').trim();
    const titleZh = (r.title_chinese || '').trim();
    const titleOri = (r.title || '').trim();
    const contentEn = (r.content_english || '').trim();
    const contentZh = (r.content_chinese || '').trim();
    const contentOri = (r.content || '').trim();

    const cardTitle = (uiLang === 'zh' && titleZh) ? titleZh : (titleEn || titleOri);
    const body = (uiLang === 'zh' && contentZh) ? contentZh : (contentEn || contentOri);
    const title = cardTitle ? `<div class="card-title">${escapeHtml(cardTitle)}</div>` : '';

    // Details panel: original title + original body (only if they differ from
    // what's on the card) + author / version / relative date.
    const lang = (r.language || '').trim();
    const showOriTitle = titleOri && titleOri !== cardTitle;
    const showOriContent = contentOri && contentOri !== body;
    const metaParts = [];
    if (r.author) metaParts.push(`<span class="author">${escapeHtml(r.author)}</span>`);
    if (r.app_version) metaParts.push(`<span class="version">v${escapeHtml(r.app_version)}</span>`);
    if (r.review_date) {
        metaParts.push(`<span class="date" title="${escapeHtml(r.review_date)}">${escapeHtml(relTime(r.review_date))}</span>`);
    }

    let detailsInner = '';
    if (showOriTitle || showOriContent) {
        const langName = TL(lang);
        const langSuffix = langName ? ` (${escapeHtml(langName)})` : '';
        detailsInner += `<div class="original-label">${escapeHtml(T('original'))}${langSuffix}</div>`;
        if (showOriTitle) {
            detailsInner += `<div class="original-title">${escapeHtml(titleOri)}</div>`;
        }
        if (showOriContent) {
            detailsInner += `<div class="original-content">${escapeHtml(contentOri)}</div>`;
        }
    }
    if (metaParts.length) {
        detailsInner += `<div class="detail-meta">${metaParts.join('<span class="dot">·</span>')}</div>`;
    }
    const hasDetails = detailsInner.length > 0;

    // Button label = detected language (localized) or "Details"/"详情" fallback.
    const btnLabel = TL(lang) || T('detailsFallback');
    const detailsBtn = hasDetails
        ? `<button class="details-btn" data-label="${escapeHtml(btnLabel)}" onclick="toggleDetails(this)" aria-expanded="false">${escapeHtml(btnLabel)}</button>`
        : '';
    const detailsPanel = hasDetails
        ? `<div class="card-details" hidden>${detailsInner}</div>`
        : '';

    return `<div class="review-card">
        <div class="card-top">
            ${marker}
            <span class="platform-badge ${platform}">${escapeHtml(platformLabel(platform))}</span>
            <span class="country-tag">${escapeHtml((r.country || '').toUpperCase())}</span>
            ${detailsBtn}
        </div>
        ${title}
        <div class="card-content">${escapeHtml(body)}</div>
        ${detailsPanel}
    </div>`;
}

function toggleDetails(btn) {
    const card = btn.closest('.review-card');
    if (!card) return;
    const panel = card.querySelector('.card-details');
    if (!panel) return;
    const wasOpen = !panel.hasAttribute('hidden');
    if (wasOpen) panel.setAttribute('hidden', '');
    else panel.removeAttribute('hidden');
    btn.classList.toggle('open', !wasOpen);
    btn.setAttribute('aria-expanded', wasOpen ? 'false' : 'true');
    const label = btn.dataset.label || T('detailsFallback');
    btn.textContent = wasOpen ? label : T('close');
}

function renderArchive() {
    if (!allDates.length) {
        els.archive.style.display = 'none';
        return;
    }
    els.archive.style.display = '';
    const start = archivePage * DATES_PER_PAGE;
    const end = Math.min(start + DATES_PER_PAGE, allDates.length);
    const pageDates = allDates.slice(start, end);
    const hasPrev = archivePage > 0;
    const hasNext = end < allDates.length;

    const prevSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>`;
    const nextSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 6 15 12 9 18"/></svg>`;

    let html = '';
    html += `<button class="archive-nav ${hasPrev ? '' : 'disabled'}" onclick="archivePrev()" title="${escapeHtml(T('newerTitle'))}">${prevSvg}</button>`;
    html += `<button class="archive-date-btn ${!currentDateFilter?'active':''}" onclick="selectDate(null)">
        <span class="day">${escapeHtml(T('lastN'))} ${DEFAULT_RECENT_DAYS}</span><span class="month">${escapeHtml(T('days'))}</span>
    </button>`;
    pageDates.forEach(d => {
        const dt = new Date(d + 'T00:00:00');
        const day = dt.getDate();
        const month = dt.toLocaleDateString(T('dateLocale'), { month: 'short' });
        html += `<button class="archive-date-btn ${currentDateFilter===d?'active':''}" onclick="selectDate('${d}')">
            <span class="day">${day}</span><span class="month">${escapeHtml(month)}</span>
        </button>`;
    });
    html += `<button class="archive-nav ${hasNext ? '' : 'disabled'}" onclick="archiveNext()" title="${escapeHtml(T('olderTitle'))}">${nextSvg}</button>`;
    els.archiveDates.innerHTML = html;
}

function archivePrev() {
    if (archivePage <= 0) return;
    const y = els.archive.getBoundingClientRect().top;
    archivePage--;
    renderArchive();
    const drift = els.archive.getBoundingClientRect().top - y;
    if (Math.abs(drift) > 2) window.scrollBy(0, drift);
}

function archiveNext() {
    const totalPages = Math.ceil(allDates.length / DATES_PER_PAGE);
    if (archivePage >= totalPages - 1) return;
    const y = els.archive.getBoundingClientRect().top;
    archivePage++;
    renderArchive();
    const drift = els.archive.getBoundingClientRect().top - y;
    if (Math.abs(drift) > 2) window.scrollBy(0, drift);
}

function selectDate(date) {
    const y = els.archive.getBoundingClientRect().top;
    currentDateFilter = date;
    if (!date) {
        archivePage = 0;
        filterMonth = null;
        showMonths = false;
    } else {
        filterMonth = parseInt(date.slice(5, 7), 10) - 1;
    }
    renderAll();
    const drift = els.archive.getBoundingClientRect().top - y;
    if (Math.abs(drift) > 2) window.scrollBy(0, drift);
}

function filterSelectYear() {
    filterMonth = null;
    showMonths = false;
    filterOpen = false;
    els.filterAnchor.classList.remove('open');
    if (currentDateFilter) selectDate(null);
    else renderAll();
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
    els.filterAnchor.classList.remove('open');
    selectDate(dateStr);
}

function renderFooter() {
    // Steady-state footer is intentionally blank; only transient states
    // (background scan indicator, manual poll completion/error) populate it.
    els.footer.textContent = '';
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
        // Invalidate cache so the fresh data is shown
        try { localStorage.removeItem(CACHE_KEY); } catch (e) {}
        await loadReviews();
    } catch (e) {
        els.footer.textContent = T('scanError', e.message);
    } finally {
        els.pollBtn.disabled = false;
        els.pollBtn.classList.remove('is-loading');
    }
}

els.pollBtn.addEventListener('click', triggerPoll);

applyStaticLabels();
renderLangToggle();
loadReviews();
