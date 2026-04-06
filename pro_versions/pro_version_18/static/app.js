const API_URL = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:5000'
    : 'https://duflat-production.up.railway.app';

let _currentChannelData = null;
let _currentReportData = null;

/* ── Autocomplete ──────────────────────────────────── */
const urlInput = document.getElementById('urlInput');
const suggestBox = document.getElementById('suggestDropdown');
let _suggestTimer = null;
let _suggestIdx = -1;

function looksLikeUrl(v) {
    return /^(https?:\/\/|www\.|youtu|m\.you)/.test(v) || v.includes('.com') || v.includes('.be/');
}

async function fetchSuggestions(query) {
    try {
        const resp = await fetch(`${API_URL}/suggest?q=${encodeURIComponent(query)}`);
        if (!resp.ok) return [];
        return await resp.json();
    } catch { return []; }
}

function formatSubs(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1).replace('.0','') + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1).replace('.0','') + 'K';
    return n.toString();
}

function showSuggestions(items) {
    if (!items.length) { hideSuggestions(); return; }
    _suggestIdx = -1;
    suggestBox.innerHTML = items.map((ch, i) =>
        `<div class="suggest-item" data-idx="${i}" data-cid="${escapeHTML(ch.channel_id)}">` +
        `<img src="${escapeHTML(ch.thumbnail)}" alt="" onerror="this.style.display='none'">` +
        `<span class="suggest-name">${escapeHTML(ch.name)}</span>` +
        `<span class="suggest-subs">${ch.subscribers ? formatSubs(ch.subscribers) + ' subs' : ''}</span>` +
        `</div>`
    ).join('');
    suggestBox.classList.add('open');

    suggestBox.querySelectorAll('.suggest-item').forEach(el => {
        el.addEventListener('mousedown', e => {
            e.preventDefault();
            pickSuggestion(el.dataset.cid);
        });
    });
}

function hideSuggestions() {
    suggestBox.classList.remove('open');
    suggestBox.innerHTML = '';
    _suggestIdx = -1;
}

function pickSuggestion(channelId) {
    urlInput.value = `https://www.youtube.com/channel/${channelId}`;
    hideSuggestions();
    doSearch();
}

function escapeHTML(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

urlInput.addEventListener('input', () => {
    const v = urlInput.value.trim();
    clearTimeout(_suggestTimer);
    if (v.length < 2 || looksLikeUrl(v)) { hideSuggestions(); return; }
    _suggestTimer = setTimeout(async () => {
        const items = await fetchSuggestions(v);
        showSuggestions(items);
    }, 300);
});

urlInput.addEventListener('keydown', e => {
    const items = suggestBox.querySelectorAll('.suggest-item');
    if (suggestBox.classList.contains('open') && items.length) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            _suggestIdx = Math.min(_suggestIdx + 1, items.length - 1);
            items.forEach((el, i) => el.classList.toggle('active', i === _suggestIdx));
            return;
        }
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            _suggestIdx = Math.max(_suggestIdx - 1, 0);
            items.forEach((el, i) => el.classList.toggle('active', i === _suggestIdx));
            return;
        }
        if (e.key === 'Enter' && _suggestIdx >= 0) {
            e.preventDefault();
            pickSuggestion(items[_suggestIdx].dataset.cid);
            return;
        }
        if (e.key === 'Escape') { hideSuggestions(); return; }
    }
    if (e.key === 'Enter') doSearch();
});

urlInput.addEventListener('blur', () => {
    setTimeout(hideSuggestions, 150);
});

if (API_URL.includes('RAILWAY_URL_BURAYA')) {
    document.getElementById('apiWarning').style.display = 'block';
}

