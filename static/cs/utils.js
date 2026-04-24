import { T } from './i18n.js?v=30';

export function escapeHtml(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function starStr(n) {
    n = Math.max(0, Math.min(5, parseInt(n) || 0));
    return '★'.repeat(n) + '☆'.repeat(5 - n);
}

export function relTime(iso) {
    if (!iso) return '';
    const t = new Date(iso).getTime();
    if (isNaN(t)) return '';
    const d = Math.floor((Date.now() - t) / 1000);
    if (d < 2592000) return T('relTime', d);
    return new Date(iso).toISOString().slice(0, 10);
}

export function fmtDateLong(d) {
    if (!d || d === 'Unknown') return T('noDate');
    const dt = new Date(d + 'T00:00:00');
    return dt.toLocaleDateString(T('dateLocale'), {
        weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
    });
}

export function platformLabel(p) {
    return p === 'apple' ? 'Apple' : (p === 'google_play' ? 'Google' : p || '');
}
