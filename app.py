"""
Duflat API — Flask routes
All business logic lives in modules/. This file wires routes to modules.

Routes:
    POST /scrape          → modules.scraper.scrape_channel()
    POST /summarize-v2    → modules.summarizer_v2.summarize_channel_v2()
    POST /find-email      → modules.email_finder.find_email()
    POST /find-email-v2   → modules.email_detective.find_email_v2()
    POST /generate-email  → modules.email_generator.generate_email()
    GET  /debug-*         → various debug endpoints (dev only)
"""

import os
import threading
import yt_dlp
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from modules.scraper      import scrape_channel, normalize_url, _extract_about_via_ytdlp, fetch_about_page
from modules.email_finder import find_email
from modules.email_detective import find_email_v2
from modules.summarizer_v2 import summarize_channel_v2
from modules.email_generator import generate_email
from modules.social_listening import (
    init_supabase, check_urls, process_urls, save_mentions,
    get_mentions, compute_stats_and_dates, scan_urls,
    delete_mentions, update_mention, auto_discover, _analyze_with_haiku,
)
from modules import cs_reviews

app = Flask(__name__, static_folder='.')
CORS(app)

# ─────────────────────────────────────────────
# ADMIN / CRON AUTH
# ─────────────────────────────────────────────
# ADMIN_KEY guards destructive or cost-heavy admin endpoints (cleanup,
# reclassify, translate, debug-haiku, test-alert).
# CRON_KEY guards discover + scan endpoints that hit 3rd-party APIs.
# If a key env var is unset the corresponding guard no-ops (so existing
# cron triggers keep working until the key is set on Railway + cron-job.org).

def _require_key(env_name, header_name):
    expected = os.environ.get(env_name, '').strip()
    if not expected:
        return None
    got = (request.headers.get(header_name, '') or request.args.get('key', '')).strip()
    if got != expected:
        return jsonify({'error': 'unauthorized'}), 401
    return None

def _require_admin():
    return _require_key('ADMIN_KEY', 'X-Admin-Key')

def _require_cron():
    return _require_key('CRON_KEY', 'X-Cron-Key')

# ─────────────────────────────────────────────
# SUPABASE INIT
# ─────────────────────────────────────────────
_supa_url = os.environ.get('SUPABASE_URL', '')
_supa_key = os.environ.get('SUPABASE_KEY', '')
if _supa_url and _supa_key:
    try:
        init_supabase(_supa_url, _supa_key)
        print(f'Supabase connected: {_supa_url[:40]}...')
    except Exception as e:
        print(f'Supabase init failed: {e}')
    try:
        cs_reviews.init_supabase(_supa_url, _supa_key)
        print('CS reviews Supabase client ready')
    except Exception as e:
        print(f'CS reviews Supabase init failed: {e}')

# ─────────────────────────────────────────────
# MAIN ROUTES
# ─────────────────────────────────────────────

@app.route('/ping')
def ping():
    return 'ok', 200


@app.route('/social/test-alert')
def test_alert():
    auth = _require_admin()
    if auth: return auth
    from modules.social_listening import (
        _send_telegram_alerts,
        _send_email_alerts,
        _send_wecom_alerts,
    )
    test = [{
        'sensitivity': 'critical',
        'source_type': 'government',
        'platform': 'Test',
        'content_english': 'This is a test alert from Duflat Social Listening.',
        'sentiment': 'negative',
        'content_date': '2026-04-21',
        'url': 'https://duflat.com/social',
    }]
    _send_telegram_alerts(test)
    _send_email_alerts(test)
    _send_wecom_alerts(test)
    return jsonify({'status': 'sent'})


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/test')
def test_page():
    return send_from_directory('.', 'test.html')


@app.route('/scrape', methods=['POST'])
def scrape():
    body = request.get_json(silent=True) or {}
    url  = body.get('url', '').strip()
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    result = scrape_channel(url)
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route('/summarize-v2', methods=['POST'])
def summarize_v2_endpoint():
    body         = request.get_json(silent=True) or {}
    channel_data = body.get('channel_data', {})
    if not channel_data:
        return jsonify({'error': 'channel_data required'}), 400
    result = summarize_channel_v2(channel_data)
    return jsonify(result)


@app.route('/find-email', methods=['POST'])
def find_email_endpoint():
    body         = request.get_json(silent=True) or {}
    channel_data = body.get('channel_data', {})
    if not channel_data:
        return jsonify({'error': 'channel_data required'}), 400
    result = find_email(channel_data)
    return jsonify(result)