async function doSearch() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) return;

    setStatus('');
    showLoader(true);
    showResult(false);
    _currentChannelData = null;
    _currentReportData = null;
    document.getElementById('searchBtn').disabled = true;

    let channelData = null;

    try {
        const res = await fetch(`${API_URL}/scrape`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (!res.ok || data.error) {
            setStatus(data.error || 'An error occurred.');
        } else {
            channelData = data;
            _currentChannelData = data;
            renderResult(data);
            const resultEl = document.getElementById('result');
            resultEl.classList.remove('reveal');
            void resultEl.offsetWidth;
            resultEl.classList.add('reveal');
            setTimeout(() => { smoothScrollTo(resultEl.querySelector('.card'), 1200); }, 300);
        }
    } catch (err) {
        setStatus('Could not reach the API - <a href="#" onclick="doSearch();return false" style="color:var(--accent)">retry</a>', true);
    } finally {
        showLoader(false);
        document.getElementById('searchBtn').disabled = false;
    }

}

async function summarizeChannel() {
    const channelData = _currentChannelData;
    if (!channelData) return;
    const btn = document.getElementById('summarizeBtn');
    const box = document.getElementById('summaryBox');
    if (!box) return;

    if (btn) { btn.disabled = true; btn.textContent = '⏳ Analyzing...'; }

    const steps = [
        'Fetching video list...',
        'Downloading transcripts (last 5 videos)...',
        'Downloading transcripts (top 5 popular)...',
        'Analyzing spoken content with AI...',
        'Building intelligence report...',
    ];
    let stepIdx = 0;
    box.innerHTML = `<div class="description-loading" style="margin-top:4px">
        <span class="spinner" style="width:13px;height:13px;border-width:2px;margin:0;display:inline-block;flex-shrink:0"></span>
        <span id="reportStep">${steps[0]}</span>
    </div>`;
    const stepTimer = setInterval(() => {
        stepIdx++;
        const el = document.getElementById('reportStep');
        if (el && stepIdx < steps.length) el.textContent = steps[stepIdx];
    }, 4000);

    try {
        const res = await fetch(`${API_URL}/summarize-v2`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_data: channelData })
        });
        clearInterval(stepTimer);
        const data = await res.json();

        if (data.report) {
            const LABELS = {
                content_language:  'Content Language',
                niche:             'Niche',
                content_themes:    'Content Themes',
                audience:          'Audience',
                content_style:     'Content Style',
                brand_fit:         'Brand Fit',
                key_insight:       'Key Insights',
            };
            let delay = 0;
            const rows = Object.entries(LABELS)
                .filter(([k]) => data.report[k])
                .map(([k, label]) => {
                    delay += 80;
                    return `<tr class="report-row" style="animation-delay:${delay}ms">
                        <td style="color:var(--muted);white-space:nowrap;padding:5px 12px 5px 0;font-size:.8rem;vertical-align:top">${label}</td>
                        <td style="padding:5px 0;font-size:.85rem;line-height:1.5">${k === 'key_insight' ? esc(data.report[k]).split(/\n+/).filter(Boolean).map(l => l.replace(/^[•]\s*/, '').trim()).filter(Boolean).map(l => '<div style="padding:2px 0 2px 12px;border-left:2px solid var(--accent);margin-bottom:5px">' + l + '</div>').join('') : esc(data.report[k])}</td>
                    </tr>`;
                }).join('');
            delay += 80;
            const tags = Array.isArray(data.tags) && data.tags.length
                ? `<div class="topic-tags report-tags" style="margin-top:10px;animation-delay:${delay}ms">${data.tags.map(t => `<span class="topic-tag">${esc(t)}</span>`).join('')}</div>`
                : '';
            delay += 80;
            const meta = data.videos_analyzed
                ? `<div class="report-meta" style="color:var(--faint);font-size:.75rem;margin-top:8px;animation-delay:${delay}ms">Analyzed ${data.videos_analyzed.total} videos (${data.videos_analyzed.transcripts_found} transcripts found)</div>`
                : '';
            box.innerHTML = `<div style="margin-bottom:10px"><table style="width:100%;border-collapse:collapse">${rows}</table>${tags}${meta}</div>`;
            _currentReportData = data;
            if (btn) { btn.disabled = true; btn.textContent = '✅ Report Ready'; }
            const arrow = document.getElementById('emailArrow');
            const emailBtn = document.getElementById('emailGenBtn');
            if (arrow) arrow.style.display = '';
            if (emailBtn) emailBtn.style.display = '';
            setTimeout(() => { smoothScrollTo(btn, 900); }, 300);
        } else {
            const errMsg = data.error || 'Could not generate report.';
            box.innerHTML = `<span style="color:var(--faint);font-size:.83rem">${esc(errMsg)} - <a href="#" onclick="summarizeChannel();return false" style="color:var(--accent)">retry</a></span>`;
            if (btn) { btn.disabled = false; btn.textContent = '✨ Generate AI Report'; }
        }
    } catch (_) {
        clearInterval(stepTimer);
        box.innerHTML = `<span style="color:var(--faint);font-size:.83rem">Could not reach the API - <a href="#" onclick="summarizeChannel();return false" style="color:var(--accent)">retry</a></span>`;
        if (btn) { btn.disabled = false; btn.textContent = '✨ Generate AI Report'; }
    }
}

