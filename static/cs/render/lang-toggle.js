import { uiLang } from '../i18n.js?v=31';

export function renderLangToggle() {
    const el = document.getElementById('langToggle');
    if (!el) return;
    el.innerHTML =
        `<button class="lang-btn ${uiLang==='en'?'active':''}" onclick="setUILang('en')">EN</button>` +
        `<button class="lang-btn ${uiLang==='zh'?'active':''}" onclick="setUILang('zh')">中文</button>`;
}
