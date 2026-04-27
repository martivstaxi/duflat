import { DEFAULT_RECENT_DAYS } from './constants.js?v=33';
import {
    allReviews, currentCountry, currentDateFilter, currentPlatform, currentRating,
} from './state.js?v=33';

export function dateOf(r) { return (r.review_date || '').slice(0, 10); }

export function isWithinRecent(dateStr) {
    if (!dateStr) return false;
    const cutoff = new Date();
    cutoff.setHours(0, 0, 0, 0);
    cutoff.setDate(cutoff.getDate() - (DEFAULT_RECENT_DAYS - 1));
    return new Date(dateStr + 'T00:00:00') >= cutoff;
}

// Picking any non-date filter (rating/platform/country) implicitly widens
// the date view to the full year — otherwise narrow slices look empty
// against the 5-day default even when they have reviews.
export function matchesDate(r) {
    const d = dateOf(r);
    if (currentDateFilter) return d === currentDateFilter;
    if (currentRating !== 'all' || currentPlatform !== 'all' || currentCountry !== 'all') return true;
    return isWithinRecent(d);
}

export function getFiltered() {
    return allReviews.filter(r => {
        if (currentRating !== 'all' && r.rating !== currentRating) return false;
        if (currentPlatform !== 'all' && r.platform !== currentPlatform) return false;
        if (currentCountry !== 'all' && (r.country || '').toLowerCase() !== currentCountry) return false;
        return matchesDate(r);
    });
}