async function generateEmail() {
    if (!_currentChannelData || !_currentReportData) return;
    const btn = document.getElementById('emailGenBtn');
    const box = document.getElementById('emailResultBox');
    if (!box) return;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px"><span style="display:inline-block;width:12px;height:12px;border:2px solid rgba(177,173,161,.15);border-top-color:#C15F3C;border-radius:50%;animation:spin .8s linear infinite"></span> Writing email</span>`;
    }
    // Dissolve existing email text if regenerating
    const existingPreview = box.querySelector('.email-preview');
    const isRegenerate = !!existingPreview;
    if (isRegenerate) {
        const regenBtn = box.querySelector('.email-regen-btn');
        if (regenBtn) regenBtn.style.animation = 'emailFadeOut .35s ease forwards';
        // Dissolve subject and body text
        const subjectEl = existingPreview.querySelector('.email-subject');
        const bodyEl = existingPreview.querySelector('.email-body');
        const dissolves = [];
        if (subjectEl) dissolves.push(dissolveText(subjectEl, 600));
        if (bodyEl) dissolves.push(dissolveText(bodyEl, 800));
        await Promise.all(dissolves);
        // Overlay spinner on top of the card — card skeleton stays visible
        existingPreview.style.position = 'relative';
        const overlay = document.createElement('div');
        overlay.id = 'regenOverlay';
        overlay.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:10px;background:rgba(30,30,28,.7);backdrop-filter:blur(4px);border-radius:var(--radius);z-index:2;color:var(--muted);font-size:.85rem;animation:emailFadeIn .4s ease';
        overlay.innerHTML = `<span style="display:inline-block;width:16px;height:16px;border:2px solid rgba(177,173,161,.12);border-top-color:#C15F3C;border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0"></span><span>Rewriting email</span>`;
        existingPreview.appendChild(overlay);
    } else {
        box.innerHTML = `<div id="emailLoading" style="margin-top:20px;padding:32px 20px;display:flex;align-items:center;justify-content:center;gap:10px;color:var(--muted);font-size:.85rem;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius)">
            <span style="display:inline-block;width:16px;height:16px;border:2px solid rgba(177,173,161,.12);border-top-color:#C15F3C;border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0"></span>
            <span>Writing personalized email</span>
        </div>`;
    }

    try {
        const res = await fetch(`${API_URL}/generate-email`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                channel_data: _currentChannelData,
                report_data: _currentReportData,
            })
        });
        const data = await res.json();

        if (data.subject && data.body) {
            if (isRegenerate && existingPreview) {
                // Remove overlay, update text, then resolve
                const overlay = existingPreview.querySelector('#regenOverlay');
                if (overlay) {
                    overlay.style.animation = 'emailFadeOut .3s ease forwards';
                    await new Promise(r => setTimeout(r, 350));
                    overlay.remove();
                }
                existingPreview.style.position = '';
                const subjectEl = existingPreview.querySelector('.email-subject');
                const bodyEl = existingPreview.querySelector('.email-body');
                if (subjectEl) {
                    subjectEl.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center">
                        <div><strong>Subject:</strong> ${esc(data.subject)}</div>
                        <button class="email-copy-btn" onclick="copySubject()">Copy</button>
                    </div>`;
                }
                if (bodyEl) bodyEl.innerHTML = esc(data.body).replace(/\n/g, '<br>');
                // Add regen button back
                const oldRegen = box.querySelector('.email-regen-btn');
                if (oldRegen) oldRegen.remove();
                existingPreview.insertAdjacentHTML('afterend', `
                    <button class="email-regen-btn" style="animation:emailFadeIn .5s ease" onclick="generateEmail()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
                        Regenerate
                    </button>`);
                // Resolve both
                const resolves = [];
                if (subjectEl) resolves.push(resolveText(subjectEl, 600));
                if (bodyEl) resolves.push(resolveText(bodyEl, 900));
                await Promise.all(resolves);
            } else {
                box.innerHTML = `
                    <div class="email-preview" style="animation:emailFadeIn .5s ease">
                        <div class="email-preview-header">
                            <span style="color:var(--faint);font-size:.72rem;text-transform:uppercase;letter-spacing:.5px">Email Preview</span>
                        </div>
                        <div class="email-subject">
                            <div style="display:flex;justify-content:space-between;align-items:center">
                                <div><strong>Subject:</strong> ${esc(data.subject)}</div>
                                <button class="email-copy-btn" onclick="copySubject()">Copy</button>
                            </div>
                        </div>
                        <div class="email-body-wrap">
                            <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px 0">
                                <span style="color:var(--faint);font-size:.72rem;text-transform:uppercase;letter-spacing:.5px">Body</span>
                                <button class="email-copy-btn" onclick="copyBody()">Copy</button>
                            </div>
                            <div class="email-body">${esc(data.body).replace(/\n/g, '<br>')}</div>
                        </div>
                    </div>
                    <button class="email-regen-btn" onclick="generateEmail()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
                        Regenerate
                    </button>`;
            }
            window._generatedEmail = { subject: data.subject, body: data.body };
            if (btn) { btn.disabled = true; btn.textContent = '✅ Email Ready'; }
            setTimeout(() => { smoothScrollTo(box.querySelector('.email-preview'), 1000); }, 400);
        } else {
            const errMsg = data.error || 'Could not generate email.';
            box.innerHTML = `<span style="color:var(--faint);font-size:.83rem">${esc(errMsg)} - <a href="#" onclick="generateEmail();return false" style="color:var(--accent)">retry</a></span>`;
            if (btn) { btn.disabled = false; btn.textContent = '✨ Personalized Email'; }
        }
    } catch (_) {
        box.innerHTML = `<span style="color:var(--faint);font-size:.83rem">Could not reach the API - <a href="#" onclick="generateEmail();return false" style="color:var(--accent)">retry</a></span>`;
        if (btn) { btn.disabled = false; btn.textContent = '✨ Personalized Email'; }
    }
}

// Dissolve text: characters randomly fade to invisible, keeping layout
function dissolveText(container, duration = 600) {
    return new Promise(resolve => {
        const textNodes = [];
        function walk(node) {
            if (node.nodeType === 3) {
                if (node.textContent.trim().length > 0) textNodes.push(node);
            } else if (node.childNodes) {
                node.childNodes.forEach(walk);
            }
        }
        walk(container);

        const allSpans = [];
        textNodes.forEach(tn => {
            const frag = document.createDocumentFragment();
            for (const ch of tn.textContent) {
                const span = document.createElement('span');
                span.className = 'dissolve-char';
                span.textContent = ch;
                frag.appendChild(span);
                if (ch.trim()) allSpans.push(span);
            }
            tn.parentNode.replaceChild(frag, tn);
        });

        if (allSpans.length === 0) { resolve(); return; }

        const shuffled = allSpans.sort(() => Math.random() - 0.5);
        const batchSize = Math.max(1, Math.ceil(shuffled.length / 15));
        const interval = duration / Math.ceil(shuffled.length / batchSize);
        let i = 0;

        const timer = setInterval(() => {
            const end = Math.min(i + batchSize, shuffled.length);
            for (let j = i; j < end; j++) {
                shuffled[j].classList.add('gone');
            }
            i = end;
            if (i >= shuffled.length) {
                clearInterval(timer);
                setTimeout(resolve, 300);
            }
        }, interval);
    });
}

// Resolve text: start invisible, characters randomly appear
function resolveText(container, duration = 800) {
    return new Promise(resolve => {
        const textNodes = [];
        function walk(node) {
            if (node.nodeType === 3) {
                if (node.textContent.trim().length > 0) textNodes.push(node);
            } else if (node.childNodes) {
                node.childNodes.forEach(walk);
            }
        }
        walk(container);

        const allSpans = [];
        textNodes.forEach(tn => {
            const frag = document.createDocumentFragment();
            for (const ch of tn.textContent) {
                const span = document.createElement('span');
                span.className = 'dissolve-char';
                span.textContent = ch;
                if (ch.trim()) {
                    span.classList.add('gone');
                    allSpans.push(span);
                }
                frag.appendChild(span);
            }
            tn.parentNode.replaceChild(frag, tn);
        });

        if (allSpans.length === 0) { resolve(); return; }

        const shuffled = allSpans.sort(() => Math.random() - 0.5);
        const batchSize = Math.max(1, Math.ceil(shuffled.length / 20));
        const interval = duration / Math.ceil(shuffled.length / batchSize);
        let i = 0;

        const timer = setInterval(() => {
            const end = Math.min(i + batchSize, shuffled.length);
            for (let j = i; j < end; j++) {
                shuffled[j].classList.remove('gone');
            }
            i = end;
            if (i >= shuffled.length) {
                clearInterval(timer);
                setTimeout(resolve, 300);
            }
        }, interval);
    });
}

function typewriterEffect(element, text, speed = 12) {
    return new Promise(resolve => {
        element.innerHTML = '';
        let i = 0;
        const len = text.length;
        const htmlText = text.replace(/\n/g, '<br>');
        const chunks = htmlText.split(/(<br>)/);
        let fullOutput = '';
        let charIndex = 0;
        let chunkIndex = 0;
        let posInChunk = 0;

        function scrollToCursor() {
            const cur = element.querySelector('.tw-cursor');
            if (!cur) return;
            const rect = cur.getBoundingClientRect();
            const target = window.pageYOffset + rect.top - window.innerHeight * 0.65;
            if (target > window.pageYOffset) {
                window.scrollTo({ top: target, behavior: 'smooth' });
            }
        }

        function tick() {
            if (chunkIndex >= chunks.length) { resolve(); return; }
            const chunk = chunks[chunkIndex];
            if (chunk === '<br>') {
                fullOutput += '<br>';
                element.innerHTML = fullOutput + '<span class="tw-cursor">|</span>';
                scrollToCursor();
                chunkIndex++;
                posInChunk = 0;
                setTimeout(tick, speed);
                return;
            }
            if (posInChunk < chunk.length) {
                const burst = Math.min(2 + Math.floor(Math.random() * 3), chunk.length - posInChunk);
                fullOutput += chunk.substring(posInChunk, posInChunk + burst);
                posInChunk += burst;
                element.innerHTML = fullOutput + '<span class="tw-cursor">|</span>';
                scrollToCursor();
                const jitter = speed + Math.floor(Math.random() * 10) - 4;
                setTimeout(tick, Math.max(4, jitter));
            } else {
                chunkIndex++;
                posInChunk = 0;
                tick();
            }
        }
        tick();
    });
}

function copySubject() {
    if (!window._generatedEmail) return;
    navigator.clipboard.writeText(window._generatedEmail.subject).then(() => {
        const btns = document.querySelectorAll('.email-copy-btn');
        if (btns[0]) { btns[0].textContent = 'Copied!'; setTimeout(() => { btns[0].textContent = 'Copy'; }, 2000); }
    });
}

function copyBody() {
    if (!window._generatedEmail) return;
    navigator.clipboard.writeText(window._generatedEmail.body).then(() => {
        const btns = document.querySelectorAll('.email-copy-btn');
        if (btns[1]) { btns[1].textContent = 'Copied!'; setTimeout(() => { btns[1].textContent = 'Copy'; }, 2000); }
    });
}

async function investigateEmail() {
    if (!_currentChannelData) return;

    const btn = document.getElementById('findEmailBtn');
    const emailItem = document.getElementById('emailInfoItem');
    if (!emailItem) return;

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px"><span style="display:inline-block;width:12px;height:12px;border:2px solid rgba(177,173,161,.15);border-top-color:#C15F3C;border-radius:50%;animation:spin .8s linear infinite"></span> Searching<span class="dots-anim"></span></span>`;
    }
    emailItem.querySelector('.meta-value').innerHTML =
        `<span style="display:inline-flex;align-items:center;gap:6px;color:var(--muted);font-size:.85rem">
            <span style="display:inline-block;width:14px;height:14px;border:2px solid rgba(177,173,161,.12);border-top-color:#C15F3C;border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0"></span>
            Investigating email sources<span class="dots-anim"></span>
        </span>`;

    try {
        const res = await fetch(`${API_URL}/find-email-v2`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel_data: _currentChannelData })
        });
        const data = await res.json();

        if (data.found && data.email) {
            emailItem.querySelector('.meta-value').innerHTML =
                `<span class="report-row" style="animation-delay:0ms"><a href="mailto:${esc(data.email)}">${esc(data.email)}</a></span>`;
            _currentChannelData = { ..._currentChannelData, email: data.email };
            if (btn) { btn.disabled = true; btn.textContent = '\u2713 Email Found'; }
        } else {
            const hiddenMsg = _currentChannelData?.has_hidden_email
                ? `<span style="color:var(--accent);font-size:.85rem" title="This channel has a business email but YouTube requires login to reveal it">🔒 Email exists but hidden by YouTube</span>`
                : `<span style="color:var(--faint);font-style:italic;font-size:.85rem">No email found</span>`;
            emailItem.querySelector('.meta-value').innerHTML = hiddenMsg;
            if (btn) { btn.disabled = false; btn.innerHTML = '🔍 Find Email'; }
        }
    } catch (err) {
        emailItem.querySelector('.meta-value').innerHTML =
            `<span style="color:var(--faint);font-size:.83rem">Search failed - <a href="#" onclick="investigateEmail();return false" style="color:var(--accent)">retry</a></span>`;
        if (btn) { btn.disabled = false; btn.innerHTML = '🔍 Find Email'; }
    }
}

