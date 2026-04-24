import { DATES_PER_PAGE, DEFAULT_RECENT_DAYS } from '../constants.js?v=31';
import { escapeHtml } from '../utils.js?v=31';
import { T } from '../i18n.js?v=31';
import {
    allDates, archivePage, currentDateFilter,
    setArchivePage, setCurrentDateFilter, setFilterMonth, setShowMonths,
} from '../state.js?v=31';
import { els } from '../dom.js?v=31';

export function renderArchive() {
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

export function archivePrev() {
    if (archivePage <= 0) return;
    const y = els.archive.getBoundingClientRect().top;
    setArchivePage(archivePage - 1);
    renderArchive();
    const drift = els.archive.getBoundingClientRect().top - y;
    if (Math.abs(drift) > 2) window.scrollBy(0, drift);
}

export function archiveNext() {
    const totalPages = Math.ceil(allDates.length / DATES_PER_PAGE);
    if (archivePage >= totalPages - 1) return;
    const y = els.archive.getBoundingClientRect().top;
    setArchivePage(archivePage + 1);
    renderArchive();
    const drift = els.archive.getBoundingClientRect().top - y;
    if (Math.abs(drift) > 2) window.scrollBy(0, drift);
}

export function selectDate(date) {
    const y = els.archive.getBoundingClientRect().top;
    setCurrentDateFilter(date);
    if (!date) {
        setArchivePage(0);
        setFilterMonth(null);
        setShowMonths(false);
    } else {
        setFilterMonth(parseInt(date.slice(5, 7), 10) - 1);
    }
    document.dispatchEvent(new CustomEvent('cs:render'));
    const drift = els.archive.getBoundingClientRect().top - y;
    if (Math.abs(drift) > 2) window.scrollBy(0, drift);
}
