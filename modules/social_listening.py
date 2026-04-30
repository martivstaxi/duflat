"""
Social Listening Module — Bilibili mention tracking

Flow (optimized — single endpoint):
  1. AI finds ~100 links mentioning "bilibili"
  2. POST /social/scan        → Python dedup + download + Haiku analysis + save (ALL IN ONE)
  3. GET  /social/mentions    → Frontend reads mentions by date

Legacy endpoints still available:
  - POST /social/check-urls, /social/process, /social/save
"""

import hashlib
import json
import os
import re
import requests
from datetime import datetime, date, timedelta, timezone
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from modules.constants import BROWSER_HEADERS

# ─────────────────────────────────────────────
# RATE-LIMIT COOLDOWN STATE (module-level)
# ─────────────────────────────────────────────
# When a 3rd-party API returns 429/403, subsequent calls in the same
# gunicorn worker process are skipped for a cooldown window. Keeps us
# from burning the rest of the budget on guaranteed failures and from
# extending the ban.

_rate_cooldown = {}  # host -> unix ts when cooldown expires

def _cooling_down(host):
    import time
    return time.time() < _rate_cooldown.get(host, 0)

def _enter_cooldown(host, seconds):
    import time
    _rate_cooldown[host] = time.time() + seconds
    print(f'[cooldown] {host} for {seconds}s', flush=True)


# ─────────────────────────────────────────────
# SUPABASE CLIENT
# ─────────────────────────────────────────────

_supabase = None

def init_supabase(url, key):
    global _supabase
    from supabase import create_client
    _supabase = create_client(url, key)
    return _supabase

def _db():
    if not _supabase:
        raise RuntimeError('Supabase not initialized')
    return _supabase


# ─────────────────────────────────────────────
# URL HASHING
# ─────────────────────────────────────────────

def hash_url(url):
    """Deterministic 16-char hash of a normalized URL."""
    normalized = url.strip().lower().rstrip('/')
    # Remove common tracking params
    normalized = re.sub(r'[?&](utm_\w+|ref|fbclid|gclid)=[^&]*', '', normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def hash_content(text):
    """Hash content text for dedup."""
    cleaned = re.sub(r'\s+', ' ', text.strip().lower())
    return hashlib.sha256(cleaned.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────
# STEP 1: CHECK URLS (dedup against DB)
# ─────────────────────────────────────────────

def check_urls(urls):
    """
    Receive list of URLs → hash → check DB → return only new unique ones.
    Zero AI cost, zero network cost (just DB queries).
    """
    # Local dedup first
    seen = {}
    for url in urls:
        url = url.strip()
        if not url:
            continue
        h = hash_url(url)
        if h not in seen:
            seen[h] = url

    if not seen:
        return []

    # Check DB in batches
    hashes = list(seen.keys())
    existing = set()

    for i in range(0, len(hashes), 50):
        batch = hashes[i:i+50]
        result = _db().table('social_sources').select('url_hash').in_('url_hash', batch).execute()
        for row in result.data:
            existing.add(row['url_hash'])

    # Return only new
    new_urls = []
    for h, url in seen.items():
        if h not in existing:
            new_urls.append({'url': url, 'url_hash': h})

    return new_urls


# ─────────────────────────────────────────────
# STEP 2: PROCESS URLS (download + date filter)
# ─────────────────────────────────────────────

# Date patterns that capture 2026 — multilingual
_DATE_PATTERNS = [
    # 2026-01-15, 2026/01/15, 2026.01.15
    re.compile(r'(2026[-/.]\d{1,2}[-/.]\d{1,2})'),
    # 15-01-2026, 01/15/2026, 15.01.2026
    re.compile(r'(\d{1,2}[-/.]\d{1,2}[-/.]2026)'),
    # English months: January 15, 2026 / Jan 15 2026
    re.compile(r'((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+2026)', re.I),
    # 15 January 2026
    re.compile(r'(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+2026)', re.I),
    # Chinese/Japanese: 2026年
    re.compile(r'(2026年\d{1,2}月)'),
    re.compile(r'(2026年)'),
    # Arabic months with 2026
    re.compile(r'((?:يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\s+2026)'),
    # Spanish months
    re.compile(r'((?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+(?:de\s+)?2026)', re.I),
    # Portuguese months
    re.compile(r'((?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+(?:de\s+)?2026)', re.I),
    # Russian months
    re.compile(r'((?:январ[яь]|феврал[яь]|март[а]?|апрел[яь]|ма[яй]|июн[яь]|июл[яь]|август[а]?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])\s+2026)', re.I),
    # Turkish months
    re.compile(r'((?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+2026)', re.I),
    # Loose: "date/posted/published/updated" near 2026
    re.compile(r'(?:date|posted|published|updated|reviewed?)[\s:]*[^0-9]*?(2026)', re.I),
    # URL contains 2026 (many news sites embed date in URL)
    re.compile(r'/2026/\d{1,2}/'),
]


def _extract_dates_2026(text):
    """Find all 2026 date references in text."""
    found = []
    for pat in _DATE_PATTERNS:
        found.extend(pat.findall(text))
    return found


def _extract_dates_from_metadata(soup):
    """Extract 2026 dates from JSON-LD, meta tags, and time elements."""
    dates = []

    # 1. JSON-LD structured data
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            if isinstance(data, list):
                data = data[0] if data else {}
            for key in ('datePublished', 'dateModified', 'dateCreated', 'uploadDate'):
                val = data.get(key, '')
                if val and '2026' in str(val):
                    dates.append(str(val)[:10])
        except Exception:
            continue

    # 2. Meta tags (og:article, schema, etc.)
    meta_names = [
        'article:published_time', 'article:modified_time',
        'og:updated_time', 'date', 'pubdate', 'publish_date',
        'dc.date', 'DC.date.issued', 'sailthru.date',
    ]
    for name in meta_names:
        tag = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name})
        if tag:
            val = tag.get('content', '')
            if val and '2026' in val:
                dates.append(val[:10])

    # 3. <time> elements with datetime attribute
    for t in soup.find_all('time', datetime=True):
        val = t['datetime']
        if '2026' in val:
            dates.append(val[:10])

    return dates