function renderResult(d) {
    const name    = d.name || 'Unknown Channel';
    const initial = name.charAt(0).toUpperCase();
    const socialKeys  = ['instagram', 'tiktok', 'twitter', 'facebook', 'discord', 'twitch', 'myanimelist'];
    const socialIcons = { instagram:'📷', tiktok:'🎵', twitter:'𝕏', facebook:'👤', discord:'💬', twitch:'🎮', myanimelist:'🎌' };
    const socialNames = { instagram:'Instagram', tiktok:'TikTok', twitter:'X / Twitter', facebook:'Facebook', discord:'Discord', twitch:'Twitch', myanimelist:'MyAnimeList' };

    const socialBadges = socialKeys
        .filter(s => d[s])
        .map(s => `<a class="social-badge" href="${esc(d[s])}" target="_blank" rel="noopener">${socialIcons[s]} ${socialNames[s]}</a>`)
        .join('');

    const allLinks = Array.isArray(d.all_links) ? d.all_links : [];
    const linkItems = allLinks.slice(0, 12)
        .map(l => `<a href="${esc(l)}" target="_blank" rel="noopener">${esc(l)}</a>`)
        .join('');

    document.getElementById('result').innerHTML = `
        <div class="card">
            <div class="card-header">
                ${d.thumbnail && d.thumbnail.includes('yt3.')
                    ? `<img class="channel-avatar" src="${esc(d.thumbnail)}" alt="" style="object-fit:cover" onerror="this.outerHTML='<div class=channel-avatar>${initial}</div>'">`
                    : `<div class="channel-avatar">${initial}</div>`
                }
                <div>
                    <div class="channel-name">${esc(name)}</div>
                    ${d.handle     ? `<div class="channel-handle">${esc(d.handle)}</div>` : ''}
                    ${d.channel_url? `<a class="channel-url-link" href="${esc(d.channel_url)}" target="_blank" rel="noopener">${esc(d.channel_url)}</a>` : ''}
                </div>
            </div>

            <div class="stats-row">
                ${statItem(d.subscribers,    'Subscribers')}
                ${statItem(d.videos,         'Videos')}
                ${statItem(d.views,          'Total Views')}
                ${statItem(d.last_video_date,'Last Video')}
            </div>

            <div class="meta-section">
                <div class="meta-row" id="emailInfoItem">
                    <span class="meta-label">Email</span>
                    ${d.email
                        ? `<span class="meta-value"><a href="mailto:${esc(d.email)}">${esc(d.email)}</a></span>`
                        : `<span class="meta-value">
                               ${d.has_hidden_email
                                   ? `<span style="color:var(--faint);font-size:.78rem" title="YouTube requires login to reveal this email">🔒 Hidden email</span>`
                                   : ''}
                               <button class="find-email-btn" id="findEmailBtn" onclick="investigateEmail()">
                                   🔍 Find Email
                               </button>
                           </span>`
                    }
                </div>
                ${d.location ? `
                <div class="meta-row">
                    <span class="meta-label">Location</span>
                    <span class="meta-value">${esc(d.location)}</span>
                </div>` : ''}
                ${d.joined ? `
                <div class="meta-row">
                    <span class="meta-label">Joined</span>
                    <span class="meta-value">${esc(d.joined)}</span>
                </div>` : ''}
            </div>

            <div class="about-section" id="summaryBlock">
                <div class="about-section-header">
                    <div class="report-btn-row">
                        <button class="ai-report-btn" id="summarizeBtn" onclick="summarizeChannel()">
                            ✨ Generate AI Report
                        </button>
                        <span class="btn-arrow" id="emailArrow" style="display:none">›</span>
                        <button class="email-gen-btn" id="emailGenBtn" onclick="generateEmail()" style="display:none">
                            ✨ Personalized Email
                        </button>
                    </div>
                </div>
                <div id="summaryBox"></div>
                <div style="margin-top:16px">
                    <span class="section-label" style="margin-left:3px">About</span>
                </div>
                <div class="description-box" style="margin-top:8px">
                    ${d.description
                        ? `<div style="font-family:var(--font-sans);white-space:pre-wrap;max-height:110px;overflow-y:auto">${esc(d.description)}</div>`
                        : `<span style="color:var(--faint);font-style:italic">No description available.</span>`
                    }
                </div>
            </div>

            ${socialBadges ? `<div class="social-grid">${socialBadges}</div>` : ''}

            ${linkItems ? `
            <div class="all-links-section">
                <div class="all-links-title">Creator's External Links</div>
                <div class="link-list">${linkItems}</div>
            </div>` : ''}
        </div>
        <div id="emailResultBox"></div>`;
    showResult(true);
}

