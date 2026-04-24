// Entry point. Responsibilities:
//   1. Wire up the renderAll orchestration (one listener on cs:render).
//   2. Expose every inline-onclick handler to window so the existing HTML
//      keeps working without refactor.
//   3. Paint static labels + lang toggle on boot, then kick off loadReviews.
//
// No business logic lives here — each concern is in its own module.

import { applyStaticLabels, setUILang, T } from './i18n.js?v=31';
import {
    appInfo, setCountry, setFilterOpen, setPlatform, setRating,
} from './state.js?v=31';
import { els } from './dom.js?v=31';
import { loadReviews } from './api.js?v=31';

import { renderLangToggle } from './render/lang-toggle.js?v=31';
import { renderRatingBtns } from './render/rating-btns.js?v=31';
import {
    renderFilterDropdown, toggleFilterPanel, filterSelectYear, toggleMonths,
    filterSelectMonth, filterCalPrev, filterCalNext, filterPickDate,
} from './render/filter-dropdown.js?v=31';
import { renderActiveChips } from './render/active-chips.js?v=31';
import { renderReviews, toggleDetails } from './render/cards.js?v=31';
import { renderArchive, archivePrev, archiveNext, selectDate } from './render/archive.js?v=31';
import { renderFooter } from './render/footer.js?v=31';
import { openInsights, closeInsights, setInsightsPeriod, onLangChange as onInsightsLangChange } from './insights.js?v=31';

// ── Global orchestration ────────────────────
// Fired by state setters, setUILang(), and applyData() via cs:render event.
function renderAll() {
    renderLangToggle();
    renderRatingBtns();
    renderFilterDropdown();
    renderActiveChips();
    renderReviews();
    renderArchive();
    renderFooter();
    // subLine depends on live state (app name from /cs/reviews response).
    if (appInfo && appInfo.name && els.subLine) {
        els.subLine.textContent = T('subTemplate', appInfo.name);
    }
    // If the insights modal is open, keep its language aligned.
    onInsightsLangChange();
}
document.addEventListener('cs:render', renderAll);

// selectDate() is called both from the archive row and from the filter
// dropdown's "year" shortcut. The dropdown can't import from archive.js
// without creating a render cycle, so it routes through this event.
document.addEventListener('cs:select-date', e => selectDate(e.detail ?? null));

// ── Inline onclick → global bindings (keeps cs.html untouched) ──
Object.assign(window, {
    setUILang, setRating, setPlatform, setCountry,
    toggleFilterPanel, filterSelectYear, toggleMonths,
    filterSelectMonth, filterCalPrev, filterCalNext, filterPickDate,
    toggleDetails, selectDate, archivePrev, archiveNext,
    loadReviews,
    openInsights, closeInsights, setInsightsPeriod,
});

// Dismiss dropdown on outside click. Lives here because it needs the
// page-level click surface, not the dropdown itself.
document.addEventListener('click', e => {
    const anchor = els.filterAnchor;
    const toggle = document.getElementById('filterToggle');
    if (!anchor.classList.contains('open')) return;
    if (anchor.contains(e.target) || (toggle && toggle.contains(e.target))) return;
    anchor.classList.remove('open');
    setFilterOpen(false);
});

// ── Boot ────────────────────────────────────
applyStaticLabels();
renderLangToggle();
loadReviews();