@app.route('/generate-email', methods=['POST'])
def generate_email_endpoint():
    body = request.get_json(silent=True) or {}
    channel_data = body.get('channel_data', {})
    report_data = body.get('report_data', {})
    transcripts = body.get('transcripts', [])
    if not channel_data:
        return jsonify({'error': 'channel_data required'}), 400
    if not report_data:
        return jsonify({'error': 'report_data required'}), 400
    result = generate_email(channel_data, report_data, transcripts)
    if 'error' in result:
        return jsonify(result), 500
    return jsonify(result)


@app.route('/suggest')
def suggest():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify([])
    api_key = os.environ.get('YOUTUBE_API_KEY', '')
    if not api_key:
        return jsonify([])
    try:
        import requests as _req
        resp = _req.get('https://www.googleapis.com/youtube/v3/search', params={
            'part': 'snippet',
            'type': 'channel',
            'q': q,
            'maxResults': 5,
            'order': 'relevance',
            'key': api_key,
        }, timeout=5)
        if resp.status_code != 200:
            return jsonify([])
        items = resp.json().get('items', [])
        # Get subscriber counts in batch
        channel_ids = [it['snippet']['channelId'] for it in items if it.get('snippet', {}).get('channelId')]
        subs_map = {}
        if channel_ids:
            stats_resp = _req.get('https://www.googleapis.com/youtube/v3/channels', params={
                'part': 'statistics',
                'id': ','.join(channel_ids),
                'key': api_key,
            }, timeout=5)
            if stats_resp.status_code == 200:
                for ch in stats_resp.json().get('items', []):
                    subs_map[ch['id']] = int(ch.get('statistics', {}).get('subscriberCount', 0))
        results = []
        for it in items:
            snip = it.get('snippet', {})
            cid = snip.get('channelId', '')
            thumb = snip.get('thumbnails', {}).get('default', {}).get('url', '')
            results.append({
                'name': snip.get('channelTitle', ''),
                'channel_id': cid,
                'thumbnail': thumb,
                'subscribers': subs_map.get(cid, 0),
            })
        # Sort by subscribers descending
        results.sort(key=lambda x: x['subscribers'], reverse=True)
        return jsonify(results)
    except Exception:
        return jsonify([])


