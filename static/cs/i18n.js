// Bilingual (EN + Simplified Chinese) UI strings + detected-value localizers.
// Card body/title: uiLang='zh' && content_chinese available → Chinese, else English.
// Original content (in the Details panel) is NEVER translated.

export const I18N = {
    en: {
        siteTitle: 'User Comments',
        pageTitle: 'Duflat — User Comments',
        subTemplate: (app) => `${app} · App Store & Play`,
        loading: 'Loading comments...',
        loadError: (msg) => `Load error: ${msg}`,
        tryAgain: 'try again',
        noMatch: 'No comments match the filters.',
        noDate: 'No date',
        all: 'All',
        allCountries: 'All countries',
        platform: 'Platform',
        country: 'Country',
        date: 'Date',
        lastNDays: (n) => `Last ${n} days`,
        selectMonth: 'Select month',
        archiveTitle: 'Browse by date',
        lastN: 'Last',
        days: 'days',
        olderTitle: 'Older',
        newerTitle: 'Newer',
        original: 'Original',
        detailsFallback: 'Details',
        close: 'Close',
        scanning: 'Scanning for fresh comments in background…',
        // Health Check modal
        insightsTitle: 'Health Check',
        insightsTooltip: 'Health Check',
        period7d: '7 days',
        period30d: '30 days',
        periodYear: () => String(new Date().getFullYear()),
        insightsLoading: 'Analyzing reviews…',
        insightsError: 'Could not load report. Try again shortly.',
        insightsOffline: 'AI summary unavailable right now.',
        insightsNoData: 'No reviews in this window yet.',
        metricTotal: 'Reviews',
        metricAvg: 'Rating',
        metricLow: '1–2★',
        summaryLabel: 'Summary',
        issuesLabel: 'Top issues',
        praiseLabel: 'Highlights',
        anomalyLabel: 'Heads up',
        noIssues: 'No 1–2★ reviews in this window.',
        insightsGenerated: (rel) => `Updated ${rel}`,
        // CSV export modal
        exportTooltip: 'Download CSV',
        exportTitle: 'Download as CSV',
        exportPeriod7d: 'Last 7 days',
        exportPeriod30d: 'Last 30 days',
        exportPeriodAll: 'All',
        exportSummary: (n) => n === 1 ? '1 review ready' : `${n.toLocaleString('en-US')} reviews ready`,
        exportDownload: 'Download',
        csvDate: 'Date',
        csvPlatform: 'Platform',
        csvCountry: 'Country',
        csvRating: 'Rating',
        csvVersion: 'Version',
        csvAuthor: 'Author',
        csvLanguage: 'Language',
        csvTitle: 'Title',
        csvContent: 'Content',
        months: ['January','February','March','April','May','June','July','August','September','October','November','December'],
        dayShort: ['Su','Mo','Tu','We','Th','Fr','Sa'],
        relTime: (d) => {
            if (d < 60) return d + 's ago';
            if (d < 3600) return Math.floor(d / 60) + 'm ago';
            if (d < 86400) return Math.floor(d / 3600) + 'h ago';
            return Math.floor(d / 86400) + 'd ago';
        },
        dateLocale: 'en-US',
        langs: {},
        countries: {
            us: 'United States', gb: 'United Kingdom', ca: 'Canada', au: 'Australia',
            nz: 'New Zealand', ie: 'Ireland',
            de: 'Germany', fr: 'France', it: 'Italy', es: 'Spain', nl: 'Netherlands',
            be: 'Belgium', ch: 'Switzerland', at: 'Austria',
            se: 'Sweden', no: 'Norway', dk: 'Denmark', fi: 'Finland',
            pl: 'Poland', cz: 'Czechia', sk: 'Slovakia', hu: 'Hungary',
            ro: 'Romania', bg: 'Bulgaria', hr: 'Croatia', si: 'Slovenia',
            rs: 'Serbia', gr: 'Greece', pt: 'Portugal',
            lt: 'Lithuania', lv: 'Latvia', ee: 'Estonia', is: 'Iceland',
            mt: 'Malta', lu: 'Luxembourg', cy: 'Cyprus', md: 'Moldova',
            hk: 'Hong Kong', mo: 'Macau', tw: 'Taiwan', jp: 'Japan', kr: 'South Korea',
            sg: 'Singapore', my: 'Malaysia', id: 'Indonesia', ph: 'Philippines',
            th: 'Thailand', vn: 'Vietnam',
            in: 'India', pk: 'Pakistan', bd: 'Bangladesh', lk: 'Sri Lanka', np: 'Nepal',
            ru: 'Russia', ua: 'Ukraine', by: 'Belarus', kz: 'Kazakhstan',
            uz: 'Uzbekistan', az: 'Azerbaijan', am: 'Armenia', ge: 'Georgia',
            kg: 'Kyrgyzstan', tj: 'Tajikistan', tm: 'Turkmenistan',
            tr: 'Turkey', il: 'Israel', sa: 'Saudi Arabia', ae: 'UAE',
            qa: 'Qatar', kw: 'Kuwait', bh: 'Bahrain', om: 'Oman',
            jo: 'Jordan', lb: 'Lebanon', eg: 'Egypt',
            za: 'South Africa', ng: 'Nigeria', ke: 'Kenya', gh: 'Ghana',
            tz: 'Tanzania', ug: 'Uganda', zw: 'Zimbabwe', ci: "Côte d'Ivoire",
            sn: 'Senegal', cm: 'Cameroon', dz: 'Algeria', ma: 'Morocco', tn: 'Tunisia',
            br: 'Brazil', mx: 'Mexico', ar: 'Argentina', cl: 'Chile', co: 'Colombia',
            pe: 'Peru', uy: 'Uruguay', py: 'Paraguay', bo: 'Bolivia',
            ve: 'Venezuela', ec: 'Ecuador',
            cr: 'Costa Rica', pa: 'Panama', gt: 'Guatemala', sv: 'El Salvador',
            hn: 'Honduras', ni: 'Nicaragua', do: 'Dominican Republic',
        },
    },
    zh: {
        siteTitle: '用户评论',
        pageTitle: 'Duflat — 用户评论',
        subTemplate: (app) => `${app} · App Store 与 Google Play`,
        loading: '正在加载评论...',
        loadError: (msg) => `加载失败：${msg}`,
        tryAgain: '重试',
        noMatch: '没有符合筛选条件的评论。',
        noDate: '无日期',
        all: '全部',
        allCountries: '全部国家',
        platform: '平台',
        country: '国家',
        date: '日期',
        lastNDays: (n) => `最近 ${n} 天`,
        selectMonth: '选择月份',
        archiveTitle: '按日期浏览',
        lastN: '最近',
        days: '天',
        olderTitle: '较旧',
        newerTitle: '较新',
        original: '原文',
        detailsFallback: '详情',
        close: '关闭',
        scanning: '正在后台扫描最新评论…',
        // 健康检查弹窗
        insightsTitle: '健康检查',
        insightsTooltip: '健康检查',
        period7d: '7 天',
        period30d: '30 天',
        periodYear: () => String(new Date().getFullYear()),
        insightsLoading: '正在分析评论…',
        insightsError: '报告加载失败，请稍后再试。',
        insightsOffline: 'AI 摘要暂不可用。',
        insightsNoData: '此时段暂无评论。',
        metricTotal: '评论',
        metricAvg: '评分',
        metricLow: '1–2 星',
        summaryLabel: '摘要',
        issuesLabel: '主要问题',
        praiseLabel: '亮点',
        anomalyLabel: '留意',
        noIssues: '此时段没有 1–2 星评论。',
        insightsGenerated: (rel) => `更新于 ${rel}`,
        // CSV 导出弹窗
        exportTooltip: '下载 CSV',
        exportTitle: '导出为 CSV',
        exportPeriod7d: '最近 7 天',
        exportPeriod30d: '最近 30 天',
        exportPeriodAll: '全部',
        exportSummary: (n) => `${n.toLocaleString('zh-CN')} 条评论待导出`,
        exportDownload: '下载',
        csvDate: '日期',
        csvPlatform: '平台',
        csvCountry: '国家',
        csvRating: '评分',
        csvVersion: '版本',
        csvAuthor: '作者',
        csvLanguage: '语言',
        csvTitle: '标题',
        csvContent: '内容',
        months: ['一月','二月','三月','四月','五月','六月','七月','八月','九月','十月','十一月','十二月'],
        dayShort: ['日','一','二','三','四','五','六'],
        relTime: (d) => {
            if (d < 60) return d + ' 秒前';
            if (d < 3600) return Math.floor(d / 60) + ' 分钟前';
            if (d < 86400) return Math.floor(d / 3600) + ' 小时前';
            return Math.floor(d / 86400) + ' 天前';
        },
        dateLocale: 'zh-CN',
        langs: {
            English: '英语', Spanish: '西班牙语', Portuguese: '葡萄牙语',
            French: '法语', German: '德语', Italian: '意大利语',
            Dutch: '荷兰语', Polish: '波兰语', Czech: '捷克语',
            Slovak: '斯洛伐克语', Hungarian: '匈牙利语', Romanian: '罗马尼亚语',
            Greek: '希腊语', Swedish: '瑞典语', Norwegian: '挪威语',
            Danish: '丹麦语', Finnish: '芬兰语',
            Japanese: '日语', Korean: '韩语',
            'Traditional Chinese': '繁体中文', 'Simplified Chinese': '简体中文',
            Chinese: '中文',
            Arabic: '阿拉伯语', Turkish: '土耳其语', Russian: '俄语',
            Ukrainian: '乌克兰语', Hebrew: '希伯来语',
            Indonesian: '印尼语', Malay: '马来语', Thai: '泰语',
            Vietnamese: '越南语', Hindi: '印地语', Bengali: '孟加拉语',
            Tagalog: '他加禄语', Other: '其他', Unknown: '未知',
        },
        countries: {
            us: '美国', gb: '英国', ca: '加拿大', au: '澳大利亚',
            nz: '新西兰', ie: '爱尔兰',
            de: '德国', fr: '法国', it: '意大利', es: '西班牙', nl: '荷兰',
            be: '比利时', ch: '瑞士', at: '奥地利',
            se: '瑞典', no: '挪威', dk: '丹麦', fi: '芬兰',
            pl: '波兰', cz: '捷克', sk: '斯洛伐克', hu: '匈牙利',
            ro: '罗马尼亚', bg: '保加利亚', hr: '克罗地亚', si: '斯洛文尼亚',
            rs: '塞尔维亚', gr: '希腊', pt: '葡萄牙',
            lt: '立陶宛', lv: '拉脱维亚', ee: '爱沙尼亚', is: '冰岛',
            mt: '马耳他', lu: '卢森堡', cy: '塞浦路斯', md: '摩尔多瓦',
            hk: '香港', mo: '澳门', tw: '台湾', jp: '日本', kr: '韩国',
            sg: '新加坡', my: '马来西亚', id: '印度尼西亚', ph: '菲律宾',
            th: '泰国', vn: '越南',
            in: '印度', pk: '巴基斯坦', bd: '孟加拉国', lk: '斯里兰卡', np: '尼泊尔',
            ru: '俄罗斯', ua: '乌克兰', by: '白俄罗斯', kz: '哈萨克斯坦',
            uz: '乌兹别克斯坦', az: '阿塞拜疆', am: '亚美尼亚', ge: '格鲁吉亚',
            kg: '吉尔吉斯斯坦', tj: '塔吉克斯坦', tm: '土库曼斯坦',
            tr: '土耳其', il: '以色列', sa: '沙特阿拉伯', ae: '阿联酋',
            qa: '卡塔尔', kw: '科威特', bh: '巴林', om: '阿曼',
            jo: '约旦', lb: '黎巴嫩', eg: '埃及',
            za: '南非', ng: '尼日利亚', ke: '肯尼亚', gh: '加纳',
            tz: '坦桑尼亚', ug: '乌干达', zw: '津巴布韦', ci: '科特迪瓦',
            sn: '塞内加尔', cm: '喀麦隆', dz: '阿尔及利亚', ma: '摩洛哥', tn: '突尼斯',
            br: '巴西', mx: '墨西哥', ar: '阿根廷', cl: '智利', co: '哥伦比亚',
            pe: '秘鲁', uy: '乌拉圭', py: '巴拉圭', bo: '玻利维亚',
            ve: '委内瑞拉', ec: '厄瓜多尔',
            cr: '哥斯达黎加', pa: '巴拿马', gt: '危地马拉', sv: '萨尔瓦多',
            hn: '洪都拉斯', ni: '尼加拉瓜', do: '多米尼加共和国',
        },
    },
};

