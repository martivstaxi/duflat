// Runtime knobs. Change once here, affects every module.

export const CACHE_KEY = 'cs_reviews_cache_v2';
export const CACHE_TTL = 5 * 60 * 1000;

export const DATES_PER_PAGE = 4;
export const DEFAULT_RECENT_DAYS = 5;   // initial view window; archive/calendar drills deeper
export const AUTO_POLL_THRESHOLD_MS = 3 * 60 * 60 * 1000;  // page load bg-poll if last poll > 3h

export const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? ''
    : 'https://duflat-production.up.railway.app';
