// Single owner of UI + data state. Readers import the `let` bindings
// (live — they track updates made in this module). Writers call the
// exported setters, which both mutate and dispatch a `cs:render` event
// so app.js can re-run renderAll.

export let allReviews = [];
export let allDates = [];
export let lastPollMeta = null;
export let appInfo = null;

export let currentRating = 'all';       // 'all' | 1..5
export let currentPlatform = 'all';     // 'all' | 'apple' | 'google_play'
export let currentCountry = 'all';      // 'all' | 'us' | 'jp' | ...
export let currentYear = new Date().getFullYear().toString();
export let currentDateFilter = null;    // 'YYYY-MM-DD' or null

export let archivePage = 0;             // bottom navigator page
export let filterMonth = null;          // 0..11 when a month is being browsed
export let showMonths = false;          // month-list visible inside dropdown
export let filterOpen = false;
export let autoPolling = false;         // background auto-poll in-flight guard

function renderSoon() {
    document.dispatchEvent(new CustomEvent('cs:render'));
}

// ── Data writers (called by api.js after fetch)
export function applyData(data) {
    // Server returns rows already ordered review_date DESC — no re-sort needed.
    allReviews = (data.reviews || []).slice();
    allDates = (data.available_dates || []).slice().sort((a, b) => b.localeCompare(a));
    lastPollMeta = data.last_poll || null;
    appInfo = data.app || null;
    renderSoon();
}

export function setAutoPolling(v) { autoPolling = !!v; }

// ── Filter writers
export function setRating(v) {
    currentRating = v === 'all' ? 'all' : parseInt(v);
    renderSoon();
}

export function setPlatform(v) {
    currentPlatform = v;
    filterOpen = false;
    renderSoon();
}

export function setCountry(v) {
    currentCountry = v;
    filterOpen = false;
    renderSoon();
}

// ── Dropdown UI-state writers
export function setFilterOpen(v) { filterOpen = !!v; }
export function setArchivePage(n) { archivePage = n; }
export function setFilterMonth(n) { filterMonth = n; }
export function setShowMonths(v) { showMonths = !!v; }
export function setCurrentDateFilter(d) { currentDateFilter = d; }