export let uiLang = detectInitialLang();
document.documentElement.lang = (uiLang === 'zh' ? 'zh-CN' : 'en');

function detectInitialLang() {
    try {
        const saved = localStorage.getItem('cs_ui_lang');
        if (saved === 'zh' || saved === 'en') return saved;
    } catch (e) {}
    const nav = ((navigator.language || navigator.userLanguage || 'en') + '').toLowerCase();
    return nav.startsWith('zh') ? 'zh' : 'en';
}

export function T(k, ...args) {
    const src = I18N[uiLang] && I18N[uiLang][k] !== undefined ? I18N[uiLang][k] : I18N.en[k];
    if (typeof src === 'function') return src(...args);
    return src === undefined ? k : src;
}

export function TL(lang) {
    if (!lang) return '';
    if (uiLang === 'zh') return I18N.zh.langs[lang] || lang;
    return lang;
}

export function TC(code) {
    if (!code) return '';
    const dict = (I18N[uiLang] && I18N[uiLang].countries) || I18N.en.countries || {};
    return dict[code] || I18N.en.countries[code] || code.toUpperCase();
}

// Setting the language: persists, flips <html lang>, re-applies static
// DOM labels, and dispatches a render event so every view updates.
export function setUILang(l) {
    if (l !== 'en' && l !== 'zh') return;
    uiLang = l;
    try { localStorage.setItem('cs_ui_lang', l); } catch (e) {}
    document.documentElement.lang = (l === 'zh' ? 'zh-CN' : 'en');
    applyStaticLabels();
    document.dispatchEvent(new CustomEvent('cs:render'));
}

// Swap innerText on the elements that live outside the render loop
// (header, page title, loading text).
export function applyStaticLabels() {
    document.title = T('pageTitle');
    const titleEl = document.getElementById('siteTitle');
    if (titleEl) titleEl.textContent = T('siteTitle');
    const archTitle = document.getElementById('archiveTitle');
    if (archTitle) archTitle.textContent = T('archiveTitle');
    const loadingText = document.getElementById('loadingText');
    if (loadingText) loadingText.textContent = T('loading');
    const fab = document.getElementById('insightsFab');
    if (fab) {
        const tip = T('insightsTooltip');
        fab.setAttribute('aria-label', tip);
        fab.setAttribute('title', tip);
    }
    const expFab = document.getElementById('exportFab');
    if (expFab) {
        const tip = T('exportTooltip');
        expFab.setAttribute('aria-label', tip);
        expFab.setAttribute('title', tip);
    }
    // subLine depends on live state — handled by applyStaticLabelsWithApp()
}
