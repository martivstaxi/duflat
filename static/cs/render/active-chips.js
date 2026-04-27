import { escapeHtml, platformLabel, starStr } from '../utils.js?v=37';
import { T } from '../i18n.js?v=37';
import { currentCountry, currentDateFilter, currentPlatform, currentRating } from '../state.js?v=37';
import { els } from '../dom.js?v=37';

export function renderActiveChips() {
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