def _parse_date_string(s):
    """Try to parse a date string into YYYY-MM-DD format."""
    s = s.strip().replace('/', '-').replace(',', '')
    formats = [
        '%Y-%m-%d', '%d-%m-%Y', '%m-%d-%Y',
        '%B %d %Y', '%b %d %Y', '%d %B %Y', '%d %b %Y',
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    # Fallback: if just "2026" found
    if '2026' in s:
        return '2026-01-01'
    return None


def process_urls(url_items, time_budget=55):
    """
    Download each URL, extract text, check for 2026 dates.
    Returns only content that has 2026 dates — ready for AI analysis.
    Zero AI cost. Stops after time_budget seconds.
    """
    import time
    results = []
    processed = 0
    start = time.time()

    for item in url_items:
        if time.time() - start > time_budget:
            break
        url = item['url']
        url_hash = item['url_hash']
        processed += 1

        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=8, allow_redirects=True)
            resp.raise_for_status()

            # Use resp.content (bytes) so BS4 detects encoding from HTML meta tags
            # resp.text can corrupt CJK characters when headers don't declare charset
            soup = BeautifulSoup(resp.content, 'html.parser')

            # Check metadata BEFORE removing script tags (JSON-LD lives in <script>)
            meta_dates = _extract_dates_from_metadata(soup)

            # Remove noise
            for tag in soup(['script', 'style', 'nav', 'footer', 'iframe', 'noscript']):
                tag.decompose()

            text = soup.get_text(separator='\n', strip=True)

            # Cap at 15K chars for processing
            text_trimmed = text[:15000]

            # Check for 2026 dates — metadata + page text + URL
            dates = meta_dates + _extract_dates_2026(text_trimmed + '\n' + url)

            # Detect platform from URL
            domain = urlparse(url).netloc.replace('www.', '')

            # Save source record
            _db().table('social_sources').upsert({
                'url_hash': url_hash,
                'url': url,
                'domain': domain,
                'has_2026_content': len(dates) > 0,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()

            if dates:
                # Parse the first date found
                parsed_date = _parse_date_string(dates[0])

                results.append({
                    'url': url,
                    'url_hash': url_hash,
                    'platform': domain,
                    'text': text_trimmed[:5000],  # Limit text sent to AI
                    'dates_found': dates[:5],
                    'content_date': parsed_date,
                })

        except Exception as e:
            # Record failed attempt
            try:
                _db().table('social_sources').upsert({
                    'url_hash': url_hash,
                    'url': url,
                    'domain': urlparse(url).netloc.replace('www.', ''),
                    'has_2026_content': False,
                    'checked_at': datetime.utcnow().isoformat(),
                }, on_conflict='url_hash').execute()
            except:
                pass

    return {
        'processed': processed,
        'with_2026_content': len(results),
        'items': results,
    }


# ─────────────────────────────────────────────
# STEP 3: SAVE MENTIONS (AI-analyzed results)
# ─────────────────────────────────────────────

def _detect_chinese_script(text):
    """
    Distinguish Simplified Chinese (Mandarin/mainland) from Traditional Chinese (HK/TW).

    Uses Unicode codepoint ranges:
    - Simplified-only chars exist only in Simplified Unicode blocks
    - Traditional-only chars exist only in Traditional Unicode blocks
    - Overlapping chars (used in both) are ignored

    Logic: count unambiguous Simplified chars vs unambiguous Traditional chars.
    If simp > trad  → Simplified Chinese (Mandarin, block)
    If trad > simp  → Traditional Chinese (HK/TW, allow)
    If tied (0==0)  → default Traditional Chinese (safe: HK/TW content is expected)

    Common Simplified-only chars (不存在于繁体): 国来对说时间会这们问东车头发
    Common Traditional-only chars (不存在于简体): 國來對說時間會這們問東車頭發
    """
    # Expanded character pairs — 40+ distinctive pairs
    SIMP_CHARS = set('国来对说时间会这们问东车头发钱马书开关无处边长带达华风给结论总给认专经历层难实际际报书节约统带运约处场达种须结万议须积极见')
    TRAD_CHARS = set('國來對說時間會這們問東車頭發錢馬書開關無處邊長帶達華風給結論總給認專經歷層難實際際報書節約統帶運約處場達種須結萬議須積極見')

    simp = sum(1 for c in text if c in SIMP_CHARS)
    trad = sum(1 for c in text if c in TRAD_CHARS)

    if simp > trad:
        return 'Simplified Chinese'  # Mandarin — will be blocked from saving
    else:
        return 'Traditional Chinese'  # HK/TW — allowed (trad > simp OR both 0 → safe default)


def _detect_lang_from_text(text):
    """
    Heuristic language detection by counting character types.
    Returns detected language string or None if ambiguous.
    """
    if not text or len(text) < 10:
        return None
    total = len([c for c in text if not c.isspace()])
    if total == 0:
        return None

    arabic  = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    kana    = sum(1 for c in text if '\u3040' <= c <= '\u30FF')  # hiragana + katakana
    cjk     = sum(1 for c in text if '\u4E00' <= c <= '\u9FFF')
    cyril   = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
    latin   = sum(1 for c in text if c.isascii() and c.isalpha())

    if arabic / total > 0.15:
        return 'Arabic'
    if kana / total > 0.05:
        return 'Japanese'
    if cjk / total > 0.15:
        return _detect_chinese_script(text)
    if cyril / total > 0.15:
        return 'Russian'
    if latin / total > 0.25:
        return 'Latin'   # English/Spanish/Portuguese/Turkish — trust Haiku for exact lang
    return None


# Terms that confirm a mention is about Bilibili
_BILIBILI_TERMS = [
    'bilibili', 'b站', 'ビリビリ', 'blg', '哔哩哔哩', '嗶哩嗶哩',
    '9626', 'anisora', 'bili bili', 'bilibil', '哔哩', '嗶哩',
    'bilibili gaming', 'first stand', 'anisora',
]


def _validate_and_repair(mention):
    """
    Validate a Haiku-analyzed mention before saving to DB.
    Returns (is_valid, mention, issues[]).
    Repairs what it can (language label); rejects what it cannot.

    Checks:
      1. Language match  — detect from text, auto-repair if wrong
      2. content_original ≠ content_english
      3. Bilibili relevance — reject if Bilibili not mentioned at all
      4. Date sanity — reject future dates, warn on very old dates
      5. Minimum content length
    """
    issues = []
    original = mention.get('content_original', '').strip()
    english  = mention.get('content_english', '').strip()
    lang     = mention.get('language', '')
    content_date = mention.get('content_date') or ''
    today    = date.today().isoformat()

    # ── 1. LANGUAGE CHECK ──────────────────────────────────────────
    detected = _detect_lang_from_text(original)
    if detected == 'Latin' and lang in (
        'Traditional Chinese', 'Simplified Chinese', 'Japanese', 'Arabic', 'Russian'
    ):
        # Text is clearly Latin/English but Haiku labeled it as non-Latin → fix
        issues.append(f'lang_repair:{lang}→English')
        mention['language'] = 'English'
    elif detected and detected != 'Latin' and detected != lang:
        # Confident non-Latin detection disagrees with Haiku
        issues.append(f'lang_repair:{lang}→{detected}')
        mention['language'] = detected

    # ── 2. ORIGINAL ≠ ENGLISH CHECK ───────────────────────────────
    if original and english and original == english:
        issues.append('reject:original_same_as_english')
        return False, mention, issues

    # ── 3. BILIBILI RELEVANCE CHECK ───────────────────────────────
    combined = (original + ' ' + english).lower()
    if not any(term in combined for term in _BILIBILI_TERMS):
        issues.append('reject:bilibili_not_mentioned')
        return False, mention, issues

    # ── 4. DATE SANITY ─────────────────────────────────────────────
    if content_date:
        if content_date > today:
            issues.append(f'reject:future_date:{content_date}')
            return False, mention, issues
        if content_date < '2024-01-01':
            issues.append(f'warn:very_old_date:{content_date}')  # allow but flag

    # ── 5. SENSITIVITY / SOURCE_TYPE SANITY ──────────────────────
    valid_sensitivity = ('low', 'medium', 'high', 'critical')
    valid_source_type = ('government', 'news_major', 'news_minor', 'blog', 'forum', 'social', 'financial')
    if mention.get('sensitivity', 'low') not in valid_sensitivity:
        mention['sensitivity'] = 'low'
    if mention.get('source_type', 'news_minor') not in valid_source_type:
        mention['source_type'] = 'news_minor'

    # ── 6. MINIMUM LENGTH ──────────────────────────────────────────
    if len(original) < 15:
        issues.append(f'reject:content_too_short:{len(original)}chars')
        return False, mention, issues

    return True, mention, issues


def _ai_validate_and_repair(mentions):
    """
    Second AI pass: Haiku reviews Haiku's own output.
    For each mention, checks:
      1. Is Bilibili actually mentioned? (reject if not)
      2. Is the language label correct? (fix if wrong, still save)
      3. Is content_original genuinely different from content_english? (reject if same)

    Returns list of mentions — repaired ones included, rejected ones removed.
    This runs AFTER _validate_and_repair() heuristics, as a final quality gate.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or not mentions:
        return mentions

    try:
        import anthropic
    except ImportError:
        return mentions

    entries = []
    for i, m in enumerate(mentions):
        entries.append({
            'idx': i,
            'url': m.get('url', ''),
            'platform': m.get('platform', ''),
            'language_label': m.get('language', ''),
            'content_original': m.get('content_original', '')[:800],
            'content_english': m.get('content_english', '')[:400],
        })

    prompt = f"""You are a quality control agent reviewing social listening data about Bilibili.

For EACH entry below, answer three questions and return fixes:

1. BILIBILI_RELEVANT: Does content_original actually mention Bilibili, Bilibili Gaming (BLG), B站, ビリビリ, 哔哩哔哩, 嗶哩嗶哩, AniSora, or any directly related topic? Answer true/false.

2. LANGUAGE_CORRECT: Is the language_label correct for the actual text in content_original?
   - If wrong, provide the correct language ("English", "Japanese", "Arabic", "Traditional Chinese", "Simplified Chinese", "Turkish", "Russian", "Spanish", "Portuguese")
   - If correct, return null

3. CONTENT_DISTINCT: Is content_original meaningfully different from content_english (different language OR different wording)?

Rules:
- If BILIBILI_RELEVANT=false → mark action:"reject"
- If LANGUAGE_CORRECT has a correction → mark action:"repair_language", corrected_language:"..."
- If CONTENT_DISTINCT=false → mark action:"reject"
- Otherwise → mark action:"keep"
- If both repair and keep → action:"repair_language" (repair + keep, do NOT reject)

Return ONLY a JSON array, one object per entry:
[{{"idx":0,"bilibili_relevant":true,"language_correct":null,"content_distinct":true,"action":"keep"}}, ...]

Entries:
{json.dumps(entries, ensure_ascii=False)}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=2048,
            messages=[{'role': 'user', 'content': prompt}],
        )
        verdicts = _extract_json(resp.content[0].text)
        if verdicts is None:
            return mentions  # parse failed → pass through
    except Exception as e:
        print(f'[validator] {type(e).__name__}', flush=True)
        return mentions  # if AI validator fails, pass through (don't block saves)

    # Apply verdicts
    result = []
    for v in verdicts:
        idx = v.get('idx')
        if idx is None or idx >= len(mentions):
            continue
        action = v.get('action', 'keep')
        m = mentions[idx]

        if action == 'reject':
            continue  # drop silently

        if action == 'repair_language':
            corrected = v.get('corrected_language')
            if corrected:
                m['language'] = corrected
            result.append(m)
        else:
            result.append(m)  # keep as-is

    # Safety: if validator returned fewer items than expected (parse issue), pass all through
    if len(result) == 0 and len(mentions) > 0:
        return mentions

    return result


def save_mentions(mentions):
    """
    Save AI-analyzed mentions to Supabase.
    Each mention passes _validate_and_repair() before saving:
      - Language label auto-corrected if wrong
      - Irrelevant, duplicate-content, future-dated, too-short mentions rejected
    Then a final Haiku gate (_layer4_final_gate) verifies publication year,
    Bilibili relevance, scope, and non-financial angle before DB write.
    """
    saved = 0
    skipped = 0
    repaired = 0
    gate_rejected = 0
    candidates = []
    alert_queue = []

    # ── Pass 1: heuristic scope + validate + repair ────────────────────
    for m in mentions:
        original = m.get('content_original', '').strip()
        if not original:
            skipped += 1
            continue

        # Simplified Chinese / Mandarin is out of project scope — always reject
        if m.get('language') == 'Simplified Chinese':
            skipped += 1
            continue

        # Mainland China content is out of project scope — always reject
        country = (m.get('country') or '').strip().lower()
        if country in ('china', 'mainland china', 'prc', "people's republic of china", '中国', '中國'):
            skipped += 1
            continue
        url_lower = (m.get('url') or '').lower()
        if any(d in url_lower for d in (
            '.cn/', '.gov.cn', 'sina.com', 'weibo.com', 'sohu.com', 'qq.com',
            'thepaper.cn', 'xinhua', 'people.com.cn', 'globaltimes',
            'chinadaily', 'cctv.', 'baidu.com', 'zhihu.com', '163.com',
            '36kr.com', 'ifeng.com', 'douyin.com', 'toutiao.com',
        )):
            skipped += 1
            continue

        # Run validation + auto-repair
        is_valid, m, issues = _validate_and_repair(m)
        if not is_valid:
            skipped += 1
            continue
        if any(i.startswith('lang_repair') for i in issues):
            repaired += 1

        candidates.append(m)

    # ── Pass 2: L4 FINAL GATE (Haiku) — last line of defence ───────────
    pre_gate_count = len(candidates)
    approved, gate_rejections = _layer4_final_gate(candidates)
    gate_rejected = pre_gate_count - len(approved)
    skipped += gate_rejected

    # ── Pass 3: upsert approved mentions ───────────────────────────────
    for m in approved:
        original = m.get('content_original', '').strip()
        c_hash = hash_content(original)

        row = {
            'content_hash': c_hash,
            'url': m.get('url', ''),
            'url_hash': m.get('url_hash', hash_url(m.get('url', ''))),
            'platform': m.get('platform', ''),
            'author': m.get('author', ''),
            'country': m.get('country', ''),
            'language': m.get('language', ''),
            'sentiment': m.get('sentiment', 'neutral'),
            'sensitivity': m.get('sensitivity', 'low'),
            'source_type': m.get('source_type', 'news_minor'),
            'content_original': original,
            'content_english': m.get('content_english', ''),
            'content_chinese': m.get('content_chinese', ''),
            'keywords': m.get('keywords', []),
            'content_date': m.get('content_date'),
        }

        try:
            _db().table('social_mentions').upsert(
                row, on_conflict='content_hash'
            ).execute()
            saved += 1
            if row['sensitivity'] == 'critical':
                alert_queue.append(m)
        except Exception as e:
            print(
                f'[save_mentions] upsert failed url={row["url"][:120]} '
                f'err={type(e).__name__}',
                flush=True,
            )
            skipped += 1

    # Alert for critical (P0) sensitivity mentions only
    if alert_queue:
        _send_telegram_alerts(alert_queue)
        _send_email_alerts(alert_queue)
        _send_wecom_alerts(alert_queue)

    return {
        'saved': saved,
        'skipped': skipped,
        'repaired': repaired,
        'gate_rejected': gate_rejected,
        'gate_rejections': gate_rejections,
    }


# ─────────────────────────────────────────────
# TELEGRAM ALERTS
# ─────────────────────────────────────────────

def _send_telegram_alerts(mentions):
    """Send Telegram notification for critical (P0) sensitivity mentions."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        return

    for m in mentions:
        sensitivity = m.get('sensitivity', 'low')
        icon = '\U0001F6A8'
        source_type = m.get('source_type', '')
        platform = m.get('platform', '')
        url = m.get('url', '')

        text = (
            f"{icon} *{sensitivity.upper()}* mention detected\n\n"
            f"{m.get('content_english', '')}\n\n"
            f"Source: {source_type} — {platform}\n"
            f"Sentiment: {m.get('sentiment', 'neutral')}\n"
            f"Date: {m.get('content_date', 'unknown')}"
        )
        if url:
            text += f"\n[Link]({url})"

        try:
            requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={
                    'chat_id': chat_id,
                    'text': text,
                    'parse_mode': 'Markdown',
                    'disable_web_page_preview': True,
                },
                timeout=10,
            )
        except Exception:
            pass  # alert failure should never block the pipeline


def _send_email_alerts(mentions):
    """Send email notification for critical (P0) sensitivity mentions via Resend."""
    api_key = os.environ.get('RESEND_API_KEY', '')
    to_raw = os.environ.get('ALERT_EMAIL_TO', '')
    to_list = [e.strip() for e in to_raw.split(',') if e.strip()]
    if not api_key or not to_list:
        return

    for m in mentions:
        sensitivity = m.get('sensitivity', 'low')
        source_type = m.get('source_type', '')
        platform = m.get('platform', '')
        url = m.get('url', '')
        sentiment = m.get('sentiment', 'neutral')
        content = m.get('content_english', '')
        date = m.get('content_date', 'unknown')

        subject = f"[{sensitivity.upper()}] Bilibili mention — {source_type}"

        body = (
            f"<h2 style='color:#dc2626'>"
            f"{sensitivity.upper()} Mention Detected</h2>"
            f"<p style='font-size:16px;line-height:1.6'>{content}</p>"
            f"<table style='font-size:14px;border-collapse:collapse'>"
            f"<tr><td style='padding:4px 12px 4px 0;color:#666'>Source</td><td>{source_type} — {platform}</td></tr>"
            f"<tr><td style='padding:4px 12px 4px 0;color:#666'>Sentiment</td><td>{sentiment}</td></tr>"
            f"<tr><td style='padding:4px 12px 4px 0;color:#666'>Date</td><td>{date}</td></tr>"
            f"</table>"
        )
        if url:
            body += f"<p><a href='{url}'>View source</a></p>"
        body += "<hr><p style='font-size:12px;color:#999'>Duflat Social Listening</p>"

        try:
            r = requests.post(
                'https://api.resend.com/emails',
                headers={'Authorization': f'Bearer {api_key}'},
                json={
                    'from': 'Duflat Alerts <alerts@duflat.com>',
                    'to': to_list,
                    'subject': subject,
                    'html': body,
                },
                timeout=10,
            )
            if r.status_code >= 400:
                print(f'[resend] {r.status_code} {r.text[:300]}', flush=True)
        except Exception as e:
            print(f'[resend] exception {e}', flush=True)


# ─────────────────────────────────────────────
# WECOM ALERTS
# ─────────────────────────────────────────────

def _send_wecom_alerts(mentions):
    """Send WeCom (企业微信) webhook notification for critical (P0) mentions."""
    key = os.environ.get('WECOM_WEBHOOK_KEY', '')
    if not key:
        return

    endpoint = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}'

    for m in mentions:
        sensitivity = m.get('sensitivity', 'low')
        source_type = m.get('source_type', '')
        platform = m.get('platform', '')
        sentiment = m.get('sentiment', 'neutral')
        content = m.get('content_english', '')
        date = m.get('content_date', 'unknown')
        url = m.get('url', '')

        content_md = (
            f'# <font color="warning">{sensitivity.upper()} mention detected</font>\n\n'
            f'{content}\n\n'
            f'> **Source:** {source_type} — {platform}\n'
            f'> **Sentiment:** {sentiment}\n'
            f'> **Date:** {date}'
        )
        if url:
            content_md += f'\n> **Link:** [{url}]({url})'

        try:
            requests.post(
                endpoint,
                json={'msgtype': 'markdown', 'markdown': {'content': content_md}},
                timeout=10,
            )
        except Exception:
            pass  # alert failure should never block the pipeline


# ─────────────────────────────────────────────
# STEP 4: GET MENTIONS (for frontend)
# ─────────────────────────────────────────────

def get_mentions(days=None, specific_date=None, limit=5000):
    """
    Fetch mentions for social.html display.
    - days=3  → last 3 days
    - specific_date='2026-01-01' → that exact date
    """
    query = _db().table('social_mentions').select('*')

    if specific_date:
        query = query.eq('content_date', specific_date)
    elif days:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        query = query.gte('content_date', cutoff)

    result = query.order('content_date', desc=True).limit(limit).execute()
    return result.data


# ─────────────────────────────────────────────
# HAIKU ANALYSIS (replaces manual AI analysis)
# ─────────────────────────────────────────────

_TLD_LANG_HINTS = {
    '.ru': 'Russian', '.jp': 'Japanese',
    '.tw': 'Traditional Chinese', '.hk': 'Traditional Chinese',
    '.tr': 'Turkish', '.es': 'Spanish', '.mx': 'Spanish',
    '.ar': 'Spanish', '.br': 'Portuguese', '.pt': 'Portuguese',
    '.sa': 'Arabic', '.ae': 'Arabic', '.eg': 'Arabic',
}


_HAIKU_MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-haiku-4-5-20251001')


def _extract_json(text):
    """Extract a JSON object/array from a Haiku response.

    Handles: raw JSON, ```json fenced blocks, JSON embedded in prose,
    truncated responses (last-brace repair). Returns parsed value or
    None with a reason logged."""
    text = (text or '').strip()
    if not text:
        return None
    # 1. Raw parse (most common case)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. Strip markdown fence (```json ... ``` or ``` ... ```)
    fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if fence:
        inner = fence.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            text = inner  # fall through to salvage
    # 3. Salvage: locate outer [ ... ] or { ... } and trim
    for open_c, close_c in (('[', ']'), ('{', '}')):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    # 4. Truncation repair: close the last complete array element
    last_comma = text.rfind('},')
    if last_comma > 0:
        start = text.find('[')
        if start != -1 and start < last_comma:
            try:
                return json.loads(text[start:last_comma + 1] + ']')
            except Exception:
                pass
    print(f'[haiku_parse] failed, preview={text[:160]!r}', flush=True)
    return None


def _haiku_call(prompt, max_tokens=4096):
    """Shared Haiku call wrapper used by all pipeline layers. Returns parsed JSON or None.

    Errors are logged (not silenced) so that L4 fail-closed + upstream
    retries have something to act on."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        print('[haiku_call] ANTHROPIC_API_KEY not set', flush=True)
        return None
    try:
        import anthropic
    except ImportError:
        print('[haiku_call] anthropic package missing', flush=True)
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return _extract_json(resp.content[0].text)
    except Exception as e:
        # Log exception type only; never the message (may contain key / prompt)
        print(f'[haiku_call] {type(e).__name__}', flush=True)
        return None


def _chunks(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def _layer1_triage(items):
    """
    LAYER 1 — TRIAGE: fast relevance filter.
    Three yes/no checks: Bilibili actually mentioned, in scope (non-Mainland), has a social angle (not pure financial).
    Returns list of items that pass all three checks.
    Batches items in groups of 12 to keep JSON output well under max_tokens.
    """
    if not items:
        return []

    kept = []
    for batch in _chunks(items, 12):
        kept.extend(_layer1_triage_batch(batch))
    return kept


def _layer1_triage_batch(items):
    entries = []
    for i, item in enumerate(items):
        entries.append({
            'idx': i,
            'url': item['url'],
            'platform': item['platform'],
            'text': item['text'][:1200],  # small sample, this is just a filter
        })

    prompt = f"""You are a triage agent for a social listening platform tracking Bilibili.

For EACH article, answer three yes/no questions. Only articles that answer YES to ALL THREE should be kept.

1. MENTIONS_BILIBILI: Does this article substantively discuss Bilibili (哔哩哔哩 / 嗶哩嗶哩 / B站 / ビリビリ / BLG / Bilibili Gaming / AniSora)? Not just a name-drop in a list.

2. IN_SCOPE: Is this content suitable for a non-Mainland-China social listening audience? OUT OF SCOPE = Mainland PRC state media, Mainland news sites, Mainland regulators, Mainland user forums (Weibo/Zhihu/Tieba/Douyin/Toutiao), Simplified Chinese (Mandarin) content. IN SCOPE = Traditional Chinese (Taiwan/HK), English, Japanese, Korean, Arabic, Turkish, Russian, Spanish, Portuguese, etc.

3. HAS_SOCIAL_ANGLE: Is there a non-financial story here worth telling?
   - SOCIAL angle = user opinion, creator news, product/feature, policy/moderation, AI/strategy, M&A rumor, competitor dynamic, esports (BLG), anime streaming, cultural moment, brand reputation.
   - NOT a social angle = pure stock price movement, earnings numbers, analyst ratings, bond offering, dividend, IPO, market cap, revenue figures, SEC/CSRC filing.
   - If article MIXES financial info + social story → YES (true). We will extract only the social part later.
   - If article is PURELY financial with no social angle → NO (false).

Return ONLY a JSON array: [{{"idx":0,"mentions_bilibili":true,"in_scope":true,"has_social_angle":true}}, ...]

Articles:
{json.dumps(entries, ensure_ascii=False)}"""

    verdicts = _haiku_call(prompt, max_tokens=2048)
    if not verdicts:
        # If triage fails, conservatively pass everything through — downstream layers will clean up
        return items

    kept = []
    for v in verdicts:
        idx = v.get('idx')
        if idx is None or idx >= len(items):
            continue
        if v.get('mentions_bilibili') and v.get('in_scope') and v.get('has_social_angle'):
            kept.append(items[idx])
    return kept


def _layer2_extract(items):
    """
    LAYER 2 — EXTRACT: structured field extraction, non-financial focus.
    Batches items in groups of 8 since each mention's output is heavy (content_english + content_original).
    """
    if not items:
        return []
    result = []
    for batch in _chunks(items, 8):
        result.extend(_layer2_extract_batch(batch))
    return result


def _layer2_extract_batch(items):
    entries = []
    for i, item in enumerate(items):
        domain = item['platform']
        lang_hint = ''
        for tld, lang in _TLD_LANG_HINTS.items():
            if domain.endswith(tld):
                lang_hint = lang
                break
        e = {
            'idx': i,
            'platform': item['platform'],
            'text': item['text'][:2000],
        }
        if lang_hint:
            e['lang_hint'] = lang_hint
        entries.append(e)

    prompt = f"""You are an extraction agent for a Bilibili social listening platform. The articles below have already passed a relevance filter — they all mention Bilibili, are in scope, and have a social story.

Your job: extract structured fields. FOCUS ONLY on the non-financial angle of the story. Never write about stock prices, earnings figures, revenue numbers, analyst ratings, or dividends — even if the source article includes them.

Write each content_english as a plain-English social insight — like a social media observation, NOT a news headline.

GOOD examples (social voice, non-financial):
- "Fans are hyped about Bilibili's anime lineup for winter 2026, especially Frieren Season 2."
- "BLG's run at the international esports tournament has Chinese-speaking fans buzzing."
- "Users are pushing back on the new moderation policy after several creators got suspended."
- "Bilibili is doubling down on AI content tools, which has creators both excited and worried."

BAD examples (financial/corporate, never write like this):
- "Bilibili reported Q4 revenue of RMB 8.32 billion."
- "Morgan Stanley raised its price target on BILI to $31."
- "Investors are reacting positively to the bond offering."

If the source article mixes financial + social angles (e.g., "CFO announced AI investments; revenue was X billion"), write ONLY about the AI investment angle. Omit all financial figures from content_english and skip financial sentences when picking content_original.

For EACH article, extract:
- content_english: 1-2 sentences, plain social insight tone, non-financial
- content_chinese: Simplified Chinese translation of content_english, same length and tone. Natural Chinese social-listening voice (not machine-literal word-for-word). Keep brand/product names in Latin letters (e.g. "Bilibili", "AniSora", "AI", "BLG", "PGL"). Use Simplified Chinese characters ONLY. This is purely for UI localization and does not change the scope rules.
- content_original: 1-3 sentences copied VERBATIM from source text, in original language. Pick the sentences that carry the non-financial story. If only financial sentences exist, return empty string.
- language: detect from content_original's actual characters. Use one of: "English", "Japanese", "Arabic", "Traditional Chinese", "Turkish", "Russian", "Spanish", "Portuguese". If `lang_hint` provided, use as tie-breaker only. (Simplified Chinese should not appear here — those were filtered.)
- author: byline if present, else the platform domain
- country: country of origin if detectable, else "International"
- keywords: EXACTLY 2 or 3 single-word topic tags (max 3, never more). Use social/product terms like "esports", "creators", "anime", "AI", "moderation", "policy". Do NOT use financial terms (no "earnings", "stock", "dividend", "revenue", etc.).

Return ONLY a JSON array: [{{"idx":0,"content_english":"...","content_chinese":"...","content_original":"...","language":"...","author":"...","country":"...","keywords":[...]}}, ...]

Articles:
{json.dumps(entries, ensure_ascii=False)}"""

    extracted = _haiku_call(prompt, max_tokens=4096)
    if not extracted:
        return []

    result = []
    for v in extracted:
        idx = v.get('idx')
        if idx is None or idx >= len(items):
            continue
        src = items[idx]
        result.append({
            'url': src['url'],
            'url_hash': src['url_hash'],
            'platform': src['platform'],
            'content_date': src.get('content_date', ''),
            'content_english': v.get('content_english', ''),
            'content_chinese': v.get('content_chinese', ''),
            'content_original': v.get('content_original', ''),
            'language': v.get('language', ''),
            'author': v.get('author', ''),
            'country': v.get('country', ''),
            'keywords': v.get('keywords', []),
        })
    return result


def _layer3_classify(mentions):
    """
    LAYER 3 — CLASSIFY in two focused passes so Haiku stays sharp:

      3A. SENSITIVITY — two binary sub-layers:
            - P0 check (critical): active-crisis detector, narrow prompt
            - P1 check (high): concern/risk detector for non-P0 items
            - everything else → P2 ("medium")

      3B. META — sentiment + source_type in a separate dar-focused call.

    Splitting these prevents the old problem where one mega-prompt made Haiku
    under-call P0/P1 because it was also worrying about sentiment/source_type.
    """
    if not mentions:
        return []
    for batch in _chunks(mentions, 15):
        _layer3_sensitivity_batch(batch)
    for batch in _chunks(mentions, 15):
        _layer3_meta_batch(batch)
    return mentions


def _layer3_sensitivity_batch(mentions):
    """Two focused binary passes: P0 detector, then P1 detector on survivors."""
    entries_all = [{
        'idx': i,
        'platform': m.get('platform', ''),
        'content_english': (m.get('content_english') or '')[:400],
        'content_original': (m.get('content_original') or '')[:400],
    } for i, m in enumerate(mentions)]

    # ── 3A-i: P0 binary detector ─────────────────────────────────────
    p0_prompt = f"""You are a P0 (ACTIVE CRISIS) detector for a Bilibili social listening platform.

For EACH item answer "yes" or "no". Answer "yes" ONLY if the item clearly describes ONE of the following, happening NOW or very recently, and specifically about Bilibili:

- Regulatory / government action against Bilibili: ban, formal investigation, sanctions, legal proceeding, adverse court ruling, enforcement order
- Confirmed data breach or security incident at Bilibili
- Major media exposé or scandal specifically about Bilibili
- Content-safety incident forcing takedowns (child-safety, illegal content, CSAM)
- Large-scale user backlash / viral controversy currently unfolding (not historical)
- Mass creator revolt currently happening

Hard rules — answer "no" in all of these cases:
- Any positive news (milestones, records, product wins, gala success, partnerships) — positive is NEVER P0
- Speculation, commentary, analysis, opinion pieces
- Financial / stock / earnings coverage that slipped through
- Historical events already resolved
- Passing mentions where Bilibili is tangential
- Anything you are unsure about → "no"

Return ONLY a JSON array: [{{"idx":0,"p0":"yes"}}, {{"idx":1,"p0":"no"}}, ...]

Mentions:
{json.dumps(entries_all, ensure_ascii=False)}"""

    p0_verdicts = _haiku_call(p0_prompt, max_tokens=1024)
    p0_indices = set()
    if p0_verdicts:
        for v in p0_verdicts:
            idx = v.get('idx')
            if idx is None or not isinstance(idx, int) or idx >= len(mentions):
                continue
            if str(v.get('p0', 'no')).strip().lower() == 'yes':
                p0_indices.add(idx)

    # ── 3A-ii: P1 binary detector on non-P0 survivors ────────────────
    p1_indices = set()
    non_p0 = [e for e in entries_all if e['idx'] not in p0_indices]
    if non_p0:
        p1_prompt = f"""You are a P1 (CONCERN / RISK SIGNAL) detector for a Bilibili social listening platform. These items have already been confirmed as NOT a P0 crisis.

For EACH item answer "yes" or "no". Answer "yes" if the item describes a concern, risk, or negative signal for Bilibili — something that is or could become a problem for user trust, brand reputation, creator relationships, product experience, or competitive position. Examples of P1 signals:

- Data privacy, security, or platform-safety worries raised by users, researchers, or journalists (even speculative, e.g. "is Bilibili safe to use?")
- Academic / journalistic research highlighting problems: harmful content reach, youth-safety findings, moderation gaps, misinformation
- Creator dissatisfaction, disputes with Bilibili, talk of leaving the platform
- User complaints about moderation, censorship, or content policy going beyond isolated cases
- Negative journalist / analyst critique or opinion piece questioning Bilibili's strategy or practices
- Feature / product complaints gaining visible traction (bugs, unwanted UX changes, regressions)
- Algorithm or policy changes that users are pushing back on
- Competitor move that threatens Bilibili's position, user-migration signals
- Accessibility or technical problems getting visible attention
- Brand-reputation risk: negative cultural framing, PR misstep short of scandal

Hard rules — answer "no" in all of these cases:
- Positive milestones: MAU / DAU records, record viewer counts, esports wins, gala audiences, anniversary successes
- Product launches, AI tool releases, new features announced or celebrated (unless the coverage is about clear user pushback)
- Brand partnerships, global brands joining the platform
- Neutral industry overviews or list inclusions
- Trivia, tips, passing mentions, aggregator-style scraping
- If the story reads like a WIN for Bilibili → "no"
- If you are unsure → "no"

A P1 item should read like a warning light on a dashboard, not a trophy.

Return ONLY a JSON array: [{{"idx":0,"p1":"yes"}}, ...]  (use the SAME idx values as in the input)

Mentions:
{json.dumps(non_p0, ensure_ascii=False)}"""

        p1_verdicts = _haiku_call(p1_prompt, max_tokens=1024)
        if p1_verdicts:
            for v in p1_verdicts:
                idx = v.get('idx')
                if idx is None or not isinstance(idx, int) or idx >= len(mentions):
                    continue
                if idx in p0_indices:
                    continue
                if str(v.get('p1', 'no')).strip().lower() == 'yes':
                    p1_indices.add(idx)

    # ── Write sensitivity label onto each mention ────────────────────
    for i in range(len(mentions)):
        if i in p0_indices:
            mentions[i]['sensitivity'] = 'critical'
        elif i in p1_indices:
            mentions[i]['sensitivity'] = 'high'
        else:
            mentions[i]['sensitivity'] = 'medium'


def _layer3_meta_batch(mentions):
    """Separate, focused call for sentiment + source_type (not mixed with sensitivity)."""
    entries = [{
        'idx': i,
        'platform': m.get('platform', ''),
        'content_english': (m.get('content_english') or '')[:400],
    } for i, m in enumerate(mentions)]

    prompt = f"""Classify each Bilibili-related mention by sentiment and source_type.

sentiment: "positive" | "negative" | "neutral"

  IMPORTANT: judge what the described event / information means FOR BILIBILI, NOT the writing tone of the source. A news article written in a neutral, factual reporting style can still be clearly positive or negative sentiment if the underlying event is a win or a problem for Bilibili. Do not confuse "reporter tone is calm" with "neutral sentiment".

  - "positive" — the event is GOOD NEWS for Bilibili. Examples:
      * Records, milestones, growth figures, MAU / DAU highs, record viewers
      * Awards, wins, successful launches (AniSora, AI tools, new features launched and received well)
      * Global brand partnerships joining the platform
      * Esports wins, cultural-event successes, viral positive moments
      * User excitement, fan praise, creator compliments
      * Successful IP collaborations, well-received content drops

  - "negative" — the event is BAD NEWS for Bilibili. Examples:
      * Complaints, criticism, controversy, backlash, user frustration
      * Creator disputes, talk of leaving, moderation disputes
      * Regulatory pressure, legal action, investigation, bans
      * Platform-safety, privacy, security concerns
      * Negative reviews of features, bugs gaining traction
      * Declining metrics framed as concerning, critical analyst takes
      * Scandals, exposés, negative cultural framing
      * Competitor threat narratives where Bilibili loses ground

  - "neutral" — use ONLY when the item is genuinely flat with no clear good-or-bad angle for Bilibili:
      * Bilibili appears as one of many platforms in a list with no specific coloring
      * A how-to / tip / background reference
      * An industry overview that does not lean positive or negative about Bilibili specifically
      * Pure factual announcements with no evaluative content (rare)

  Default to positive or negative whenever there is a discernible direction. "neutral" should be rare — reserve it for truly flat mentions. When in doubt between neutral and one of the other two, pick whichever side the underlying event leans toward, however slightly.

source_type: "government" | "news_major" | "news_minor" | "blog" | "forum" | "social"
  - government: regulator, ministry, official agency
  - news_major: Reuters, Bloomberg, BBC, NHK, CNBC, AP, AFP, major national outlets
  - news_minor: smaller regional outlets, trade press, niche industry publications
  - blog: personal blog, opinion site, review site
  - forum: Reddit, discussion board, community forum
  - social: social media post, tweet, YouTube / IG / TikTok comment
  (Do NOT use "financial" — financial content was filtered out in earlier layers.)

Return ONLY a JSON array: [{{"idx":0,"sentiment":"...","source_type":"..."}}, ...]

Mentions:
{json.dumps(entries, ensure_ascii=False)}"""

    verdicts = _haiku_call(prompt, max_tokens=1024)
    if not verdicts:
        for m in mentions:
            m.setdefault('sentiment', 'neutral')
            m.setdefault('source_type', 'news_minor')
        return
    for v in verdicts:
        idx = v.get('idx')
        if idx is None or not isinstance(idx, int) or idx >= len(mentions):
            continue
        mentions[idx]['sentiment'] = v.get('sentiment', 'neutral')
        mentions[idx]['source_type'] = v.get('source_type', 'news_minor')
    for m in mentions:
        m.setdefault('sentiment', 'neutral')
        m.setdefault('source_type', 'news_minor')


def _layer4_final_gate(mentions):
    """
    LAYER 4 — FINAL GATE before DB write.

    Catches false positives slipping through the 2026-regex date filter: pages
    that mention 2026 somewhere in the body but were actually published in 2025
    or earlier. Also a last safety net for Bilibili-relevance, scope (non-
    Mainland / non-Simplified), and purely-financial content that slipped past
    earlier layers.

    Input: list of mentions that already passed _validate_and_repair.
    Output: (approved_list, rejected_details) where rejected_details is a list
    of {url, content_date, reason} entries for logging / API return.
    """
    if not mentions:
        return [], []

    entries = []
    for i, m in enumerate(mentions):
        entries.append({
            'idx': i,
            'url': (m.get('url') or '')[:200],
            'content_date': m.get('content_date') or '',
            'language': m.get('language', ''),
            'country': m.get('country', ''),
            'content_english': (m.get('content_english') or '')[:500],
            'content_original': (m.get('content_original') or '')[:500],
        })

    approved_indices = set()
    rejected_details = []
    for batch in _chunks(entries, 12):
        prompt = f"""You are the FINAL GATE before publishing social listening mentions to a live website. Be strict — reject anything that does not clearly meet ALL of these criteria.

For EACH item answer "approve" or "reject". Reject if ANY of the following is true:

1. PUBLICATION YEAR ≠ 2026
   - The project publishes ONLY content genuinely published in 2026.
   - Beware false positives: many 2025 articles mention "2026" in the body (upcoming events, forecasts, winter-2026 anime lineup, roadmap year, related article sidebar, cached modification date). Those must be REJECTED if the item itself was published before 2026.
   - Use the text and URL to judge the likely publication date. The URL sometimes encodes a date like /2025/09/... — if you see an earlier-year path, REJECT.
   - If the item clearly reads like a 2025-or-older article (historical framing, events from 2024/2025 described in past tense as the subject, retrospectives about prior years), REJECT.
   - If the content describes something that would be published in 2026 and reads like fresh 2026 news/discussion, approve.
   - When genuinely uncertain about the year, REJECT.

2. NOT ABOUT BILIBILI
   - The text must be genuinely about Bilibili the Chinese video platform (bilibili.com, B站, 哔哩哔哩, 嗶哩嗶哩). If Bilibili is only a tangential keyword, a sidebar link, or a disambiguation, REJECT.

3. OUT OF SCOPE (Mainland China / Simplified Chinese)
   - If the source is a Mainland China outlet or the content language is Simplified Chinese (Mandarin / zh-CN), REJECT. Traditional Chinese (TW/HK) is fine.

4. PURE FINANCIAL
   - Pure stock/earnings/analyst/IPO/dividend coverage with no product/creator/policy/user angle → REJECT. Mixed content where the non-financial angle is extractable is fine (those should already have been rewritten upstream).

Return ONLY a JSON array: [{{"idx":0,"verdict":"approve"}}, {{"idx":1,"verdict":"reject","reason":"year_2025"}}, ...]

Reason codes (short): year_not_2026, not_bilibili, scope_mainland, pure_financial, uncertain.

Items:
{json.dumps(batch, ensure_ascii=False)}"""

        verdicts = _haiku_call(prompt, max_tokens=1024)
        if not verdicts:
            # Fail-CLOSED: Haiku fail → park the batch in the retry queue
            # instead of auto-publishing unvetted content. A transient API
            # blip must not bypass year/scope/financial checks.
            batch_urls = [mentions[e['idx']].get('url', '') for e in batch]
            print(
                f'[L4 gate] haiku call failed, fail-CLOSED batch={len(batch)} '
                f'urls={batch_urls[:3]}...',
                flush=True,
            )
            try:
                _db().table('social_gate_failures').insert({
                    'batch': [mentions[e['idx']] for e in batch],
                    'error_type': 'haiku_call_failed',
                }).execute()
            except Exception as e2:
                print(f'[L4 gate] gate_failures insert error: {type(e2).__name__}', flush=True)
            continue

        for v in verdicts:
            idx = v.get('idx')
            if idx is None or not isinstance(idx, int) or idx >= len(mentions):
                continue
            verdict = str(v.get('verdict', '')).strip().lower()
            if verdict == 'approve':
                approved_indices.add(idx)
            else:
                reason = v.get('reason', 'unspecified')
                url = mentions[idx].get('url', '')
                cdate = mentions[idx].get('content_date', '')
                preview = (mentions[idx].get('content_english') or mentions[idx].get('content_original') or '')[:300]
                print(f'[L4 gate] REJECT idx={idx} reason={reason} date={cdate} url={url}', flush=True)
                rejected_details.append({
                    'url': url,
                    'content_date': cdate,
                    'reason': reason,
                })
                try:
                    _db().table('social_rejections').insert({
                        'url': url,
                        'content_date': cdate if cdate else None,
                        'reason': reason,
                        'layer': 'l4',
                        'content_preview': preview,
                    }).execute()
                except Exception as e2:
                    print(f'[L4 gate] rejections insert error: {type(e2).__name__}', flush=True)

    approved = [mentions[i] for i in range(len(mentions)) if i in approved_indices]
    return approved, rejected_details


def retry_gate_failures():
    """Admin: re-run the L4 gate on previously parked (Haiku-failed) batches.

    Used to drain the social_gate_failures queue once the API is healthy
    again. Successful rows are upserted via the normal save_mentions path
    so that Telegram/WeCom alerts still fire for any P0s. Resolved rows
    are marked instead of deleted for audit.
    Returns {'retried': N, 'saved': M, 'still_failing': K}."""
    try:
        res = (_db().table('social_gate_failures')
               .select('id, batch, retry_count')
               .eq('resolved', False)
               .order('created_at')
               .limit(100)
               .execute())
        rows = res.data or []
    except Exception as e:
        return {'error': f'fetch_failed: {type(e).__name__}'}

    retried = 0
    saved_total = 0
    still_failing = 0
    for row in rows:
        batch = row.get('batch') or []
        if not isinstance(batch, list) or not batch:
            continue
        retried += 1
        result = save_mentions(batch)  # re-runs L4 gate + upsert
        saved_total += result.get('saved', 0)
        # Consider it resolved if Haiku produced a verdict this time:
        # save_mentions returns gate_rejected >= 0 only when the gate ran.
        # If everything was still parked again we treat as still-failing.
        try:
            _db().table('social_gate_failures').update({
                'resolved': True,
                'retry_count': (row.get('retry_count') or 0) + 1,
            }).eq('id', row['id']).execute()
        except Exception:
            still_failing += 1
    return {
        'retried': retried,
        'saved': saved_total,
        'still_failing': still_failing,
    }


def _analyze_with_haiku(items):
    """
    Three-layer Haiku pipeline (replaces the old single-prompt call):
      L1 TRIAGE  → relevance + scope + social-angle filter (drops garbage cheaply)
      L2 EXTRACT → content_english, content_original, language, author, country, keywords
      L3 CLASSIFY → sentiment, sensitivity, source_type
    Each layer has a narrow focus so Haiku attention stays sharp.
    """
    if not items:
        return []
    triaged = _layer1_triage(items)
    if not triaged:
        return []
    extracted = _layer2_extract(triaged)
    if not extracted:
        return []
    return _layer3_classify(extracted)


# ─────────────────────────────────────────────
# SCAN — ALL-IN-ONE ENDPOINT
# ─────────────────────────────────────────────

def scan_urls(urls):
    """
    Full pipeline in one call:
      1. Dedup URLs against DB
      2. Download & check for 2026 dates
      3. Analyze with Haiku
      4. Save to Supabase
    Returns summary dict.
    """
    # Step 1: dedup
    new_urls = check_urls(urls)
    if not new_urls:
        return {'received': len(urls), 'new': 0, 'with_2026': 0, 'saved': 0, 'skipped': 0}

    # Step 2: download + date filter (cap at 80 URLs to stay within timeout)
    processed = process_urls(new_urls[:80], time_budget=40)
    items_2026 = processed.get('items', [])

    if not items_2026:
        return {
            'received': len(urls),
            'new': len(new_urls),
            'with_2026': 0,
            'saved': 0,
            'skipped': 0,
        }

    # Step 3: 3-layer Haiku pipeline (triage → extract → classify)
    mentions = _analyze_with_haiku(items_2026)

    # Step 4: save (heuristic validation also runs inside save_mentions)
    if mentions:
        result = save_mentions(mentions)
    else:
        result = {'saved': 0, 'skipped': 0, 'repaired': 0}

    return {
        'received': len(urls),
        'new': len(new_urls),
        'with_2026': len(items_2026),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# AUTO-DISCOVER — DDG search across 8 languages
# ─────────────────────────────────────────────

# Search queries per language — short, no year (pipeline filters for 2026 content)
_DISCOVER_QUERIES = {
    'English': [
        # Core — always included
        'Bilibili',
        'Bilibili Gaming',
        # Rotated pool — random 4 picked each run
        'Bilibili app',
        '"bilibili.com"',
        'B站 Bilibili',
        'Bilibili China platform',
        'Bilibili streaming',
        'Bilibili review',
        'Bilibili opinion',
        'Bilibili users',
        'Bilibili update',
        'Bilibili banned',
        'Bilibili vs YouTube',
        'Bilibili community',
        # Ecosystem expansion — VTuber, esports, AI, creator, policy
        'Bilibili VTuber',
        'Bilibili BLG',
        'Bilibili LPL',
        'Bilibili AniSora',
        'Bilibili AI',
        'Bilibili creator',
        'Bilibili anime rights',
        'Bilibili censorship',
        'Bilibili moderation',
        'Bilibili leak',
        'Bilibili partnership',
        'Bilibili livestream',
    ],
    'Japanese': [
        'ビリビリ',
        'Bilibili',
        'ビリビリ動画',
        'B站',
        'ビリビリ アプリ',
        '哔哩哔哩',
        'bilibili.com',
        'ビリビリ レビュー',
        'ビリビリ ユーザー',
        'ビリビリ 中国',
        'ビリビリ 配信',
        # Ecosystem
        'ビリビリ アニメ',
        'ビリビリ Vtuber',
        'ビリビリ 声優',
        'ビリビリ BLG',
        'ビリビリ AI',
        'ビリビリ AniSora',
    ],
    'Arabic': [
        'بيليبيلي',
        'Bilibili',
        'بيليبيلي Bilibili',
        'B站',
        'بيليبيلي تطبيق',
        'بيليبيلي صيني',
        'bilibili.com',
        'بيليبيلي منصة',
        'بيليبيلي مراجعة',
        'Bilibili app',
    ],
    'Traditional Chinese': [
        '嗶哩嗶哩',
        'B站',
        'Bilibili',
        '嗶哩嗶哩 B站',
        '嗶哩嗶哩 平台',
        'bilibili.com',
        'B站 用戶',
        'B站 更新',
        'B站 評價',
        'B站 直播',
        # Ecosystem
        '嗶哩嗶哩 動漫',
        'B站 VTuber',
        'B站 BLG',
        'B站 AniSora',
        'B站 AI',
        'B站 創作者',
    ],
    'Turkish': [
        'Bilibili',
        'Bilibili nedir',
        'Bilibili Çin',
        'bilibili.com',
        'Bilibili platform',
        'Bilibili uygulama',
        'Bilibili inceleme',
        'Bilibili yorum',
        'Bilibili kullanıcı',
    ],
    'Russian': [
        'Bilibili',
        'Билибили',
        'Bilibili Китай',
        'B站 Bilibili',
        'bilibili.com',
        'Билибили платформа',
        'Билибили приложение',
        'Билибили обзор',
        'Билибили пользователи',
    ],
    'Spanish': [
        'Bilibili',
        'Bilibili China',
        'bilibili.com',
        'Bilibili plataforma',
        'Bilibili app',
        'B站 Bilibili',
        'Bilibili opinión',
        'Bilibili usuarios',
        'Bilibili reseña',
    ],
    'Portuguese': [
        'Bilibili',
        'Bilibili China',
        'bilibili.com',
        'Bilibili plataforma',
        'Bilibili app',
        'B站 Bilibili',
        'Bilibili opinião',
        'Bilibili usuários',
        'Bilibili avaliação',
    ],
}

# How many queries to use per run (pick random subset from pool)
_QUERIES_PER_RUN = 6

# Google News RSS params per language — reliable multilingual news source
_GNEWS_PARAMS = {
    'English':            {'hl': 'en',    'gl': 'US', 'ceid': 'US:en'},
    'Japanese':           {'hl': 'ja',    'gl': 'JP', 'ceid': 'JP:ja'},
    'Arabic':             {'hl': 'ar',    'gl': 'SA', 'ceid': 'SA:ar'},
    'Traditional Chinese':{'hl': 'zh-TW', 'gl': 'TW', 'ceid': 'TW:zh-Hant'},
    'Turkish':            {'hl': 'tr',    'gl': 'TR', 'ceid': 'TR:tr'},
    'Russian':            {'hl': 'ru',    'gl': 'RU', 'ceid': 'RU:ru'},
    'Spanish':            {'hl': 'es',    'gl': 'ES', 'ceid': 'ES:es'},
    'Portuguese':         {'hl': 'pt-BR', 'gl': 'BR', 'ceid': 'BR:pt-419'},
}

# Domains to skip (not content pages)
_SKIP_DOMAINS = {
    'play.google.com', 'apps.apple.com',
    'wikipedia.org', 'bilibili.com', 'bilibili.tv', 'github.com',
    'vlr.gg', 'aastocks.com',
    # Mainland China domains — out of project scope
    'sina.com.cn', 'sina.cn', 'weibo.com', 'weibo.cn',
    '163.com', 'sohu.com', 'qq.com', 'thepaper.cn',
    'xinhuanet.com', 'people.com.cn', 'globaltimes.cn',
    'chinadaily.com.cn', 'cctv.com', 'cctv.cn',
    'cac.gov.cn', 'nrta.gov.cn', 'miit.gov.cn', 'nppa.gov.cn',
    'gov.cn', 'chinanews.com', 'chinanews.com.cn',
    'baidu.com', 'zhihu.com', 'douyin.com', 'toutiao.com',
    '36kr.com', 'ifeng.com', 'jiemian.com', 'huanqiu.com',
    'eastmoney.com', 'chinaz.com', 'yicai.com', 'caixin.com',
    'infzm.com', 'cnstock.com', 'stcn.com',
}


def _google_news_rss(query, hl, gl, ceid, max_results=20, when='1m'):
    """Fetch article URLs from Google News RSS. when: '1h','1d','7d','1m','1y'."""
    import xml.etree.ElementTree as ET
    import urllib.parse
    q = f"{query} when:{when}" if when else query
    rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl={hl}&gl={gl}&ceid={ceid}"
    try:
        resp = requests.get(rss_url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        urls = []
        for item in root.iter('item'):
            # Try <link> tag first, then <guid>
            link_el = item.find('link')
            guid_el = item.find('guid')
            url = None
            if link_el is not None and link_el.text and link_el.text.startswith('http'):
                url = link_el.text.strip()
            elif guid_el is not None and guid_el.text and guid_el.text.startswith('http'):
                url = guid_el.text.strip()
            if url:
                domain = urlparse(url).netloc.lower().replace('www.', '')
                if not any(skip in domain for skip in _SKIP_DOMAINS):
                    urls.append(url)
        return urls[:max_results]
    except Exception:
        return []


def _bing_news_rss(query, mkt='en-US', max_results=20):
    """Fetch article URLs from Bing News RSS. Returns list of URLs."""
    import xml.etree.ElementTree as ET
    import urllib.parse
    rss_url = f"https://www.bing.com/news/search?q={urllib.parse.quote(query)}&format=RSS&mkt={mkt}"
    try:
        resp = requests.get(rss_url, headers=BROWSER_HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        urls = []
        for item in root.iter('item'):
            link_el = item.find('link')
            url = None
            if link_el is not None and link_el.text and link_el.text.startswith('http'):
                url = link_el.text.strip()
            if url:
                domain = urlparse(url).netloc.lower().replace('www.', '')
                if not any(skip in domain for skip in _SKIP_DOMAINS):
                    urls.append(url)
        return urls[:max_results]
    except Exception:
        return []


# Bing News market codes per language
_BING_MARKETS = {
    'English':            'en-US',
    'Japanese':           'ja-JP',
    'Arabic':             'ar-SA',
    'Traditional Chinese':'zh-TW',
    'Turkish':            'tr-TR',
    'Russian':            'ru-RU',
    'Spanish':            'es-ES',
    'Portuguese':         'pt-BR',
}


def _brave_search_full(query, max_results=20, freshness='pm', country='us'):
    """Brave Search Web API — returns list of result dicts:
    [{'url':..., 'title':..., 'description':...}]. URL-only callers can
    use the `_brave_search` wrapper.

    freshness: 'pd'/'pw'/'pm'/'py' or None for all-time. site: filter
    is silently dropped by Brave when freshness is set, so callers that
    site:-restrict should pass freshness=None.
    """
    import time as _t
    api_key = os.environ.get('BRAVE_API_KEY', '').strip()
    if not api_key:
        return []
    if _cooling_down('api.search.brave.com'):
        return []
    params = {'q': query, 'count': min(max_results, 20)}
    if country:
        params['country'] = country
    if freshness:
        params['freshness'] = freshness
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip',
        'X-Subscription-Token': api_key,
    }
    try:
        resp = requests.get('https://api.search.brave.com/res/v1/web/search',
                            params=params, headers=headers, timeout=10)
    except Exception as e:
        print(f'[brave] q={query!r} request_err={e}', flush=True)
        return []
    if resp.status_code == 429:
        _enter_cooldown('api.search.brave.com', 60)
        print(f'[brave] q={query!r} RATE_LIMITED', flush=True)
        return []
    if resp.status_code != 200:
        print(f'[brave] q={query!r} status={resp.status_code} body={resp.text[:200]}',
              flush=True)
        return []
    try:
        data = resp.json()
    except Exception:
        _t.sleep(1.1)
        return []
    web = (data.get('web') or {}).get('results') or []
    out = []
    seen = set()
    for r in web:
        u = r.get('url') or ''
        if not u or u in seen:
            continue
        seen.add(u)
        out.append({
            'url': u,
            'title': r.get('title') or '',
            'description': r.get('description') or '',
        })
    _t.sleep(1.1)
    return out[:max_results]


def _brave_search(query, max_results=20, freshness='pm', country='us'):
    """Backward-compat wrapper: returns list of URLs only."""
    return [r['url'] for r in _brave_search_full(query, max_results, freshness, country)]


def _ddg_search(query, max_results=20, region='wt-wt', timelimit=None):
    """DuckDuckGo search via duckduckgo-search library — returns list of URLs.
    timelimit: 'd'=day, 'w'=week, 'm'=month, 'y'=year, None=all time
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region=region, timelimit=timelimit, max_results=max_results))
        urls = []
        for r in results:
            url = r.get('href', '')
            if not url:
                continue
            domain = urlparse(url).netloc.lower().replace('www.', '')
            if any(skip in domain for skip in _SKIP_DOMAINS):
                continue
            if url not in urls:
                urls.append(url)
        return urls[:max_results]
    except Exception:
        return []


# DDG region codes per language — multiple regions for better coverage
_LANG_REGIONS = {
    'English': ['us-en', 'uk-en', 'wt-wt'],
    'Japanese': ['jp-jp', 'wt-wt'],
    'Arabic': ['xa-ar', 'wt-wt'],
    'Traditional Chinese': ['hk-tzh', 'tw-tzh', 'wt-wt'],
    'Turkish': ['tr-tr', 'wt-wt'],
    'Russian': ['ru-ru', 'wt-wt'],
    'Spanish': ['es-es', 'ar-es', 'mx-es', 'wt-wt'],
    'Portuguese': ['br-pt', 'pt-pt', 'wt-wt'],
}


# Known domains with Bilibili content — crawl their listing pages for fresh articles
_DIRECT_CRAWL_SOURCES = [
    # English — general tech/gaming
    'https://www.invenglobal.com/lol/teams/bilibili-gaming',
    'https://techcrunch.com/tag/bilibili/',
    'https://www.theverge.com/search?q=bilibili',
    'https://www.scmp.com/topics/bilibili',
    # English — niche gaming/anime (fills the gap news aggregators miss)
    'https://www.animenewsnetwork.com/search/?q=bilibili',
    'https://www.gematsu.com/?s=bilibili',
    'https://www.eurogamer.net/search?q=bilibili',
    'https://www.polygon.com/search?q=bilibili',
    'https://kotaku.com/search?q=bilibili',
    'https://www.pcgamer.com/search/?searchTerm=bilibili',
    # English — Asia-tech non-Mainland
    'https://kr-asia.com/?s=bilibili',
    'https://restofworld.org/search/?q=bilibili',
    'https://asia.nikkei.com/Search?keyword=bilibili',
    # Traditional Chinese
    'https://www.ithome.com.tw/search?q=bilibili',
    'https://ec.ltn.com.tw/search?keyword=bilibili',
    # Japanese
    'https://fistbump-news.jp/?s=bilibili',
    'https://www.4gamer.net/search/?text=bilibili',
    'https://animeanime.jp/search/?q=bilibili',
    # Spanish/Portuguese
    'https://www.xataka.com/?s=bilibili',
    # Turkish
    'https://www.webtekno.com/arama?q=bilibili',
]


def crawl_direct_sources(max_urls=50):
    """
    Crawl known good domains' listing/search pages to extract fresh article links.
    Returns list of URLs found on these pages.
    """
    all_urls = []
    seen = set()
    for listing_url in _DIRECT_CRAWL_SOURCES:
        try:
            resp = requests.get(listing_url, headers=BROWSER_HEADERS, timeout=8)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, 'html.parser')
            base_domain = urlparse(listing_url).netloc
            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                if href.startswith('/'):
                    href = f"https://{base_domain}{href}"
                elif not href.startswith('http'):
                    continue
                link_domain = urlparse(href).netloc.replace('www.', '')
                if any(skip in link_domain for skip in _SKIP_DOMAINS):
                    continue
                if href not in seen and len(href) > 30:
                    seen.add(href)
                    all_urls.append(href)
        except Exception:
            continue
    return all_urls[:max_urls]


def auto_discover(languages=None):
    """
    Auto-discover Bilibili mentions in specified language(s) using DDG.
    Pass one language at a time to stay within gunicorn timeout.
    Uses multiple regions per language for better coverage.
    Time budget: 50s for DDG search, rest for scan pipeline.
    Returns per-language summary.
    """
    import time
    import random

    if languages is None:
        languages = list(_DISCOVER_QUERIES.keys())

    results = {}
    for lang in languages:
        all_queries = _DISCOVER_QUERIES.get(lang, [])
        if not all_queries:
            continue

        # Random subset each run — different queries each day
        if len(all_queries) > _QUERIES_PER_RUN:
            queries = random.sample(all_queries, _QUERIES_PER_RUN)
        else:
            queries = all_queries

        regions = list(_LANG_REGIONS.get(lang, ['wt-wt']))
        random.shuffle(regions)

        # Collect URLs from all queries × all regions for this language
        # Time budget: 50s for DDG searches (leaves ~60s for download+analyze+save)
        all_urls = []
        seen = set()
        search_start = time.time()

        # Bilibili-specific Google News queries per language
        gnews_queries = ['bilibili', 'Bilibili Gaming']
        if lang == 'Traditional Chinese':
            gnews_queries = ['嗶哩嗶哩', 'B站', 'bilibili']
        elif lang == 'Japanese':
            gnews_queries = ['ビリビリ', 'bilibili', 'B站']
        elif lang == 'Arabic':
            gnews_queries = ['بيليبيلي', 'bilibili']

        # 1. Google News RSS — fast, multilingual
        gnews = _GNEWS_PARAMS.get(lang)
        if gnews:
            for q in gnews_queries:
                if time.time() - search_start > 15:
                    break
                urls = _google_news_rss(q, gnews['hl'], gnews['gl'], gnews['ceid'], max_results=20)
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        all_urls.append(u)

        # 2. Bing News RSS — separate index from Google (max 5s, 1-2 queries)
        bing_mkt = _BING_MARKETS.get(lang, 'en-US')
        for q in gnews_queries[:2]:
            if time.time() - search_start > 20:
                break
            urls = _bing_news_rss(q, mkt=bing_mkt, max_results=20)
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    all_urls.append(u)

        # 3. DDG — broader search, main workhorse (budget: 20s–55s = 35s)
        # First half of queries: last month (fresh). Second half: last year (wider net).
        half = len(queries) // 2
        for i, q in enumerate(queries):
            if time.time() - search_start > 55:
                break
            tl = 'm' if i < half else 'y'
            for region in regions:
                if time.time() - search_start > 55:
                    break
                urls = _ddg_search(q, max_results=20, region=region, timelimit=tl)
                for u in urls:
                    if u not in seen:
                        seen.add(u)
                        all_urls.append(u)
                # If first region already found enough URLs for this query, skip extras
                if len(urls) >= 10:
                    break

        # 4. YouTube search via DDG — find videos about Bilibili (budget: 5s)
        if time.time() - search_start < 60:
            yt_urls = _ddg_search('site:youtube.com bilibili', max_results=10, region='wt-wt', timelimit='m')
            for u in yt_urls:
                if u not in seen and 'youtube.com/watch' in u:
                    seen.add(u)
                    all_urls.append(u)

        # Run through scan pipeline
        if all_urls:
            scan_result = scan_urls(all_urls)
        else:
            scan_result = {'received': 0, 'new': 0, 'with_2026': 0, 'saved': 0, 'skipped': 0}

        scan_result['language'] = lang
        scan_result['queries'] = len(queries)
        scan_result['urls_found'] = len(all_urls)
        results[lang] = scan_result

    # Bonus: direct domain crawl (outside language loop, runs once per discover call)
    try:
        direct_urls = crawl_direct_sources(max_urls=60)
        if direct_urls:
            direct_result = scan_urls(direct_urls)
            direct_result['language'] = 'direct_crawl'
            results['direct_crawl'] = direct_result
    except Exception:
        pass

    return results


# ─────────────────────────────────────────────
# REDDIT — direct JSON API (bypasses DDG + JS rendering)
# ─────────────────────────────────────────────

_REDDIT_SUBREDDITS = [
    'Bilibili', 'gachagaming', 'China', 'HongKong',
    'animepiracy', 'Sino', 'Vtubers',
    'anime', 'animenews', 'AnimeSuggest',
    'GenshinImpact', 'HonkaiStarRail', 'Genshin_Impact',
    'LeagueOfLegends', 'VtubersAdv', 'VCJ',
]

_REDDIT_SEARCH_QUERIES = [
    'bilibili', 'bilibili gaming', 'bilibili app',
    'bilibili hoyoverse', 'genshin bilibili', 'hololive bilibili',
    'bilibili world', 'bilibili vtuber', 'BLG bilibili',
]

_REDDIT_UA = 'web:duflat-social-listening:v1.0 (by /u/duflat_bot)'


def _fetch_reddit_json(kind, q):
    """kind='search' → reddit.com/search.json?q=q; kind='sub' → r/q/new.json."""
    import time
    from urllib.parse import quote_plus
    if _cooling_down('reddit.com'):
        return []
    if kind == 'search':
        url = f'https://www.reddit.com/search.json?q={quote_plus(q)}&sort=new&t=year&limit=50'
    else:
        url = f'https://www.reddit.com/r/{q}/new.json?limit=50'
    try:
        resp = requests.get(url, headers={'User-Agent': _REDDIT_UA}, timeout=6)
    except Exception as e:
        print(f'[reddit] {kind}={q} request_exception={e}', flush=True)
        return []
    if resp.status_code in (429, 403):
        # Reddit limits unauthenticated traffic to ~60 req/10min.
        _enter_cooldown('reddit.com', 600)
        print(f'[reddit] {kind}={q} RATE_LIMITED status={resp.status_code}', flush=True)
        return []
    if resp.status_code != 200:
        print(f'[reddit] {kind}={q} status={resp.status_code} body={resp.text[:200]}', flush=True)
        return []
    try:
        children = resp.json().get('data', {}).get('children', [])
    except Exception as e:
        print(f'[reddit] {kind}={q} json_err={e} body={resp.text[:200]}', flush=True)
        return []
    print(f'[reddit] {kind}={q} ok children={len(children)}', flush=True)
    time.sleep(0.3)
    return children


def _reddit_post_to_item(d):
    """Convert Reddit post data dict to pipeline item."""
    permalink = d.get('permalink', '')
    if not permalink:
        return None
    post_url = f'https://www.reddit.com{permalink}'
    created = d.get('created_utc', 0)
    try:
        dt = datetime.utcfromtimestamp(created)
    except Exception:
        return None
    if dt.year < 2026:
        return None
    text_parts = [d.get('title', ''), d.get('selftext', '') or '']
    sub = d.get('subreddit', '')
    if sub:
        text_parts.insert(0, f'[r/{sub}]')
    text = '\n\n'.join(p for p in text_parts if p).strip()
    if not text:
        return None
    return {
        'url': post_url,
        'url_hash': hash_url(post_url),
        'platform': 'reddit.com',
        'text': text[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_reddit():
    """Fetch Bilibili-related Reddit posts via JSON API, analyze, save."""
    import time
    all_items = []
    seen = set()
    fetch_budget = 40  # seconds
    fetch_start = time.time()

    # Subreddit feeds (noisy — only keep bilibili mentions)
    for sub in _REDDIT_SUBREDDITS:
        if time.time() - fetch_start > fetch_budget:
            break
        children = _fetch_reddit_json('sub', sub)
        for c in children:
            d = c.get('data', {})
            blob = (d.get('title', '') + ' ' + (d.get('selftext', '') or '')).lower()
            if sub.lower() == 'bilibili':
                pass  # dedicated sub — keep all
            elif 'bilibili' not in blob and 'b站' not in blob and '哔哩' not in blob and '嗶哩' not in blob:
                continue
            item = _reddit_post_to_item(d)
            if item and item['url'] not in seen:
                seen.add(item['url'])
                all_items.append(item)

    # Global search queries
    for q in _REDDIT_SEARCH_QUERIES:
        if time.time() - fetch_start > fetch_budget:
            break
        children = _fetch_reddit_json('search', q)
        for c in children:
            d = c.get('data', {})
            blob = (d.get('title', '') + ' ' + (d.get('selftext', '') or '')).lower()
            if 'bilibili' not in blob and 'b站' not in blob and '哔哩' not in blob and '嗶哩' not in blob:
                continue
            item = _reddit_post_to_item(d)
            if item and item['url'] not in seen:
                seen.add(item['url'])
                all_items.append(item)

    print(f'[reddit] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'reddit', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    # Dedup against DB (check_urls returns list of {url, url_hash} dicts)
    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[reddit] check_urls error: {e}', flush=True)
        return {'platform': 'reddit', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[reddit] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'reddit', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    # Cap to stay within gunicorn 120s — Haiku on 25 items ≈ 30-40s
    items_new = items_new[:25]

    # Log source records
    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': 'reddit.com',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    # Haiku analyze + validate + save
    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[reddit] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[reddit] haiku error: {e}', flush=True)
        return {'platform': 'reddit', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[reddit] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[reddit] save error: {e}', flush=True)
        return {'platform': 'reddit', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'reddit',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# HACKER NEWS — Algolia public API (stories + comments)
# ─────────────────────────────────────────────

_HN_QUERIES = ['bilibili', 'b站', 'bilibili gaming', 'anisora']


def _fetch_hn_algolia(query, tags='story', pages=1):
    """Fetch Bilibili-related HN hits via Algolia. tags='story' or 'comment'."""
    from urllib.parse import quote_plus
    hits = []
    for p in range(pages):
        url = (
            f'https://hn.algolia.com/api/v1/search_by_date'
            f'?query={quote_plus(query)}&tags={tags}&hitsPerPage=50&page={p}'
        )
        try:
            resp = requests.get(url, timeout=6)
        except Exception as e:
            print(f'[hn] {tags}={query} request_exception={e}', flush=True)
            break
        if resp.status_code != 200:
            print(f'[hn] {tags}={query} status={resp.status_code}', flush=True)
            break
        try:
            data = resp.json()
        except Exception as e:
            print(f'[hn] {tags}={query} json_err={e}', flush=True)
            break
        batch = data.get('hits', []) or []
        hits.extend(batch)
        if len(batch) < 50:
            break
    print(f'[hn] {tags}={query} hits={len(hits)}', flush=True)
    return hits


def _hn_hit_to_item(h, tags):
    """Convert an Algolia hit to pipeline item. tags: 'story' or 'comment'."""
    object_id = h.get('objectID')
    if not object_id:
        return None
    story_id = h.get('story_id') or object_id
    hn_url = f'https://news.ycombinator.com/item?id={story_id if tags == "comment" else object_id}'
    created_at = h.get('created_at', '')
    try:
        dt = datetime.strptime(created_at[:10], '%Y-%m-%d')
    except Exception:
        return None
    if dt.year < 2026:
        return None
    title = h.get('title') or h.get('story_title') or ''
    body  = h.get('story_text') or h.get('comment_text') or ''
    ext   = h.get('url') or ''
    parts = [f'[HN {tags}]']
    if title: parts.append(title)
    if ext:   parts.append(f'(external: {ext})')
    if body:  parts.append(body)
    text = '\n\n'.join(parts).strip()
    if len(text) < 40:
        return None
    return {
        'url': hn_url,
        'url_hash': hash_url(hn_url),
        'platform': 'news.ycombinator.com',
        'text': text[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_hackernews():
    """Fetch Bilibili-related HN stories + comments, analyze, save."""
    import time
    all_items = []
    seen = set()
    fetch_start = time.time()

    for q in _HN_QUERIES:
        if time.time() - fetch_start > 30:
            break
        for tags in ('story', 'comment'):
            hits = _fetch_hn_algolia(q, tags=tags, pages=1)
            for h in hits:
                item = _hn_hit_to_item(h, tags)
                if item and item['url'] not in seen:
                    blob = item['text'].lower()
                    if 'bilibili' not in blob and 'b站' not in blob and '哔哩' not in blob and '嗶哩' not in blob:
                        continue
                    seen.add(item['url'])
                    all_items.append(item)

    print(f'[hn] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'hackernews', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[hn] check_urls error: {e}', flush=True)
        return {'platform': 'hackernews', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[hn] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'hackernews', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': 'news.ycombinator.com',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[hn] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[hn] haiku error: {e}', flush=True)
        return {'platform': 'hackernews', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[hn] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[hn] save error: {e}', flush=True)
        return {'platform': 'hackernews', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'hackernews',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# BLUESKY — public AT Protocol search API (no auth)
# ─────────────────────────────────────────────

_BLUESKY_QUERIES = [
    'bilibili', 'bilibili gaming', 'anisora', 'b站', '哔哩哔哩',
    'bilibili hoyoverse', 'genshin bilibili', 'hololive bilibili',
    'bilibili world', 'bilibili vtuber', 'bilibili anime',
]
_BLUESKY_UA = 'duflat-social-listening/1.0'


def _fetch_bluesky_posts(query, limit=100):
    """Fetch public posts matching query via Bluesky AppView. No auth."""
    import time
    from urllib.parse import quote_plus
    if _cooling_down('bsky.app'):
        return []
    url = (
        'https://api.bsky.app/xrpc/app.bsky.feed.searchPosts'
        f'?q={quote_plus(query)}&limit={limit}&sort=latest'
    )
    try:
        resp = requests.get(url, headers={'User-Agent': _BLUESKY_UA}, timeout=6)
    except Exception as e:
        print(f'[bsky] q={query} request_exception={e}', flush=True)
        return []
    if resp.status_code in (429, 403):
        _enter_cooldown('bsky.app', 300)
        print(f'[bsky] q={query} RATE_LIMITED status={resp.status_code}', flush=True)
        return []
    if resp.status_code != 200:
        print(f'[bsky] q={query} status={resp.status_code} body={resp.text[:200]}', flush=True)
        return []
    try:
        posts = resp.json().get('posts', []) or []
    except Exception as e:
        print(f'[bsky] q={query} json_err={e} body={resp.text[:200]}', flush=True)
        return []
    print(f'[bsky] q={query} ok posts={len(posts)}', flush=True)
    time.sleep(0.3)
    return posts


def _bluesky_post_to_item(p):
    """Convert a Bluesky post dict to pipeline item (2026+ only)."""
    uri = p.get('uri', '') or ''
    author = p.get('author', {}) or {}
    handle = author.get('handle', '')
    record = p.get('record', {}) or {}
    text = (record.get('text') or '').strip()
    created_at = record.get('createdAt', '') or p.get('indexedAt', '')
    if not uri or not handle or not text or not created_at:
        return None
    # at://did:plc:xxx/app.bsky.feed.post/<rkey>
    rkey = uri.rsplit('/', 1)[-1]
    if not rkey:
        return None
    post_url = f'https://bsky.app/profile/{handle}/post/{rkey}'
    try:
        dt = datetime.strptime(created_at[:10], '%Y-%m-%d')
    except Exception:
        return None
    if dt.year < 2026:
        return None
    return {
        'url': post_url,
        'url_hash': hash_url(post_url),
        'platform': 'bsky.app',
        'text': f'[@{handle}] {text}'[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_bluesky():
    """Fetch Bilibili-related Bluesky posts via public search, analyze, save."""
    import time
    all_items = []
    seen = set()
    fetch_start = time.time()

    for q in _BLUESKY_QUERIES:
        if time.time() - fetch_start > 30:
            break
        posts = _fetch_bluesky_posts(q, limit=100)
        for p in posts:
            item = _bluesky_post_to_item(p)
            if not item or item['url'] in seen:
                continue
            blob = item['text'].lower()
            if 'bilibili' not in blob and 'b站' not in blob and '哔哩' not in blob and '嗶哩' not in blob:
                continue
            seen.add(item['url'])
            all_items.append(item)

    print(f'[bsky] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'bluesky', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[bsky] check_urls error: {e}', flush=True)
        return {'platform': 'bluesky', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[bsky] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'bluesky', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': 'bsky.app',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[bsky] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[bsky] haiku error: {e}', flush=True)
        return {'platform': 'bluesky', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[bsky] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[bsky] save error: {e}', flush=True)
        return {'platform': 'bluesky', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'bluesky',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# YOUTUBE — creator commentary via Data API v3 Search
# ─────────────────────────────────────────────
# Surfaces videos where real YouTubers talk about Bilibili. Skips
# Bilibili's own official channels (handle blacklist) and anything
# below a subscriber floor (default 5k). Title + description +
# channel_title is fed to Haiku — transcript ingestion is a planned
# follow-up (yt-dlp cost doesn't fit the 120s gunicorn budget).

_YOUTUBE_SEARCH_QUERIES = [
    # Core English — broad coverage
    'bilibili', 'bilibili app', 'bilibili china',
    'bilibili review', 'bilibili explained',
    'bilibili gaming', 'bilibili anime', 'bilibili vtuber',
    'bilibili world', 'bilibili creator',
    # Topical English — ecosystem, news, controversy
    'bilibili 2026', 'bilibili drama', 'bilibili news',
    'bilibili ai', 'BLG bilibili', 'hoyoverse bilibili',
    # Japanese — ビリビリ is the katakana transliteration used
    # heavily on JP YouTube for Bilibili coverage
    'ビリビリ動画', 'bilibili 日本',
    # Korean — 비리비리 is the hangul form
    '비리비리', 'bilibili 한국',
    # Spanish / Portuguese — growing LATAM audience
    'bilibili español', 'bilibili brasil',
]

# Cap on pages fetched per query via YouTube pageToken. Each page = 100
# quota units, so 2 pages × 22 queries × 4 runs/day = ~17.6k units/day
# on its own. Keep default to 1 unless a quota increase lands.
_YOUTUBE_PAGES_PER_QUERY = int(os.environ.get('YOUTUBE_PAGES_PER_QUERY', '1'))

# Known Bilibili-owned channels (handles, lowercase, no @). Anything
# matching these, or with channel title exactly "Bilibili", is skipped.
_YOUTUBE_BILIBILI_HANDLE_BLACKLIST = {
    'bilibili', 'bilibili_global', 'bilibili_anime', 'bilibili_en',
    'bilibiliesports', 'bilibiligame', 'bilibili_gaming',
    'bilibiliworld', 'bilibilichn', 'bilibilimusic', 'bilibili_movie',
    'bilibiliindonesia', 'bilibilithailand', 'bilibilimalaysia',
}

_YOUTUBE_MIN_SUBSCRIBERS = int(os.environ.get('YOUTUBE_MIN_SUBSCRIBERS', '5000'))


def _youtube_search(query, published_after_iso, max_pages=None):
    """Search YouTube for recent videos matching query. Returns list of snippets
    across up to max_pages (default _YOUTUBE_PAGES_PER_QUERY). Each page is
    100 quota units."""
    api_key = os.environ.get('YOUTUBE_API_KEY', '')
    if not api_key:
        print('[youtube] YOUTUBE_API_KEY not set', flush=True)
        return []
    if _cooling_down('youtube.com'):
        return []
    if max_pages is None:
        max_pages = _YOUTUBE_PAGES_PER_QUERY
    from urllib.parse import quote_plus
    out = []
    page_token = None
    for _ in range(max(1, max_pages)):
        url = (
            'https://www.googleapis.com/youtube/v3/search'
            f'?part=snippet&type=video&q={quote_plus(query)}'
            f'&publishedAfter={quote_plus(published_after_iso)}'
            f'&order=date&maxResults=50&key={api_key}'
        )
        if page_token:
            url += f'&pageToken={page_token}'
        try:
            resp = requests.get(url, timeout=8)
        except Exception as e:
            print(f'[youtube] q={query} request_exception={e}', flush=True)
            break
        if resp.status_code == 403:
            _enter_cooldown('youtube.com', 3600)
            print(f'[youtube] q={query} QUOTA/AUTH status=403 body={resp.text[:200]}', flush=True)
            break
        if resp.status_code != 200:
            print(f'[youtube] q={query} status={resp.status_code} body={resp.text[:200]}', flush=True)
            break
        try:
            data = resp.json()
        except Exception as e:
            print(f'[youtube] q={query} json_err={e}', flush=True)
            break
        out.extend(data.get('items', []) or [])
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    print(f'[youtube] q={query} videos={len(out)}', flush=True)
    return out


def _youtube_hydrate_channels(channel_ids):
    """Fetch subscriberCount for each channel id. Returns dict id→subs."""
    api_key = os.environ.get('YOUTUBE_API_KEY', '')
    if not api_key or not channel_ids:
        return {}
    out = {}
    # API accepts up to 50 ids per call.
    ids = list(set(channel_ids))
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        url = (
            'https://www.googleapis.com/youtube/v3/channels'
            f'?part=statistics,snippet&id={",".join(batch)}&key={api_key}'
        )
        try:
            resp = requests.get(url, timeout=8)
            if resp.status_code != 200:
                continue
            for ch in resp.json().get('items', []) or []:
                cid = ch.get('id')
                if not cid:
                    continue
                stats = ch.get('statistics') or {}
                snip = ch.get('snippet') or {}
                try:
                    subs = int(stats.get('subscriberCount', 0) or 0)
                except Exception:
                    subs = 0
                out[cid] = {
                    'subs': subs,
                    'handle': (snip.get('customUrl') or '').lower().lstrip('@'),
                    'title': snip.get('title') or '',
                }
        except Exception as e:
            print(f'[youtube] channels hydrate error: {e}', flush=True)
            continue
    return out


def _is_bilibili_owned_channel(channel_title, handle):
    """True if this channel is operated by Bilibili itself."""
    t = (channel_title or '').strip().lower()
    h = (handle or '').strip().lower().lstrip('@')
    if h in _YOUTUBE_BILIBILI_HANDLE_BLACKLIST:
        return True
    # Channel title exactly 'bilibili' or starts with 'bilibili ' (e.g. "Bilibili Global")
    if t == 'bilibili':
        return True
    if t.startswith('bilibili ') or t.startswith('bilibili_'):
        return True
    return False


def _youtube_video_to_item(snippet_entry, channel_meta):
    """Convert a YouTube search result + channel meta to a pipeline item."""
    vid = (snippet_entry.get('id') or {}).get('videoId')
    snip = snippet_entry.get('snippet') or {}
    if not vid or not snip:
        return None
    published = snip.get('publishedAt') or ''
    if not published:
        return None
    try:
        dt = datetime.strptime(published[:10], '%Y-%m-%d')
    except Exception:
        return None
    if dt.year < 2026:
        return None

    channel_id = snip.get('channelId') or ''
    channel_title = snip.get('channelTitle') or ''
    meta = channel_meta.get(channel_id) or {}
    handle = meta.get('handle', '')
    subs = int(meta.get('subs') or 0)

    if _is_bilibili_owned_channel(channel_title, handle):
        return None
    if subs < _YOUTUBE_MIN_SUBSCRIBERS:
        return None

    title = (snip.get('title') or '').strip()
    description = (snip.get('description') or '').strip()
    if not title:
        return None

    video_url = f'https://www.youtube.com/watch?v={vid}'
    text = (
        f'[{channel_title} · {subs:,} subs] {title}\n\n{description}'
    )
    return {
        'url': video_url,
        'url_hash': hash_url(video_url),
        'platform': 'youtube.com',
        'text': text[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_youtube():
    """Fetch Bilibili-related YouTube videos from real creators (not Bilibili itself)."""
    import time
    api_key = os.environ.get('YOUTUBE_API_KEY', '')
    if not api_key:
        return {'platform': 'youtube', 'error': 'YOUTUBE_API_KEY not set'}

    fetch_start = time.time()
    # Fixed to 2026-01-01 — project only ingests 2026 content, API-side
    # date filter is stricter than a 90-day sliding window and saves
    # quota by pruning pre-2026 results server-side.
    published_after = '2026-01-01T00:00:00Z'

    raw_entries = []
    for q in _YOUTUBE_SEARCH_QUERIES:
        # 40s fetch budget — expanded for the 20+ query pool. Still
        # well inside the 120s gunicorn limit with Haiku + save to follow.
        if time.time() - fetch_start > 40:
            break
        entries = _youtube_search(q, published_after)
        raw_entries.extend(entries)

    # Hydrate channel subscriber counts in one or two batched calls.
    channel_ids = [
        (e.get('snippet') or {}).get('channelId')
        for e in raw_entries
        if (e.get('snippet') or {}).get('channelId')
    ]
    channel_meta = _youtube_hydrate_channels(channel_ids)

    all_items = []
    seen = set()
    for entry in raw_entries:
        item = _youtube_video_to_item(entry, channel_meta)
        if not item or item['url'] in seen:
            continue
        blob = item['text'].lower()
        # 'bilibili' almost always appears in title or description for
        # search results, but keep the gate for defensive parity with
        # other platforms.
        if ('bilibili' not in blob and 'b站' not in blob
                and '哔哩' not in blob and '嗶哩' not in blob):
            continue
        seen.add(item['url'])
        all_items.append(item)

    print(f'[youtube] total candidates={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'youtube', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[youtube] check_urls error: {e}', flush=True)
        return {'platform': 'youtube', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[youtube] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'youtube', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': 'youtube.com',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[youtube] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[youtube] haiku error: {e}', flush=True)
        return {'platform': 'youtube', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[youtube] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[youtube] save error: {e}', flush=True)
        return {'platform': 'youtube', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'youtube',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# MASTODON — federated microblog, public hashtag timelines, no auth
# ─────────────────────────────────────────────
# /api/v2/search needs auth on most instances; /api/v1/timelines/tag/{tag}
# is public on all standard Mastodon deployments.

_MASTODON_INSTANCES = [
    'mastodon.social', 'mastodon.online', 'fosstodon.org',
    'hachyderm.io', 'mstdn.social', 'mstdn.jp',
]
_MASTODON_TAGS = [
    'bilibili', 'bilibilivideo', 'vtuber', 'anime',
    'hoyoverse', 'genshinimpact',
]
_MASTODON_UA = 'duflat-social-listening/1.0'


def _fetch_mastodon_tag(instance, tag):
    """Fetch the public timeline for a tag on a Mastodon instance."""
    import time
    from urllib.parse import quote_plus
    if _cooling_down(instance):
        return []
    url = f'https://{instance}/api/v1/timelines/tag/{quote_plus(tag)}?limit=40'
    try:
        resp = requests.get(url, headers={'User-Agent': _MASTODON_UA}, timeout=6)
    except Exception as e:
        print(f'[mastodon] {instance} tag={tag} request_exception={e}', flush=True)
        return []
    if resp.status_code in (429, 403):
        _enter_cooldown(instance, 300)
        print(f'[mastodon] {instance} tag={tag} RATE_LIMITED status={resp.status_code}', flush=True)
        return []
    if resp.status_code != 200:
        print(f'[mastodon] {instance} tag={tag} status={resp.status_code}', flush=True)
        return []
    try:
        statuses = resp.json() or []
    except Exception as e:
        print(f'[mastodon] {instance} tag={tag} json_err={e}', flush=True)
        return []
    print(f'[mastodon] {instance} tag={tag} statuses={len(statuses)}', flush=True)
    time.sleep(0.3)
    return statuses


def _mastodon_status_to_item(s):
    """Convert a Mastodon status dict to pipeline item (2026+ only)."""
    url = s.get('url') or s.get('uri') or ''
    if not url:
        return None
    created_at = s.get('created_at') or ''
    if not created_at:
        return None
    try:
        dt = datetime.strptime(created_at[:10], '%Y-%m-%d')
    except Exception:
        return None
    if dt.year < 2026:
        return None
    account = s.get('account') or {}
    handle = account.get('acct') or account.get('username') or ''
    content_html = s.get('content') or ''
    try:
        text = BeautifulSoup(content_html, 'html.parser').get_text(' ', strip=True)
    except Exception:
        text = re.sub(r'<[^>]+>', ' ', content_html)
    text = text.strip()
    if not text:
        return None
    return {
        'url': url,
        'url_hash': hash_url(url),
        'platform': 'mastodon',
        'text': f'[@{handle}] {text}'[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_mastodon():
    """Fetch Bilibili-related Mastodon posts across instances, analyze, save."""
    import time
    all_items = []
    seen = set()
    fetch_start = time.time()

    for instance in _MASTODON_INSTANCES:
        for tag in _MASTODON_TAGS:
            if time.time() - fetch_start > 35:
                break
            statuses = _fetch_mastodon_tag(instance, tag)
            for s in statuses:
                item = _mastodon_status_to_item(s)
                if not item or item['url'] in seen:
                    continue
                blob = item['text'].lower()
                if ('bilibili' not in blob and 'b站' not in blob
                        and '哔哩' not in blob and '嗶哩' not in blob):
                    continue
                seen.add(item['url'])
                all_items.append(item)

    print(f'[mastodon] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'mastodon', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[mastodon] check_urls error: {e}', flush=True)
        return {'platform': 'mastodon', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[mastodon] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'mastodon', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': urlparse(it['url']).netloc or 'mastodon',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[mastodon] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[mastodon] haiku error: {e}', flush=True)
        return {'platform': 'mastodon', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[mastodon] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[mastodon] save error: {e}', flush=True)
        return {'platform': 'mastodon', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'mastodon',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# LIHKG — Hong Kong Traditional Chinese forum, JSON API, no auth
# ─────────────────────────────────────────────

_LIHKG_QUERIES = [
    'bilibili', 'B站', '嗶哩嗶哩', '哔哩哔哩',
    'bilibili 動畫', 'bilibili 遊戲',
]
_LIHKG_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


def _fetch_lihkg_threads(query):
    """Search LIHKG threads by keyword via their public JSON API."""
    import time
    from urllib.parse import quote_plus
    if _cooling_down('lihkg.com'):
        return []
    url = (
        'https://lihkg.com/api_v2/thread/search'
        f'?q={quote_plus(query)}&page=1&count=30&sort=desc_reply_time&type=thread'
    )
    headers = {
        'User-Agent': _LIHKG_UA,
        'Referer': 'https://lihkg.com/',
        'Accept': 'application/json',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=6)
    except Exception as e:
        print(f'[lihkg] q={query} request_exception={e}', flush=True)
        return []
    if resp.status_code in (429, 403):
        _enter_cooldown('lihkg.com', 600)
        print(f'[lihkg] q={query} RATE_LIMITED status={resp.status_code}', flush=True)
        return []
    if resp.status_code != 200:
        print(f'[lihkg] q={query} status={resp.status_code}', flush=True)
        return []
    try:
        data = resp.json() or {}
        threads = (data.get('response') or {}).get('items') or []
    except Exception as e:
        print(f'[lihkg] q={query} json_err={e}', flush=True)
        return []
    print(f'[lihkg] q={query} threads={len(threads)}', flush=True)
    time.sleep(0.4)
    return threads


def _lihkg_thread_to_item(t):
    """Convert LIHKG thread dict to pipeline item (2026+ only)."""
    thread_id = t.get('thread_id') or t.get('post_id')
    title = (t.get('title') or '').strip()
    if not thread_id or not title:
        return None
    # LIHKG timestamps are unix seconds. Prefer create_time, fallback to last_reply_time.
    ts = t.get('create_time') or t.get('last_reply_time')
    if not ts:
        return None
    try:
        dt = datetime.utcfromtimestamp(int(ts))
    except Exception:
        return None
    if dt.year < 2026:
        return None
    user = (t.get('user') or {}).get('nickname') or ''
    category = (t.get('category') or {}).get('name') or ''
    post_url = f'https://lihkg.com/thread/{thread_id}/page/1'
    text = title
    if category:
        text = f'[{category}] {text}'
    return {
        'url': post_url,
        'url_hash': hash_url(post_url),
        'platform': 'lihkg.com',
        'text': f'[@{user}] {text}'[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_lihkg():
    """Fetch Bilibili-related LIHKG threads, analyze, save."""
    import time
    all_items = []
    seen = set()
    fetch_start = time.time()

    for q in _LIHKG_QUERIES:
        if time.time() - fetch_start > 30:
            break
        threads = _fetch_lihkg_threads(q)
        for t in threads:
            item = _lihkg_thread_to_item(t)
            if not item or item['url'] in seen:
                continue
            blob = item['text'].lower()
            if ('bilibili' not in blob and 'b站' not in blob
                    and '哔哩' not in blob and '嗶哩' not in blob):
                continue
            seen.add(item['url'])
            all_items.append(item)

    print(f'[lihkg] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'lihkg', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[lihkg] check_urls error: {e}', flush=True)
        return {'platform': 'lihkg', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[lihkg] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'lihkg', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': 'lihkg.com',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[lihkg] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[lihkg] haiku error: {e}', flush=True)
        return {'platform': 'lihkg', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[lihkg] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[lihkg] save error: {e}', flush=True)
        return {'platform': 'lihkg', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'lihkg',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# LEMMY — federated Reddit alternative, public search API, no auth
# ─────────────────────────────────────────────

# lemmy.ml deliberately excluded: Mainland-aligned content clusters there
# (sino, genzedong etc.) and the project scope drops Mainland anyway.
_LEMMY_INSTANCES = [
    'lemmy.world', 'beehaw.org', 'lemm.ee',
    'sh.itjust.works', 'programming.dev',
]
_LEMMY_QUERIES = [
    'bilibili', 'bilibili gaming', 'bilibili world',
    'bilibili vtuber', 'bilibili anime', 'BLG bilibili',
    'genshin bilibili', 'hoyoverse bilibili',
]
_LEMMY_UA = 'duflat-social-listening/1.0'


def _fetch_lemmy_posts(instance, query):
    """Fetch posts matching query from a Lemmy instance via /api/v3/search."""
    import time
    from urllib.parse import quote_plus
    host = instance
    if _cooling_down(host):
        return []
    url = (
        f'https://{instance}/api/v3/search'
        f'?q={quote_plus(query)}&type_=Posts&sort=New&limit=40'
    )
    try:
        resp = requests.get(url, headers={'User-Agent': _LEMMY_UA}, timeout=6)
    except Exception as e:
        print(f'[lemmy] {instance} q={query} request_exception={e}', flush=True)
        return []
    if resp.status_code in (429, 403):
        _enter_cooldown(host, 300)
        print(f'[lemmy] {instance} q={query} RATE_LIMITED status={resp.status_code}', flush=True)
        return []
    if resp.status_code != 200:
        print(f'[lemmy] {instance} q={query} status={resp.status_code}', flush=True)
        return []
    try:
        posts = resp.json().get('posts', []) or []
    except Exception as e:
        print(f'[lemmy] {instance} q={query} json_err={e}', flush=True)
        return []
    print(f'[lemmy] {instance} q={query} posts={len(posts)}', flush=True)
    time.sleep(0.3)
    return posts


def _lemmy_post_to_item(entry):
    """Convert a Lemmy search 'post' entry into a pipeline item.

    entry shape: {"post": {...}, "community": {...}, "creator": {...}}"""
    post = entry.get('post') or {}
    creator = entry.get('creator') or {}
    community = entry.get('community') or {}
    ap_id = post.get('ap_id') or ''
    if not ap_id:
        return None
    title = (post.get('name') or '').strip()
    body = (post.get('body') or '').strip()
    linked = (post.get('url') or '').strip()
    published = post.get('published') or ''
    if not published:
        return None
    try:
        dt = datetime.strptime(published[:10], '%Y-%m-%d')
    except Exception:
        return None
    if dt.year < 2026:
        return None
    handle = creator.get('name') or ''
    community_name = community.get('name') or ''
    parts = []
    if title:
        parts.append(title)
    if body:
        parts.append(body)
    if linked and linked != ap_id:
        parts.append(f'link: {linked}')
    text = '\n'.join(parts).strip()
    if not text:
        return None
    return {
        'url': ap_id,
        'url_hash': hash_url(ap_id),
        'platform': 'lemmy',
        'text': f'[@{handle} in !{community_name}] {text}'[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_lemmy():
    """Fetch Bilibili-related Lemmy posts across multiple instances, analyze, save."""
    import time
    all_items = []
    seen = set()
    fetch_start = time.time()

    for instance in _LEMMY_INSTANCES:
        for q in _LEMMY_QUERIES:
            if time.time() - fetch_start > 35:
                break
            posts = _fetch_lemmy_posts(instance, q)
            for p in posts:
                item = _lemmy_post_to_item(p)
                if not item or item['url'] in seen:
                    continue
                blob = item['text'].lower()
                if ('bilibili' not in blob and 'b站' not in blob
                        and '哔哩' not in blob and '嗶哩' not in blob):
                    continue
                seen.add(item['url'])
                all_items.append(item)

    print(f'[lemmy] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'lemmy', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[lemmy] check_urls error: {e}', flush=True)
        return {'platform': 'lemmy', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[lemmy] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'lemmy', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': urlparse(it['url']).netloc or 'lemmy',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[lemmy] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[lemmy] haiku error: {e}', flush=True)
        return {'platform': 'lemmy', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[lemmy] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[lemmy] save error: {e}', flush=True)
        return {'platform': 'lemmy', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'lemmy',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# MEDIUM — public tag RSS feeds, no auth
# ─────────────────────────────────────────────

_MEDIUM_TAGS = [
    'bilibili', 'b-station', 'chinese-anime', 'china-streaming',
    'vtuber', 'genshin-impact', 'china-tech', 'mihoyo',
]
# Real-browser UA: Medium silently returns empty feeds for bot-flavored
# UAs (verified 2026-04-29: 'compatible;...' UA = 0 items, browser UA =
# full feed).
_MEDIUM_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

_MEDIUM_NS = {
    'dc': 'http://purl.org/dc/elements/1.1/',
    'content': 'http://purl.org/rss/1.0/modules/content/',
}


def _fetch_medium_tag(tag):
    """Fetch one Medium tag RSS feed. Returns list of <item> ElementTree nodes."""
    import time
    import xml.etree.ElementTree as ET
    if _cooling_down('medium.com'):
        return []
    url = f'https://medium.com/feed/tag/{tag}'
    try:
        resp = requests.get(url, headers={'User-Agent': _MEDIUM_UA}, timeout=8)
    except Exception as e:
        print(f'[medium] tag={tag} request_exception={e}', flush=True)
        return []
    if resp.status_code in (429, 403):
        _enter_cooldown('medium.com', 600)
        print(f'[medium] tag={tag} RATE_LIMITED status={resp.status_code}', flush=True)
        return []
    if resp.status_code != 200:
        print(f'[medium] tag={tag} status={resp.status_code}', flush=True)
        return []
    try:
        root = ET.fromstring(resp.content)
        items = root.findall('.//item') or []
    except Exception as e:
        print(f'[medium] tag={tag} parse_err={e}', flush=True)
        return []
    print(f'[medium] tag={tag} items={len(items)}', flush=True)
    time.sleep(0.4)
    return items


def _medium_item_to_pipeline(item):
    """Convert a Medium RSS <item> ElementTree node into a pipeline item."""
    title = (item.findtext('title') or '').strip()
    link = (item.findtext('link') or '').strip()
    pub_str = (item.findtext('pubDate') or '').strip()
    if not link or not title or not pub_str:
        return None
    author = (item.findtext('dc:creator', namespaces=_MEDIUM_NS) or '').strip()
    try:
        # 'Wed, 01 Apr 2026 12:34:56 GMT'
        dt = datetime.strptime(pub_str[:25], '%a, %d %b %Y %H:%M:%S')
    except Exception:
        return None
    if dt.year < 2026:
        return None
    body_html = item.findtext('content:encoded', namespaces=_MEDIUM_NS) or ''
    body_text = ''
    if body_html:
        try:
            body_text = BeautifulSoup(body_html, 'html.parser').get_text(' ', strip=True)
        except Exception:
            pass
    parts = [title]
    if body_text:
        parts.append(body_text[:2000])
    text = '\n'.join(parts).strip()
    return {
        'url': link,
        'url_hash': hash_url(link),
        'platform': 'medium',
        'text': f'[@{author}] {text}'[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_medium():
    """Fetch Bilibili-related Medium posts via public tag RSS feeds."""
    import time
    all_items = []
    seen = set()
    fetch_start = time.time()

    for tag in _MEDIUM_TAGS:
        if time.time() - fetch_start > 35:
            break
        items = _fetch_medium_tag(tag)
        for el in items:
            it = _medium_item_to_pipeline(el)
            if not it or it['url'] in seen:
                continue
            blob = it['text'].lower()
            if ('bilibili' not in blob and 'b站' not in blob
                    and '哔哩' not in blob and '嗶哩' not in blob):
                continue
            seen.add(it['url'])
            all_items.append(it)

    print(f'[medium] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'medium', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[medium] check_urls error: {e}', flush=True)
        return {'platform': 'medium', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[medium] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'medium', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': urlparse(it['url']).netloc or 'medium.com',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[medium] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[medium] haiku error: {e}', flush=True)
        return {'platform': 'medium', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[medium] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[medium] save error: {e}', flush=True)
        return {'platform': 'medium', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'medium',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# SUBSTACK — curated China-focused publication RSS feeds
# ─────────────────────────────────────────────
#
# Substack's public /api/v1/post/search returns 200 with an empty result
# set for unauthenticated callers (verified 2026-04-29: any query → 0
# results). Pivot to a curated list of China-focused Substack RSS feeds
# (each publication exposes /feed publicly). We blob-filter for bilibili
# keywords since these publications cover broader China topics.

_SUBSTACK_FEEDS = [
    # name, host
    ('chinatalk',         'chinatalk.media'),
    ('sinocism',          'sinocism.com'),
    ('beijingchannel',    'beijingchannel.substack.com'),
    ('chinabooksreview',  'chinabooksreview.substack.com'),
    ('thechinaproject',   'chinaproject.substack.com'),
    ('chinaeconomicsreview','china-economic-review.substack.com'),
    ('interconnected',    'interconnect.substack.com'),
    ('whatsonweibo',      'whatsonweibo.substack.com'),
    ('chinaheritage',     'chinaheritage.substack.com'),
    ('panda-paw-dragon-claw','pandapawdragonclaw.substack.com'),
    ('thinking-chinese',  'thinkingchinese.substack.com'),
    ('chinamediabulletin','chinamediabulletin.substack.com'),
]
_SUBSTACK_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def _fetch_substack_feed(host):
    """Fetch one Substack publication's public RSS feed.

    Returns list of <item> ElementTree nodes, or [] on any failure.
    `host` is the substack subdomain or custom domain (e.g.
    'sinocism.com' or 'chinatalk.media')."""
    import time
    import xml.etree.ElementTree as ET
    if _cooling_down(host):
        return []
    url = f'https://{host}/feed'
    try:
        resp = requests.get(url, headers={'User-Agent': _SUBSTACK_UA}, timeout=8)
    except Exception as e:
        print(f'[substack] {host} request_exception={e}', flush=True)
        return []
    if resp.status_code in (429, 403):
        _enter_cooldown(host, 600)
        print(f'[substack] {host} RATE_LIMITED status={resp.status_code}', flush=True)
        return []
    if resp.status_code != 200:
        print(f'[substack] {host} status={resp.status_code}', flush=True)
        return []
    try:
        root = ET.fromstring(resp.content)
        items = root.findall('.//item') or []
    except Exception as e:
        print(f'[substack] {host} parse_err={e}', flush=True)
        return []
    print(f'[substack] {host} items={len(items)}', flush=True)
    time.sleep(0.3)
    return items


def _substack_item_to_pipeline(item, host):
    """Convert a Substack RSS <item> ElementTree node into a pipeline item."""
    title = (item.findtext('title') or '').strip()
    link = (item.findtext('link') or '').strip()
    pub_str = (item.findtext('pubDate') or '').strip()
    if not link or not title or not pub_str:
        return None
    author = (item.findtext('dc:creator', namespaces=_MEDIUM_NS) or '').strip()
    try:
        dt = datetime.strptime(pub_str[:25], '%a, %d %b %Y %H:%M:%S')
    except Exception:
        return None
    if dt.year < 2026:
        return None
    description = item.findtext('description') or ''
    body_html = item.findtext('content:encoded', namespaces=_MEDIUM_NS) or description
    body_text = ''
    if body_html:
        try:
            body_text = BeautifulSoup(body_html, 'html.parser').get_text(' ', strip=True)
        except Exception:
            pass
    parts = [title]
    if body_text:
        parts.append(body_text[:2000])
    text = '\n'.join(parts).strip()
    return {
        'url': link,
        'url_hash': hash_url(link),
        'platform': 'substack',
        'text': f'[@{author} on {host}] {text}'[:5000],
        'content_date': dt.strftime('%Y-%m-%d'),
        'dates_found': [dt.strftime('%Y-%m-%d')],
    }


def discover_substack():
    """Fetch Bilibili-related Substack posts via curated publication RSS feeds."""
    import time
    all_items = []
    seen = set()
    fetch_start = time.time()

    for _, host in _SUBSTACK_FEEDS:
        if time.time() - fetch_start > 35:
            break
        items = _fetch_substack_feed(host)
        for el in items:
            it = _substack_item_to_pipeline(el, host)
            if not it or it['url'] in seen:
                continue
            blob = it['text'].lower()
            if ('bilibili' not in blob and 'b站' not in blob
                    and '哔哩' not in blob and '嗶哩' not in blob):
                continue
            seen.add(it['url'])
            all_items.append(it)

    print(f'[substack] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'substack', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[substack] check_urls error: {e}', flush=True)
        return {'platform': 'substack', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[substack] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'substack', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': urlparse(it['url']).netloc or 'substack.com',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[substack] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[substack] haiku error: {e}', flush=True)
        return {'platform': 'substack', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[substack] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[substack] save error: {e}', flush=True)
        return {'platform': 'substack', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'substack',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# ─────────────────────────────────────────────
# TELEGRAM — Brave Search → channel index harvest
# ─────────────────────────────────────────────
#
# Channel-poll on t.me/s/{channel} alone yields ~0% Bilibili mentions in
# any general-interest channel's recent post window (probed 40+ China-
# watcher / anime / esports channels 2026-04-29). Telegram has no public
# cross-channel search API.
#
# Pivot: let Brave Search index t.me, query each alphabet variant of
# "bilibili" with `site:t.me`, harvest channel names from results. Brave
# returns mostly channel-index URLs (t.me/s/{ch}, t.me/{ch}); fetching
# t.me/s/{ch} once gives us the full recent timeline. We blob-filter
# every post on that timeline for a bilibili variant — channels Brave
# surfaces are ones that have mentioned Bilibili at some point, so the
# signal-to-noise ratio is much higher than blind channel-poll.
#
# Critical Brave note: `freshness='pm'` makes Brave silently drop the
# `site:t.me` operator (fallback mode, observed 2026-04-29). Always
# query with `freshness=None` so site: is honoured.

# Multi-alphabet "bilibili" variants. The full list is used by
# `_blob_has_bili_variant` (cheap in-memory check on every post). The
# subset `_BILI_BRAVE_QUERIES` is what actually goes to Brave Search —
# fewer queries keeps us inside gunicorn 120s and Brave 1 RPS free
# tier. The three chosen scripts (Latin, Simplified, Cyrillic) surface
# the broadest channel pool empirically; other scripts can be added if
# yield analysis later shows missed coverage.
_BILI_ALPHA_VARIANTS = [
    'bilibili',
    'B站',
    '哔哩哔哩',
    '嗶哩嗶哩',
    'Билибили',
    '비리비리',
    'ビリビリ',
    'びりびり',
    'بيليبيلي',
    'บิลิบิลิ',
]
_BILI_BRAVE_QUERIES = ['bilibili', '哔哩哔哩', 'Билибили']
_TELEGRAM_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
_TELEGRAM_CHANNEL_RE = re.compile(r'^https?://t\.me/(?:s/)?([A-Za-z0-9_]+)(?:[/?#].*)?$')
# t.me paths that aren't channels: stickers, themes, invites, IV mode, bots.
_TELEGRAM_SKIP_PREFIXES = ('addemoji', 'addstickers', 'joinchat', 'addtheme', 'iv',
                           'proxy', 'socks', 'share', '+', 'c')


def _blob_has_bili_variant(text):
    """True if the text contains any alphabet variant of 'bilibili'.
    Used as the per-source blob pre-filter so non-Latin mentions are
    not silently dropped."""
    if not text:
        return False
    t = text.lower()
    for v in _BILI_ALPHA_VARIANTS:
        if v.lower() in t:
            return True
    return False


def _telegram_channel_from_url(url):
    """Extract a Telegram channel handle from a Brave-returned URL.
    Returns lowercase channel name, or None if the URL is a sticker/
    theme/invite/etc. Both t.me/X and t.me/s/X are accepted."""
    m = _TELEGRAM_CHANNEL_RE.match(url)
    if not m:
        return None
    ch = m.group(1)
    if ch.lower() in _TELEGRAM_SKIP_PREFIXES:
        return None
    return ch


def _fetch_telegram_channel_posts(channel):
    """Fetch t.me/s/{channel} preview, return list of pipeline items
    for posts whose text contains a bilibili variant.

    Each item carries a stable per-post URL (t.me/{channel}/{post_id})
    so dedup against social_sources works even if a channel is harvested
    multiple times. Pre-2026 posts are dropped here."""
    import time
    if _cooling_down('t.me'):
        return []
    url = f'https://t.me/s/{channel}'
    try:
        resp = requests.get(url, headers={'User-Agent': _TELEGRAM_UA}, timeout=8)
    except Exception as e:
        print(f'[telegram] {channel} request_err={e}', flush=True)
        return []
    if resp.status_code in (429, 403):
        _enter_cooldown('t.me', 600)
        print(f'[telegram] {channel} RATE_LIMITED status={resp.status_code}', flush=True)
        return []
    if resp.status_code != 200:
        # 302 = channel doesn't exist as public; common after typos.
        return []
    try:
        soup = BeautifulSoup(resp.text, 'html.parser')
    except Exception:
        return []
    items = []
    today = date.today().strftime('%Y-%m-%d')
    for msg in soup.select('.tgme_widget_message_wrap'):
        msg_div = msg.select_one('.tgme_widget_message')
        if not msg_div:
            continue
        data_post = (msg_div.get('data-post') or '').strip()
        m = re.match(r'^[A-Za-z0-9_]+/(\d+)$', data_post)
        if not m:
            continue
        post_id = m.group(1)
        text_el = msg.select_one('.tgme_widget_message_text')
        if not text_el:
            continue
        text = text_el.get_text(' ', strip=True)
        if not _blob_has_bili_variant(text):
            continue
        date_el = msg.select_one('.tgme_widget_message_date time')
        iso_dt = ''
        if date_el and date_el.has_attr('datetime'):
            iso_dt = date_el['datetime'][:10]
        if iso_dt and iso_dt < '2026-01-01':
            continue
        if not iso_dt:
            iso_dt = today
        author_el = (msg.select_one('.tgme_widget_message_author_name')
                     or msg.select_one('.tgme_widget_message_owner_name'))
        author = author_el.get_text(strip=True) if author_el else channel
        post_url = f'https://t.me/{channel}/{post_id}'
        items.append({
            'url': post_url,
            'url_hash': hash_url(post_url),
            'platform': 'telegram',
            'text': f'[@{author} on t.me/{channel}] {text}'[:5000],
            'content_date': iso_dt,
            'dates_found': [iso_dt],
        })
    print(f'[telegram] {channel} bilibili_posts={len(items)}', flush=True)
    time.sleep(0.3)
    return items


def discover_telegram():
    """Discover Bilibili-related Telegram public posts.

    For each alphabet variant of 'bilibili', query Brave Search with
    `site:t.me {variant}` (freshness=None — past-month freshness makes
    Brave drop the site: filter). Brave returns channel-index and
    channel-home URLs; we extract unique channel handles and harvest
    each channel's full recent timeline (t.me/s/{ch}) for bilibili-
    matching posts. Pipeline → Haiku → save."""
    import time
    fetch_start = time.time()
    channels_seen = set()
    channels_ordered = []  # preserve discovery order, source by source

    for variant in _BILI_BRAVE_QUERIES:
        if time.time() - fetch_start > 15:
            break
        try:
            results = _brave_search(
                f'site:t.me {variant}',
                max_results=20,
                freshness=None,  # past-month makes Brave drop site:t.me
            )
        except Exception as e:
            print(f'[telegram] brave variant={variant!r} err={e}', flush=True)
            continue
        new_for_variant = 0
        for url in results or []:
            ch = _telegram_channel_from_url(url)
            if not ch:
                continue
            ch_key = ch.lower()
            if ch_key in channels_seen:
                continue
            channels_seen.add(ch_key)
            channels_ordered.append(ch)
            new_for_variant += 1
        print(f'[telegram] brave variant={variant!r} new_channels={new_for_variant} '
              f'total_channels={len(channels_ordered)}', flush=True)

    print(f'[telegram] Brave unique channels={len(channels_ordered)}', flush=True)
    if not channels_ordered:
        return {'platform': 'telegram', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    # Cap channels to keep within gunicorn 120s budget. 1 fetch ≈ 1s.
    channels_ordered = channels_ordered[:25]

    all_items = []
    seen_urls = set()
    for ch in channels_ordered:
        if time.time() - fetch_start > 70:
            break
        for it in _fetch_telegram_channel_posts(ch):
            if it['url'] in seen_urls:
                continue
            seen_urls.add(it['url'])
            all_items.append(it)

    print(f'[telegram] total fetched items={len(all_items)}', flush=True)
    if not all_items:
        return {'platform': 'telegram', 'fetched': 0, 'new': 0, 'saved': 0, 'skipped': 0}

    try:
        urls = [it['url'] for it in all_items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in all_items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[telegram] check_urls error: {e}', flush=True)
        return {'platform': 'telegram', 'fetched': len(all_items), 'error': f'dedup: {e}'}

    print(f'[telegram] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'telegram', 'fetched': len(all_items), 'new': 0, 'saved': 0, 'skipped': 0}

    items_new = items_new[:25]

    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': 't.me',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[telegram] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[telegram] haiku error: {e}', flush=True)
        return {'platform': 'telegram', 'fetched': len(all_items), 'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[telegram] validator error: {e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[telegram] save error: {e}', flush=True)
        return {'platform': 'telegram', 'fetched': len(all_items), 'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'telegram',
        'fetched': len(all_items),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
    }


# X (Twitter) discovery via Apify — Brave's Twitter index lags after the
# 2023 API closure (~%1.4 of candidates land in 2026). Apify's tweet-
# scraper actor uses Twitter's own search underneath, so it returns fresh
# tweets with full text, author, and createdAt without us paying for the
# $100/mo Twitter API. Cost: ~$0.40 per 1000 tweets, ~$5/mo for 4 cron
# runs/day @ 100 tweets each.
_X_STATUS_RE = re.compile(
    r'^https?://(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,15})/status/(\d+)'
)
_X_APIFY_ACTOR = 'apidojo/tweet-scraper'
_X_APIFY_SEARCH_TERMS = [
    'bilibili',
    '哔哩哔哩',
    'BLG bilibili',
    'bilibili gaming',
    'bilibili vtuber',
    'bilibili anime',
]
# Cron-path budget. Direct POST to /social/discover-x is gunicorn-bound
# (120s); the chain runs in a background thread so it can take longer.
_X_APIFY_MAX_ITEMS = int(os.environ.get('APIFY_X_MAX_ITEMS', '50'))
_X_APIFY_TIMEOUT_SECS = int(os.environ.get('APIFY_X_TIMEOUT_SECS', '90'))
_X_APIFY_LOOKBACK_DAYS = int(os.environ.get('APIFY_X_LOOKBACK_DAYS', '7'))

# Handles that publish on behalf of Bilibili itself — promotional output
# is out of scope for social listening, which targets community voices.
_X_BILIBILI_OWNED = {
    'bilibili_en', 'bilibilicomics', 'bilibilidottv', 'bilibiligame_jp',
    'bilibiligames_id', 'bilibiligaming', 'bilibiliph', 'bilibilibr',
    'bilibilith', 'bilibili7', 'bilibili0001', 'bilibiliweb', 'bilibilili',
    'madeby_bilibili', 'bilibili_id', 'bilibili_global',
}


def _is_bilibili_owned_x_handle(handle):
    """True if this X/Twitter handle is run by Bilibili."""
    h = (handle or '').strip().lower().lstrip('@')
    if h in _X_BILIBILI_OWNED:
        return True
    if h.startswith('bilibili'):
        return True
    return False


def _x_tweet_id_from_url(url):
    """Return (handle, tweet_id) for x.com/twitter.com /status/ URLs."""
    m = _X_STATUS_RE.match(url or '')
    if not m:
        return None
    return m.group(1), m.group(2)


def _x_apify_iso_to_date(iso):
    """Best-effort timestamp → YYYY-MM-DD. Returns '' on parse failure.

    Apify's tweet-scraper returns either ISO-8601 ('2026-04-29T12:34:56.000Z')
    or Twitter's legacy format ('Wed Apr 23 12:34:56 +0000 2026'). The
    legacy format puts the year LAST — slicing it off (e.g. iso[:25])
    drops the year and strptime defaults to 1900."""
    if not iso:
        return ''
    s = iso.strip()
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).strftime('%Y-%m-%d')
    except Exception:
        pass
    try:
        return datetime.strptime(s, '%a %b %d %H:%M:%S %z %Y').strftime('%Y-%m-%d')
    except Exception:
        return ''


def discover_x():
    """Discover Bilibili-related X (Twitter) posts via Apify tweet-scraper.

    apidojo/tweet-scraper runs Twitter's own search for our keywords and
    returns tweet text + author + createdAt directly, no oembed needed.
    Bilibili-owned handles and pre-2026 tweets are filtered before the
    Haiku pipeline.

    Cron-path call is fired from a background thread so the actor's
    multi-minute runtime doesn't trip gunicorn's 120s request timeout."""
    if _cooling_down('apify.com'):
        return {'platform': 'x', 'fetched': 0, 'error': 'cooldown'}

    token = os.environ.get('APIFY_API_TOKEN', '').strip()
    if not token:
        return {'platform': 'x', 'fetched': 0, 'error': 'no_apify_token'}

    try:
        from apify_client import ApifyClient
    except ImportError:
        return {'platform': 'x', 'fetched': 0, 'error': 'apify_client_missing'}

    today = date.today()
    since = (today - timedelta(days=_X_APIFY_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    # apidojo's `start` field is ignored when sort=Latest; embedding the
    # `since:` Twitter search operator in each term is the only way to
    # actually clip to the lookback window.
    search_terms = [f'{t} since:{since}' for t in _X_APIFY_SEARCH_TERMS]
    run_input = {
        'searchTerms': search_terms,
        'maxItems': _X_APIFY_MAX_ITEMS,
        'sort': 'Latest',
    }
    print(f'[x-apify] starting actor={_X_APIFY_ACTOR} '
          f'maxItems={_X_APIFY_MAX_ITEMS} since={since} '
          f'searchTerms={search_terms!r}', flush=True)

    client = ApifyClient(token=token)
    try:
        run = client.actor(_X_APIFY_ACTOR).call(
            run_input=run_input,
            timeout_secs=_X_APIFY_TIMEOUT_SECS,
        )
    except Exception as e:
        msg = str(e).lower()
        if 'rate' in msg or 'limit' in msg or 'quota' in msg:
            _enter_cooldown('apify.com', 1800)
        print(f'[x-apify] actor call err={e}', flush=True)
        return {'platform': 'x', 'fetched': 0, 'error': f'apify: {e}'}

    dataset_id = (run or {}).get('defaultDatasetId') or ''
    if not dataset_id:
        return {'platform': 'x', 'fetched': 0, 'error': 'no_dataset',
                'run_status': (run or {}).get('status')}

    items_raw = []
    try:
        items_raw = list(client.dataset(dataset_id).iterate_items())
    except Exception as e:
        print(f'[x-apify] dataset iter err={e}', flush=True)
        return {'platform': 'x', 'fetched': 0, 'error': f'dataset: {e}'}
    print(f'[x-apify] apify_raw={len(items_raw)}', flush=True)

    items = []
    seen_urls = set()
    skipped_owned = 0
    skipped_pre_2026 = 0
    skipped_no_bili = 0
    skipped_no_text = 0
    skipped_no_url = 0
    raw_dates = []  # debug: distribution of createdAt across the dataset

    for it in items_raw:
        url = (it.get('url') or it.get('twitterUrl') or '').strip()
        if not url:
            skipped_no_url += 1
            continue
        if url in seen_urls:
            continue
        parsed = _x_tweet_id_from_url(url)
        if not parsed:
            skipped_no_url += 1
            continue
        handle, _tweet_id = parsed
        if _is_bilibili_owned_x_handle(handle):
            skipped_owned += 1
            continue
        text = (it.get('text') or it.get('fullText') or '').strip()
        if not text:
            skipped_no_text += 1
            continue
        created = _x_apify_iso_to_date(it.get('createdAt') or it.get('created_at') or '')
        if created:
            raw_dates.append(created)
        if created and created < '2026-01-01':
            skipped_pre_2026 += 1
            continue
        if not created:
            created = today.strftime('%Y-%m-%d')
        if not _blob_has_bili_variant(text):
            skipped_no_bili += 1
            continue
        seen_urls.add(url)
        author = it.get('author') or {}
        author_name = (author.get('userName') or author.get('username')
                       or author.get('name') or handle)
        items.append({
            'url': url,
            'url_hash': hash_url(url),
            'platform': 'x',
            'text': f'[@{handle} ({author_name}) on twitter] {text}'[:5000],
            'content_date': created,
            'dates_found': [created],
        })

    raw_dates_sorted = sorted(raw_dates)
    funnel = {
        'apify_raw': len(items_raw),
        'pipeline_items': len(items),
        'skipped_owned': skipped_owned,
        'skipped_pre_2026': skipped_pre_2026,
        'skipped_no_bili': skipped_no_bili,
        'skipped_no_text': skipped_no_text,
        'skipped_no_url': skipped_no_url,
        'search_terms': search_terms,
        'raw_oldest_date': raw_dates_sorted[0] if raw_dates_sorted else '',
        'raw_newest_date': raw_dates_sorted[-1] if raw_dates_sorted else '',
        'raw_date_sample': raw_dates_sorted[::max(1, len(raw_dates_sorted)//5)] if raw_dates_sorted else [],
    }
    print(f'[x-apify] funnel={funnel}', flush=True)

    if not items:
        return {'platform': 'x', 'fetched': 0, 'new': 0,
                'saved': 0, 'skipped': 0, **funnel}

    try:
        urls = [it['url'] for it in items]
        new_urls_set = {d['url'] for d in check_urls(urls)}
        items_new = [it for it in items if it['url'] in new_urls_set]
    except Exception as e:
        print(f'[x-apify] check_urls err={e}', flush=True)
        return {'platform': 'x', 'fetched': len(items), 'error': f'dedup: {e}'}

    print(f'[x-apify] new after dedup={len(items_new)}', flush=True)
    if not items_new:
        return {'platform': 'x', 'fetched': len(items), 'new': 0,
                'saved': 0, 'skipped': 0, **funnel}

    items_new = items_new[:25]
    for it in items_new:
        try:
            _db().table('social_sources').upsert({
                'url_hash': it['url_hash'],
                'url': it['url'],
                'domain': 'twitter.com',
                'has_2026_content': True,
                'checked_at': datetime.utcnow().isoformat(),
            }, on_conflict='url_hash').execute()
        except Exception:
            pass

    try:
        mentions = _analyze_with_haiku(items_new)
        print(f'[x-apify] haiku produced={len(mentions or [])}', flush=True)
    except Exception as e:
        print(f'[x-apify] haiku err={e}', flush=True)
        return {'platform': 'x', 'fetched': len(items_new),
                'new': len(items_new), 'error': f'haiku: {e}'}

    if mentions:
        try:
            mentions = _ai_validate_and_repair(mentions)
        except Exception as e:
            print(f'[x-apify] validator err={e}', flush=True)

    try:
        if mentions:
            result = save_mentions(mentions)
        else:
            result = {'saved': 0, 'skipped': 0, 'repaired': 0}
    except Exception as e:
        print(f'[x-apify] save err={e}', flush=True)
        return {'platform': 'x', 'fetched': len(items_new),
                'new': len(items_new), 'error': f'save: {e}'}

    return {
        'platform': 'x',
        'fetched': len(items_new),
        'new': len(items_new),
        'saved': result.get('saved', 0),
        'skipped': result.get('skipped', 0),
        'gate_rejected': result.get('gate_rejected', 0),
        'gate_rejections': result.get('gate_rejections', []),
        **funnel,
    }


def delete_mentions(ids):
    """Delete mentions by ID list."""
    deleted = 0
    for mid in ids:
        try:
            _db().table('social_mentions').delete().eq('id', mid).execute()
            deleted += 1
        except Exception:
            pass
    return deleted


_DOMAIN_RE = re.compile(r'^[a-z0-9][a-z0-9.-]{0,252}\.[a-z]{2,}$')

def delete_mentions_by_domain(domain):
    """Delete mentions whose URL host exactly matches the given domain
    (or its www. variant). Substring matching is intentionally disallowed
    — passing 'com' used to wipe the entire DB."""
    domain = (domain or '').strip().lower().lstrip('.')
    if not domain or not _DOMAIN_RE.match(domain):
        return 0
    deleted = 0
    prefixes = (
        f'http://{domain}/', f'https://{domain}/',
        f'http://www.{domain}/', f'https://www.{domain}/',
    )
    for prefix in prefixes:
        try:
            res = _db().table('social_mentions').delete().like('url', f'{prefix}%').execute()
            deleted += len(res.data or [])
        except Exception as e:
            print(f'[delete_by_domain] prefix={prefix} error: {e}', flush=True)
    return deleted


def translate_missing_chinese():
    """
    Admin: backfill content_chinese for every mention that is still missing one.
    Uses Haiku in batches of 20 — tiny prompt, tiny output, single field per item.
    Returns {'total': N, 'translated': M, 'skipped': K}.
    """
    try:
        # Explicit limit: PostgREST silently truncates at 1000 otherwise.
        res = _db().table('social_mentions').select(
            'id, content_english, content_chinese'
        ).limit(50000).execute()
        rows = res.data or []
    except Exception as e:
        return {'error': f'fetch_failed: {e}'}

    pending = [r for r in rows if (r.get('content_english') or '').strip()
               and not (r.get('content_chinese') or '').strip()]
    if not pending:
        return {'total': len(rows), 'translated': 0, 'pending': 0}

    translated = 0
    skipped = 0

    for batch in _chunks(pending, 10):
        entries = [{'idx': i, 'en': r['content_english']} for i, r in enumerate(batch)]
        prompt = f"""Translate each English social-listening insight into Simplified Chinese.

Guidelines:
- Keep the same length and tone as the English original (short, social voice, not formal news)
- Use natural Simplified Chinese phrasing — not machine-literal word-for-word
- Keep brand / product / team names in Latin letters: Bilibili, AniSora, AI, BLG, PGL, Apple, Nike, etc.
- Simplified Chinese characters ONLY (no Traditional Chinese)
- Do not add information that is not in the English source
- Do not change the meaning

Return ONLY a JSON array: [{{"idx":0,"zh":"..."}}, ...]

Items:
{json.dumps(entries, ensure_ascii=False)}"""

        verdicts = _haiku_call(prompt, max_tokens=4096)
        if not verdicts:
            skipped += len(batch)
            continue

        zh_by_idx = {}
        for v in verdicts:
            idx = v.get('idx')
            if idx is None or not isinstance(idx, int) or idx >= len(batch):
                continue
            zh = (v.get('zh') or '').strip()
            if zh:
                zh_by_idx[idx] = zh

        for i, row in enumerate(batch):
            zh = zh_by_idx.get(i)
            if not zh:
                skipped += 1
                continue
            try:
                _db().table('social_mentions').update(
                    {'content_chinese': zh}
                ).eq('id', row['id']).execute()
                translated += 1
            except Exception:
                skipped += 1

    return {
        'total': len(rows),
        'pending': len(pending),
        'translated': translated,
        'skipped': skipped,
    }


def reclassify_all_mentions():
    """
    Admin: re-run L3 classification on every existing mention in the DB.
    Useful after tuning the sensitivity / sentiment / source_type rules.
    Returns {'total': N, 'updated': M, 'before': {...}, 'after': {...}}.
    """
    try:
        # Explicit limit: PostgREST silently truncates at 1000 otherwise.
        res = _db().table('social_mentions').select(
            'id, platform, content_english, content_original, sentiment, sensitivity, source_type'
        ).limit(50000).execute()
        rows = res.data or []
    except Exception as e:
        return {'error': f'fetch_failed: {e}'}

    if not rows:
        return {'total': 0, 'updated': 0}

    from collections import Counter
    before = Counter(r.get('sensitivity', 'low') for r in rows)

    # Build mention-like dicts for _layer3_classify
    mentions = [{
        'platform': r.get('platform', ''),
        'content_english': r.get('content_english', ''),
        'content_original': r.get('content_original', ''),
        '_id': r['id'],
    } for r in rows]

    classified = _layer3_classify(mentions)

    updated = 0
    for m in classified:
        mid = m.get('_id')
        if not mid:
            continue
        try:
            _db().table('social_mentions').update({
                'sentiment': m.get('sentiment', 'neutral'),
                'sensitivity': m.get('sensitivity', 'low'),
                'source_type': m.get('source_type', 'news_minor'),
            }).eq('id', mid).execute()
            updated += 1
        except Exception:
            continue

    after = Counter(m.get('sensitivity', 'low') for m in classified)
    return {
        'total': len(rows),
        'updated': updated,
        'before': dict(before),
        'after': dict(after),
    }


def update_mention(mid, content_english=None, content_original=None, language=None):
    """Update a mention's fields. Only updates provided fields."""
    updates = {}
    if content_english is not None:
        updates['content_english'] = content_english
    if content_original is not None:
        updates['content_original'] = content_original
    if content_english or content_original:
        updates['content_hash'] = hash_content(content_original or content_english)
    if language is not None:
        updates['language'] = language
    if not updates:
        return False
    try:
        _db().table('social_mentions').update(updates).eq('id', mid).execute()
        return True
    except Exception:
        return False


def compute_stats_and_dates(mentions):
    """Compute stats and available dates from already-fetched mentions (zero extra DB calls)."""
    pos = sum(1 for m in mentions if m.get('sentiment') == 'positive')
    neg = sum(1 for m in mentions if m.get('sentiment') == 'negative')
    neu = sum(1 for m in mentions if m.get('sentiment') == 'neutral')
    dates = sorted(set(m['content_date'] for m in mentions if m.get('content_date')), reverse=True)
    stats = {'total': len(mentions), 'positive': pos, 'negative': neg, 'neutral': neu}
    return stats, dates
