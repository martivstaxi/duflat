import { escapeHtml, fmtDateLong, platformLabel, relTime } from '../utils.js?v=33';
import { T, TL, uiLang } from '../i18n.js?v=33';
import { getFiltered } from '../filters.js?v=33';
import { els } from '../dom.js?v=33';

export function renderReviews() {
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

export function toggleDetails(btn) {
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