@app.route('/debug-subs', methods=['GET'])
def debug_subs():
    """Debug: test subtitle extraction for a video."""
    vid = request.args.get('v', '').strip()
    if not vid:
        return jsonify({'error': 'v parameter required (video ID)'}), 400
    import tempfile, os as _os
    url = f'https://www.youtube.com/watch?v={vid}'
    result = {'video_id': vid, 'steps': []}

    # Step 1: extract_info — check what subtitle data exists
    try:
        with yt_dlp.YoutubeDL({'skip_download': True, 'quiet': True, 'no_warnings': True}) as ydl:
            info = ydl.extract_info(url, download=False)
        subs = info.get('subtitles') or {}
        auto = info.get('automatic_captions') or {}
        result['subtitles_langs'] = list(subs.keys())[:10]
        result['auto_captions_langs'] = list(auto.keys())[:10]
        result['has_subtitles'] = len(subs) > 0
        result['has_auto_captions'] = len(auto) > 0
        if auto:
            first_lang = list(auto.keys())[0]
            result['first_auto_formats'] = [f.get('ext') for f in auto[first_lang][:5]]
        result['steps'].append('extract_info OK')
    except Exception as e:
        result['steps'].append(f'extract_info FAIL: {e}')
        return jsonify(result)

    # Step 2: try yt-dlp download to temp dir
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            outtmpl = _os.path.join(tmpdir, '%(id)s')
            opts = {
                'skip_download': True, 'writesubtitles': True, 'writeautomaticsub': True,
                'subtitlesformat': 'json3', 'subtitleslangs': ['en', 'tr'],
                'outtmpl': outtmpl, 'quiet': True, 'no_warnings': True, 'ignoreerrors': True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            files = _os.listdir(tmpdir)
            result['temp_files'] = files
            result['steps'].append(f'download OK, {len(files)} files')
            for f in files[:3]:
                fpath = _os.path.join(tmpdir, f)
                sz = _os.path.getsize(fpath)
                result[f'file_{f}_size'] = sz
                if sz > 0 and sz < 5000:
                    result[f'file_{f}_preview'] = open(fpath, encoding='utf-8', errors='ignore').read()[:500]
    except Exception as e:
        result['steps'].append(f'download FAIL: {e}')

    return jsonify(result)


@app.route('/find-email-v2', methods=['POST'])
def find_email_v2_endpoint():
    body         = request.get_json(silent=True) or {}
    channel_data = body.get('channel_data', {})
    if not channel_data:
        return jsonify({'error': 'channel_data required'}), 400
    result = find_email_v2(channel_data)
    return jsonify(result)

# ─────────────────────────────────────────────
# DEBUG ROUTES (development / diagnostics)
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# SOCIAL LISTENING ROUTES
# ─────────────────────────────────────────────

@app.route('/social')
def social_page():
    return send_from_directory('.', 'social.html')


@app.route('/social_test')
def social_test_page():
    return send_from_directory('.', 'social_test.html')


@app.route('/social/scan', methods=['POST'])
def social_scan():
    """All-in-one: dedup + download + Haiku analysis + save. Just send URLs."""
    auth = _require_cron()
    if auth: return auth
    body = request.get_json(silent=True) or {}
    urls = body.get('urls', [])
    if not urls:
        return jsonify({'error': 'urls list required'}), 400
    result = scan_urls(urls)
    return jsonify(result)


@app.route('/social/discover', methods=['POST'])
def social_discover():
    """Auto-discover Bilibili mentions across 8 languages via DDG search."""
    auth = _require_cron()
    if auth: return auth
    body = request.get_json(silent=True) or {}
    languages = body.get('languages')  # optional: filter specific languages
    result = auto_discover(languages)
    return jsonify(result)


@app.route('/social/discover-reddit', methods=['POST'])
def social_discover_reddit():
    """Fetch Bilibili-related Reddit posts via JSON API."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_reddit
    return jsonify(discover_reddit())


@app.route('/social/discover-hn', methods=['POST'])
def social_discover_hn():
    """Fetch Bilibili-related Hacker News stories + comments via Algolia API."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_hackernews
    return jsonify(discover_hackernews())


@app.route('/social/discover-bluesky', methods=['POST'])
def social_discover_bluesky():
    """Fetch Bilibili-related Bluesky posts via public AT Protocol search."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_bluesky
    return jsonify(discover_bluesky())


@app.route('/social/discover-lemmy', methods=['POST'])
def social_discover_lemmy():
    """Fetch Bilibili-related Lemmy posts across federated instances."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_lemmy
    return jsonify(discover_lemmy())


@app.route('/social/discover-mastodon', methods=['POST'])
def social_discover_mastodon():
    """Fetch Bilibili-related Mastodon posts from public tag timelines."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_mastodon
    return jsonify(discover_mastodon())


@app.route('/social/discover-lihkg', methods=['POST'])
def social_discover_lihkg():
    """Fetch Bilibili-related LIHKG threads (HK Traditional Chinese forum)."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_lihkg
    return jsonify(discover_lihkg())


@app.route('/social/discover-youtube', methods=['POST'])
def social_discover_youtube():
    """Fetch Bilibili-related YouTube videos from real creators
    (skips Bilibili-owned channels + sub-threshold creators)."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_youtube
    return jsonify(discover_youtube())


@app.route('/social/discover-youtube-comments', methods=['POST'])
def social_discover_youtube_comments():
    """Harvest viewer comments from high-view Bilibili-related YouTube videos."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_youtube_comments
    return jsonify(discover_youtube_comments())


@app.route('/social/discover-youtube-deep', methods=['POST'])
def social_discover_youtube_deep():
    """Transcript-aware YouTube discovery — catches Bilibili mentions that
    appear only in the spoken audio of topical videos."""
    auth = _require_cron()
    if auth: return auth
    from modules.social_listening import discover_youtube_deep
    return jsonify(discover_youtube_deep())


_discover_all_state = {'active': False}

def _discover_all_background():
    try:
        from modules.social_listening import (
            discover_reddit, discover_bluesky,
            discover_lemmy, discover_mastodon, discover_lihkg,
            discover_youtube, discover_youtube_comments, discover_youtube_deep,
        )
        # Order: highest-ROI first; later sources are drained even if
        # earlier ones yielded plenty, because each has an independent
        # candidate pool and running them all keeps diversity balanced.
        # discover_youtube_deep runs last — it's the slowest (sequential
        # yt-dlp transcript fetches) and lowest volume.
        for fn in (discover_bluesky, discover_reddit, discover_youtube,
                   discover_youtube_comments,
                   discover_lihkg, discover_lemmy, discover_mastodon,
                   discover_youtube_deep):
            try:
                fn()
            except Exception as e:
                print(f'[discover-all] {fn.__name__} error: {e}', flush=True)
    finally:
        _discover_all_state['active'] = False

@app.route('/social/discover-all', methods=['POST', 'GET'])
def social_discover_all():
    """Cron endpoint: fire-and-forget discover chain in background thread. Always 2xx."""
    auth = _require_cron()
    if auth: return auth
    import threading
    if _discover_all_state['active']:
        return jsonify({'status': 'already_running'}), 202
    _discover_all_state['active'] = True
    threading.Thread(target=_discover_all_background, daemon=True).start()
    return jsonify({
        'status': 'started',
        'sources': ['bluesky', 'reddit', 'youtube', 'lihkg', 'lemmy', 'mastodon'],
    }), 202


@app.route('/social/debug-reddit', methods=['GET'])
def social_debug_reddit():
    """Debug: fetch one reddit URL from the Railway worker, return raw info."""
    import requests as _rq
    url = 'https://www.reddit.com/r/Bilibili/new.json?limit=3'
    ua = 'Mozilla/5.0 (Duflat Social Listening) python-requests'
    try:
        r = _rq.get(url, headers={'User-Agent': ua}, timeout=8)
        body_preview = r.text[:400]
        try:
            n_children = len(r.json().get('data', {}).get('children', []))
        except Exception as e:
            n_children = f'json_err: {e}'
        return jsonify({
            'status': r.status_code,
            'n_children': n_children,
            'body_preview': body_preview,
        })
    except Exception as e:
        return jsonify({'exception': str(e)})


@app.route('/social/cleanup', methods=['POST'])
def social_cleanup():
    """Admin: delete mentions by ID and/or update content text."""
    auth = _require_admin()
    if auth: return auth
    body = request.get_json(silent=True) or {}
    result = {}
    ids_to_delete = body.get('delete', [])
    if ids_to_delete:
        result['deleted'] = delete_mentions(ids_to_delete)
    domain_to_delete = body.get('delete_domain', '').strip()
    if domain_to_delete:
        from modules.social_listening import delete_mentions_by_domain
        result['deleted_by_domain'] = delete_mentions_by_domain(domain_to_delete)
    updates = body.get('updates', [])
    updated = 0
    for u in updates:
        if update_mention(u['id'], u.get('content_english'), u.get('content_original'), u.get('language')):
            updated += 1
    result['updated'] = updated
    return jsonify(result)


@app.route('/social/reclassify', methods=['POST'])
def social_reclassify():
    """Admin: re-run L3 classification on every existing mention with the current rules."""
    auth = _require_admin()
    if auth: return auth
    from modules.social_listening import reclassify_all_mentions
    return jsonify(reclassify_all_mentions())


@app.route('/social/translate-missing', methods=['POST'])
def social_translate_missing():
    """Admin: backfill content_chinese (Simplified) for mentions still lacking it."""
    auth = _require_admin()
    if auth: return auth
    from modules.social_listening import translate_missing_chinese
    return jsonify(translate_missing_chinese())


@app.route('/social/retry-gate-failures', methods=['POST'])
def social_retry_gate_failures():
    """Admin: drain the L4 fail-closed queue. Safe to call repeatedly."""
    auth = _require_admin()
    if auth: return auth
    from modules.social_listening import retry_gate_failures
    return jsonify(retry_gate_failures())


@app.route('/social/debug-haiku', methods=['POST'])
def social_debug_haiku():
    """Debug: process URLs through pipeline and return raw Haiku output (no save)."""
    auth = _require_admin()
    if auth: return auth
    body = request.get_json(silent=True) or {}
    urls = body.get('urls', [])
    if not urls:
        return jsonify({'error': 'urls list required'}), 400
    from modules.social_listening import hash_url, process_urls as pu
    items = [{'url': u, 'url_hash': hash_url(u)} for u in urls]
    processed = pu(items, time_budget=30)
    items_2026 = processed.get('items', [])
    haiku_raw = _analyze_with_haiku(items_2026)
    return jsonify({
        'urls_sent': len(urls),
        'with_2026': len(items_2026),
        'items_2026': [{'url': i['url'], 'date': i.get('content_date'), 'text_preview': i['text'][:200]} for i in items_2026],
        'haiku_result': haiku_raw,
    })


@app.route('/social/check-urls', methods=['POST'])
def social_check_urls():
    """Step 1: Receive URLs from AI, return only new unique ones."""
    auth = _require_cron()
    if auth: return auth
    body = request.get_json(silent=True) or {}
    urls = body.get('urls', [])
    if not urls:
        return jsonify({'error': 'urls list required'}), 400
    new_urls = check_urls(urls)
    return jsonify({
        'received': len(urls),
        'new_unique': len(new_urls),
        'urls': new_urls,
    })


@app.route('/social/process', methods=['POST'])
def social_process():
    """Step 2: Download URLs, filter by 2026 date, return content for AI."""
    auth = _require_cron()
    if auth: return auth
    body = request.get_json(silent=True) or {}
    items = body.get('urls', [])
    if not items:
        return jsonify({'error': 'urls list required (each with url + url_hash)'}), 400
    result = process_urls(items)
    return jsonify(result)


@app.route('/social/save', methods=['POST'])
def social_save():
    """Step 3: Save AI-analyzed mentions to database."""
    auth = _require_cron()
    if auth: return auth
    body = request.get_json(silent=True) or {}
    mentions = body.get('mentions', [])
    if not mentions:
        return jsonify({'error': 'mentions list required'}), 400
    result = save_mentions(mentions)
    return jsonify(result)


@app.route('/social/mentions', methods=['GET'])
def social_mentions():
    """Step 4: Frontend reads mentions. ?days=3 or ?date=2026-01-01, ?limit=5000"""
    specific_date = request.args.get('date', '').strip()
    days = request.args.get('days', '').strip()
    try:
        limit = min(int(request.args.get('limit', 5000)), 10000)
    except Exception:
        limit = 5000

    if specific_date:
        data = get_mentions(specific_date=specific_date, limit=limit)
    elif days:
        data = get_mentions(days=int(days), limit=limit)
    else:
        data = get_mentions(days=3, limit=limit)

    stats, dates = compute_stats_and_dates(data)
    # Signal to UI if the cap was hit so it can show a warning.
    cap_hit = len(data) >= limit

    return jsonify({
        'mentions': data,
        'stats': stats,
        'available_dates': dates,
        'limit': limit,
        'cap_hit': cap_hit,
    })


@app.route('/social/debug-sources', methods=['GET'])
def social_debug_sources():
    """Debug: show recent social_sources with has_2026_content=True."""
    from modules.social_listening import _db
    result = _db().table('social_sources').select('url,domain,has_2026_content,checked_at').eq('has_2026_content', True).order('checked_at', desc=True).limit(20).execute()
    return jsonify(result.data)


# ─────────────────────────────────────────────
# CS REVIEWS ROUTES (Apple App Store + Google Play monitoring)
# ─────────────────────────────────────────────

@app.route('/cs')
def cs_page():
    return send_from_directory('.', 'cs.html')


@app.route('/cs/reviews', methods=['GET'])
def cs_reviews_list():
    """Frontend query. Params: platform, country, rating, days, limit,
    offset, search."""
    platform = request.args.get('platform') or None
    country = request.args.get('country') or None
    rating = request.args.get('rating') or None
    days = request.args.get('days') or None
    year = request.args.get('year') or None
    search = request.args.get('search') or None
    try:
        limit = min(int(request.args.get('limit', 100)), 5000)
    except Exception:
        limit = 100
    try:
        offset = max(int(request.args.get('offset', 0)), 0)
    except Exception:
        offset = 0
    rows = cs_reviews.get_reviews(
        platform=platform, country=country, rating=rating,
        days=days, year=year, limit=limit, offset=offset, search=search,
    )
    last = cs_reviews.get_last_poll()
    return jsonify({
        'reviews': rows,
        'last_poll': last,
        'app': cs_reviews.APP_CONFIG,
    })


# Single in-flight poll guard so overlapping triggers (e.g. cron retries)
# don't stack duplicate work.
_cs_poll_state = {'active': False, 'last_result': None}


def _cs_poll_background(platform, full_scan):
    try:
        _cs_poll_state['last_result'] = cs_reviews.poll_all(
            platform=platform, full_scan=full_scan,
        )
    except Exception as e:
        _cs_poll_state['last_result'] = {'error': str(e)}
        print(f'[cs_poll] background error: {e}')
    finally:
        _cs_poll_state['active'] = False


@app.route('/cs/poll', methods=['POST'])
def cs_poll():
    """Trigger a poll.

    Body:
        {"platform": "apple"|"google_play"|null}  which platform(s)
        {"wait": true}                             block until finished (for UI)
        {"full_scan": true}                        force re-scan of every country

    Default is fire-and-forget: returns 202 in <1s and runs in a
    background thread. Cron services (30s timeouts) should use the
    default. The frontend button sets wait=true to get stats inline.
    When full_scan is omitted, a 30-day discovery cycle is applied
    automatically."""
    body = request.get_json(silent=True) or {}
    platform = body.get('platform')
    wait = bool(body.get('wait'))
    full_scan = body.get('full_scan')  # True | False | None (auto)
    if platform not in (None, 'apple', 'google_play'):
        return jsonify({'error': 'platform must be apple, google_play, or null'}), 400

    if wait:
        try:
            stats = cs_reviews.poll_all(platform=platform, full_scan=full_scan)
            return jsonify(stats)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    if _cs_poll_state['active']:
        return jsonify({'status': 'already_running'}), 202

    _cs_poll_state['active'] = True
    t = threading.Thread(
        target=_cs_poll_background, args=(platform, full_scan), daemon=True,
    )
    t.start()
    return jsonify({'status': 'started', 'platform': platform or 'both',
                    'full_scan_requested': full_scan}), 202


@app.route('/cs/countries', methods=['GET'])
def cs_countries():
    """Per-country status: which platforms are active/inactive/unknown."""
    platform = request.args.get('platform') or None
    rows = cs_reviews.get_country_state(platform=platform)
    summary = {'active': 0, 'inactive': 0, 'unknown': 0}
    for r in rows:
        s = r.get('status', 'unknown')
        summary[s] = summary.get(s, 0) + 1
    return jsonify({
        'summary': summary,
        'config': {
            'inactive_threshold': cs_reviews.INACTIVE_THRESHOLD,
            'discovery_days': cs_reviews.DISCOVERY_DAYS,
        },
        'countries': rows,
    })


@app.route('/cs/poll-status', methods=['GET'])
def cs_poll_status():
    """Lightweight check of the background poller."""
    return jsonify({
        'active': _cs_poll_state['active'],
        'last_result': _cs_poll_state['last_result'],
    })


@app.route('/cs/insights', methods=['GET'])
def cs_insights():
    """Haiku narrative + stats for a review window.

    Params:
        period=7d|30d|year   (default 7d)
        lang=en|zh           (default en)
    Results cached server-side for 1h; poll completion invalidates."""
    period = (request.args.get('period') or '7d').strip().lower()
    lang = (request.args.get('lang') or 'en').strip().lower()
    try:
        result = cs_reviews.generate_insights(period=period, lang=lang)
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    return jsonify(result)


@app.route('/cs/backfill-translations', methods=['POST'])
def cs_backfill_translations():
    """One-shot backfill: fill `language` + `content_english` for legacy rows.
    Safe to call multiple times — rows already enriched are skipped."""
    body = request.get_json(silent=True) or {}
    try:
        limit = int(body.get('limit', 200))
    except Exception:
        limit = 200
    try:
        result = cs_reviews.backfill_translations(limit=limit)
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    return jsonify(result)


@app.route('/cs/debug-fetch', methods=['GET'])
def cs_debug_fetch():
    """Debug: fetch one country from one platform, return raw result
    without saving."""
    platform = request.args.get('platform', 'apple')
    country = request.args.get('country', 'us')
    default_lang = cs_reviews.GPLAY_COUNTRIES.get(country, 'en')
    lang = request.args.get('lang', default_lang)
    if platform == 'apple':
        revs = cs_reviews.fetch_apple_reviews(country)
        return jsonify({'count': len(revs), 'reviews': revs})
    if platform == 'google_play':
        revs = cs_reviews.fetch_gplay_reviews(country, lang=lang)
        return jsonify({'count': len(revs), 'reviews': revs})
    return jsonify({'error': 'unknown platform'}), 400


@app.route('/debug-email', methods=['GET'])
def debug_email():
    """Debug: what each method finds for channel email."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parameter required'}), 400

    from modules.scraper import (normalize_url, _fetch_email_innertube,
                                  _fetch_email_ydl_about, _innertube_session,
                                  _extract_continuation_token, _find_obj,
                                  _INNERTUBE_ABOUT_PARAMS, _INNERTUBE_WEB_CONTEXT,
                                  _INNERTUBE_WEB_HEADERS)
    import re as _re

    url = normalize_url(url)

    result      = scrape_channel(url)
    channel_url = result.get('channel_url', url)
    channel_id  = result.get('channel_id', '')
    if not channel_id:
        m = _re.search(r'/channel/(UC[a-zA-Z0-9_-]{22})', channel_url)
        if m:
            channel_id = m.group(1)

    # yt-dlp full about extraction
    ydl_email = _fetch_email_ydl_about(channel_url)

    # Two-phase InnerTube — detailed debug
    debug_innertube = {'phase1_status': 0, 'phase1_len': 0, 'cont_token': '',
                       'phase2_status': 0, 'phase2_len': 0,
                       'has_aboutViewModel': False, 'signInForEmail': '',
                       'email': '', 'has_hidden': False, 'error': ''}
    if channel_id:
        try:
            session = _innertube_session()
            headers = {**_INNERTUBE_WEB_HEADERS,
                       'Referer': f'https://www.youtube.com/channel/{channel_id}/about'}
            # Phase 1
            payload = {'browseId': channel_id, 'params': _INNERTUBE_ABOUT_PARAMS,
                       'context': _INNERTUBE_WEB_CONTEXT}
            r1 = session.post('https://www.youtube.com/youtubei/v1/browse',
                               json=payload, headers=headers, timeout=15)
            debug_innertube['phase1_status'] = r1.status_code
            debug_innertube['phase1_len'] = len(r1.text)
            if r1.status_code == 200:
                data1 = r1.json()
                cont_token = _extract_continuation_token(data1)
                debug_innertube['cont_token'] = cont_token[:80] + '...' if cont_token else ''

                if cont_token:
                    # Phase 2
                    r2 = session.post('https://www.youtube.com/youtubei/v1/browse',
                                      json={'continuation': cont_token, 'context': _INNERTUBE_WEB_CONTEXT},
                                      headers=headers, timeout=15)
                    debug_innertube['phase2_status'] = r2.status_code
                    debug_innertube['phase2_len'] = len(r2.text)
                    if r2.status_code == 200:
                        data2 = r2.json()
                        vm = _find_obj(data2, 'aboutChannelViewModel')
                        debug_innertube['has_aboutViewModel'] = vm is not None
                        if vm and isinstance(vm, dict):
                            sign_in = vm.get('signInForBusinessEmail', {})
                            if sign_in:
                                debug_innertube['signInForEmail'] = sign_in.get('content', '')[:100]
                                debug_innertube['has_hidden'] = True
                            for k in ('businessEmail', 'email'):
                                if vm.get(k):
                                    debug_innertube['email'] = str(vm[k])[:100]
        except Exception as e:
            debug_innertube['error'] = str(e)

    # Also run the main function
    it_email, has_hidden = '', False
    if channel_id:
        it_email, has_hidden = _fetch_email_innertube(channel_id)

    return jsonify({
        'channel_id':           channel_id,
        'scraper_email':        result.get('email'),
        'has_hidden_email':     result.get('has_hidden_email', False),
        'ydl_about_email':      ydl_email,
        'innertube_email':      it_email,
        'innertube_has_hidden': has_hidden,
        'debug_innertube':      debug_innertube,
    })


@app.route('/debug', methods=['GET'])
def debug():
    """Raw yt-dlp scalar output for a given URL."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parameter required: /debug?url=...'}), 400
    url = normalize_url(url)
    try:
        with yt_dlp.YoutubeDL({'skip_download': True, 'quiet': True, 'no_warnings': True,
                                'ignoreerrors': False, 'playlistend': 1}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    if not info:
        return jsonify({'error': 'Empty result (info=None)'}), 500

    safe = {k: v for k, v in info.items()
            if isinstance(v, (str, int, float, bool, type(None))) or
               (isinstance(v, list) and k in ('tags', 'categories'))}
    safe['entries_count'] = len(info.get('entries') or [])
    if info.get('entries'):
        first = info['entries'][0]
        if isinstance(first, dict):
            safe['first_entry_keys']                    = list(first.keys())
            safe['first_entry_upload_date']             = first.get('upload_date')
            safe['first_entry_playlist_count']          = first.get('playlist_count')
            safe['first_entry_channel_follower_count']  = first.get('channel_follower_count')
            safe['first_entry_type']                    = first.get('_type')
            sub = first.get('entries') or []
            safe['first_entry_sub_entries_count'] = len(sub)
            if sub and isinstance(sub[0], dict):
                safe['first_video_upload_date'] = sub[0].get('upload_date')
                safe['first_video_title']        = sub[0].get('title')
    return jsonify(safe)


@app.route('/debug-deep', methods=['GET'])
def debug_deep():
    """Full yt-dlp info dict (truncated to 2 levels)."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parameter required'}), 400
    url = normalize_url(url)
    try:
        with yt_dlp.YoutubeDL({'skip_download': True, 'quiet': True, 'no_warnings': True,
                                'ignoreerrors': True, 'playlistend': 1}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    if not info:
        return jsonify({'error': 'Empty result'}), 500

    def safe_val(v, depth=0):
        if isinstance(v, (str, int, float, bool, type(None))):
            return v
        if isinstance(v, list) and depth < 2:
            return [safe_val(i, depth + 1) for i in v[:3]]
        if isinstance(v, dict) and depth < 2:
            return {k2: safe_val(v2, depth + 1) for k2, v2 in list(v.items())[:30]}
        return f'<{type(v).__name__}>'

    result = safe_val(info)
    entries = info.get('entries') or []
    if entries and isinstance(entries[0], dict):
        first = entries[0]
        result['_first_entry_all_scalars'] = {
            k: v for k, v in first.items()
            if isinstance(v, (str, int, float, bool, type(None))) and 'channel' in k.lower() or
               k in ('view_count', 'subscriber_count', 'playlist_count', 'video_count', 'location', 'joined', 'country')
        }
    return jsonify(result)


@app.route('/debug-rawpage', methods=['GET'])
def debug_rawpage():
    """Show ytInitialData HTML snippets from about page."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url required'}), 400
    url = normalize_url(url)
    ps, extra = _extract_about_via_ytdlp(url)
    if not ps:
        return jsonify({'error': 'fetch failed', 'extra': extra}), 500

    checks = ['ytInitialData', 'ytcfg', '"country"', '"viewCountText"', '"joinedDateText"',
              '"videoCountText"', '"subscriberCountText"', 'channelMetadataRenderer',
              'aboutChannelViewModel', 'c4TabbedHeaderRenderer']
    snippets = {}
    for key in checks:
        idx = ps.find(key)
        if idx >= 0:
            snippets[key] = ps[max(0, idx - 20):idx + 100]

    return jsonify({'page_length': len(ps), 'first_500_chars': ps[:500],
                    'found_keys': snippets, 'extra_parsed': extra})


@app.route('/debug-about', methods=['GET'])
def debug_about():
    """About page extraction results — location/joined/views/videos test."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parameter required'}), 400
    url = normalize_url(url)
    ps, _ = _extract_about_via_ytdlp(url)
    about_result = fetch_about_page(url)
    socials, links, email = about_result[0], about_result[1], about_result[2]
    location, joined, views = about_result[3], about_result[4], about_result[5]
    video_count, last_video_date = about_result[6], about_result[7]
    has_hidden_email = about_result[8] if len(about_result) > 8 else False
    return jsonify({
        'page_length':         len(ps),
        'has_ytInitialData':   'ytInitialData' in ps,
        'has_country':         '"country"' in ps,
        'has_viewCountText':   '"viewCountText"' in ps,
        'has_joinedDateText':  '"joinedDateText"' in ps,
        'has_videoCountText':  '"videoCountText"' in ps or '"videosCountText"' in ps,
        'has_hidden_email':    has_hidden_email,
        'extracted': {
            'location':    location,
            'joined':      joined,
            'views':       views,
            'video_count': video_count,
            'email':       email,
            'socials':     socials,
            'all_links':   links,
            'last_video_date': last_video_date,
        },
    })


@app.route('/debug-search', methods=['GET'])
def debug_search():
    """Debug: test all search engines for a query."""
    q = request.args.get('q', '')
    if not q:
        return jsonify({'error': 'q parameter required: /debug-search?q=...'}), 400
    from modules.email_detective import (
        _search_serper, _search_ddg, _search_bing,
        _search_yahoo, _search_ecosia, _search_startpage,
    )
    return jsonify({
        'query': q,
        'serper': _search_serper(q),
        'ddg': _search_ddg(q),
        'bing': _search_bing(q),
        'yahoo': _search_yahoo(q),
        'ecosia': _search_ecosia(q),
        'startpage': _search_startpage(q),
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'Duflat API starting... http://localhost:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)