function statItem(val, label) {
    return `<div class="stat-item">
        <div class="stat-value">${val ? esc(val) : `<span style="color:var(--faint)">—</span>`}</div>
        <div class="stat-label">${label}</div>
    </div>`;
}

function infoItem(label, val) {
    if (!val) return `<div class="info-item">
        <span class="info-label">${label}</span>
        <span class="info-value empty">—</span>
    </div>`;
    return `<div class="info-item">
        <span class="info-label">${label}</span>
        <span class="info-value">${val}</span>
    </div>`;
}

function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function setStatus(msg, html) {
    const el = document.getElementById('statusMsg');
    if (html) el.innerHTML = msg; else el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
}

function smoothScrollTo(el, duration) {
    if (!el) return;
    const target = el.getBoundingClientRect().top + window.pageYOffset - 20;
    const start = window.pageYOffset;
    const diff = target - start;
    let startTime = null;
    function ease(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
    function step(time) {
        if (!startTime) startTime = time;
        const progress = Math.min((time - startTime) / duration, 1);
        window.scrollTo(0, start + diff * ease(progress));
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

function showLoader(show) { document.getElementById('loader').style.display = show ? 'block' : 'none'; }
function showResult(show) { document.getElementById('result').style.display = show ? 'block' : 'none'; }
