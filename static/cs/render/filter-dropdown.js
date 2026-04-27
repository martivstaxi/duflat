import { escapeHtml } from '../utils.js?v=33';
import { T, TC } from '../i18n.js?v=33';
import {
    allDates, allReviews, currentCountry, currentDateFilter, currentPlatform, currentYear,
    filterMonth, filterOpen, showMonths,
    setCurrentDateFilter, setFilterMonth, setFilterOpen, setShowMonths,
} from '../state.js?v=33';
import { dateOf } from '../filters.js?v=33';
import { els } from '../dom.js?v=33';

// Central dropdown view — filters.
// Contents: Platform section, Country section (with code + localized name),
// Date section (default "year / select month" → month-list → calendar grid).
export function renderFilterDropdown() {
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
            <button class="filter-option ${currentCountry==='all'?'active':''}" onclick="setCountry('all')"><span class="opt-name">${escapeHtml(T('allCountries'))}</span><span class="opt-count">${allReviews.length}</span></button>`;
    countryKeys.forEach(c => {
        html += `<button class="filter-option ${currentCountry===c?'active':''}" onclick="setCountry('${escapeHtml(c)}')"><span class="opt-code">${escapeHtml(c.toUpperCase())}</span><span class="opt-name">${escapeHtml(TC(c))}</span><span class="opt-count">${countryCounts[c]}</span></button>`;
    });
    html += `</div></div>`;

    // Date section: default year → month list → calendar.
    const dateSet = new Set(allDates);
    const defaultActive = !currentDateFilter && filterMonth === null && !showMonths;
    const months = T('months');
    const dayShort = T('dayShort');
    html += `<div class="filter-section">
        <div class="filter-section-title">${escapeHtml(T('date'))}</div>
        <div class="filter-options">
            <button class="filter-option ${defaultActive?'active':''}" onclick="filterSelectYear()">${escapeHtml(currentYear)}<span class="opt-count">${allReviews.length}</span></button>
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
    // Mirror state → DOM both ways so closing-via-state-setter works.
    els.filterAnchor.classList.toggle('open', filterOpen);
}

// ── Handlers (inline onclick → window-exposed via app.js) ──
export function toggleFilterPanel(e) {
    if (e) e.stopPropagation();
    setFilterOpen(!filterOpen);
    els.filterAnchor.classList.toggle('open', filterOpen);
}

export function filterSelectYear() {
    setFilterMonth(null);
    setShowMonths(false);
    setFilterOpen(false);
    els.filterAnchor.classList.remove('open');
    if (currentDateFilter) {
        // Defer to archive.selectDate(null) so archive-scroll-preservation runs.
        document.dispatchEvent(new CustomEvent('cs:select-date', {detail: null}));
    } else {
        document.dispatchEvent(new CustomEvent('cs:render'));
    }
}

export function toggleMonths(e) {
    if (e) e.stopPropagation();
    setShowMonths(!showMonths);
    setFilterMonth(null);
    renderFilterDropdown();
}

export function filterSelectMonth(e, mo) {
    if (e) e.stopPropagation();
    setFilterMonth(mo);
    setShowMonths(false);
    renderFilterDropdown();
}

export function filterCalPrev(e) {
    if (e) e.stopPropagation();
    if (filterMonth > 0) { setFilterMonth(filterMonth - 1); renderFilterDropdown(); }
}

export function filterCalNext(e) {
    if (e) e.stopPropagation();
    const currentMonth = new Date().getMonth();
    if (filterMonth < currentMonth) { setFilterMonth(filterMonth + 1); renderFilterDropdown(); }
}

export function filterPickDate(dateStr) {
    setFilterOpen(false);
    els.filterAnchor.classList.remove('open');
    document.dispatchEvent(new CustomEvent('cs:select-date', {detail: dateStr}));
}
