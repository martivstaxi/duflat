import { escapeHtml, starStr } from '../utils.js?v=31';
import { T } from '../i18n.js?v=31';
import { allReviews, currentCountry, currentDateFilter, currentPlatform, currentRating } from '../state.js?v=31';
import { els } from '../dom.js?v=31';

export function renderRatingBtns() {
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
