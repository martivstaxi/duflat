"""
Duflat API — Flask routes
All business logic lives in modules/. This file wires routes to modules.

Routes:
    POST /scrape          → modules.scraper.scrape_channel()
    POST /agency          → modules.agency.find_agency()
    GET  /debug           → raw yt-dlp output (dev only)
    GET  /debug-about     → about page extraction (dev only)
    GET  /debug-rawpage   → raw ytInitialData HTML snippets (dev only)
    GET  /debug-deep      → full yt-dlp info dict (dev only)
"""

import os
import yt_dlp
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from modules.scraper      import scrape_channel, normalize_url, _extract_about_via_ytdlp, fetch_about_page
from modules.agency       import find_agency
from modules.email_finder import find_email
from modules.summarizer   import summarize_channel

app = Flask(__name__, static_folder='.')
CORS(app)

# ─────────────────────────────────────────────
# MAIN ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


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


@app.route('/agency', methods=['POST'])
def agency_endpoint():
    body = request.get_json(silent=True) or {}

    # Accept pre-scraped channel_data (preferred — avoids re-scraping)
    channel_data = body.get('channel_data')
    if not channel_data:
        url = body.get('url', '').strip()
        if not url:
            return jsonify({'error': 'channel_data or url required'}), 400
        channel_data = scrape_channel(url)
        if 'error' in channel_data:
            return jsonify({'error': channel_data['error']}), 400

    result = find_agency(channel_data)
    return jsonify(result)


@app.route('/summarize', methods=['POST'])
def summarize_endpoint():
    body         = request.get_json(silent=True) or {}
    channel_data = body.get('channel_data', {})
    if not channel_data:
        return jsonify({'error': 'channel_data required'}), 400
    result = summarize_channel(channel_data)
    return jsonify(result)


@app.route('/find-email', methods=['POST'])
def find_email_endpoint():
    body         = request.get_json(silent=True) or {}
    channel_data = body.get('channel_data', {})
    if not channel_data:
        return jsonify({'error': 'channel_data required'}), 400
    result = find_email(channel_data)
    return jsonify(result)

# ─────────────────────────────────────────────
# DEBUG ROUTES (development / diagnostics)
# ─────────────────────────────────────────────

@app.route('/debug-email', methods=['GET'])
def debug_email():
    """Debug: what each method finds for channel email."""
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'url parameter required'}), 400

    from modules.scraper import (normalize_url, _fetch_email_innertube,
                                  _fetch_email_ydl_about, _find_email_in_obj,
                                  _try_decode_b64_email, _extract_email_from_response,
                                  _INNERTUBE_ABOUT_PARAMS, _INNERTUBE_CLIENTS)
    import re as _re, requests as _req
    from modules.constants import BROWSER_HEADERS, EMAIL_BLACKLIST

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

    # InnerTube API — try all clients with session cookies
    client_results = []
    it_email = ''
    if channel_id:
        session = _req.Session()
        try:
            session.get('https://www.youtube.com/', headers=BROWSER_HEADERS, timeout=10)
        except Exception:
            pass
        session.cookies.set('CONSENT', 'PENDING+987', domain='.youtube.com')

        for client_cfg in _INNERTUBE_CLIENTS:
            client_name = client_cfg['context']['client']['clientName']
            cr = {'client': client_name, 'status': 0, 'email': '', 'be_raw': None, 'be_decoded': None, 'error': '', 'email_hits': []}
            try:
                payload = {'browseId': channel_id, 'params': _INNERTUBE_ABOUT_PARAMS,
                           'context': client_cfg['context']}
                hdrs = {'Content-Type': 'application/json',
                        'Origin': 'https://www.youtube.com',
                        'Referer': f'https://www.youtube.com/channel/{channel_id}/about',
                        'Accept-Encoding': 'gzip, deflate',
                        **client_cfg['headers']}
                r = session.post('https://www.youtube.com/youtubei/v1/browse',
                                  json=payload, headers=hdrs, timeout=15)
                cr['status'] = r.status_code
                cr['response_len'] = len(r.text)
                bm = _re.search(r'"businessEmail"\s*:\s*"([^"]+)"', r.text)
                if bm:
                    cr['be_raw'] = bm.group(1)
                    cr['be_decoded'] = _try_decode_b64_email(bm.group(1))
                cr['email'] = _extract_email_from_response(r)
                if cr['email'] and not it_email:
                    it_email = cr['email']
                # Find email-related snippets
                for em in _re.finditer(r'.{0,60}(?:email|mail|contact|business).{0,60}', r.text[:5000], _re.I):
                    cr['email_hits'].append(em.group())
                cr['email_hits'] = cr['email_hits'][:10]
            except Exception as e:
                cr['error'] = str(e)
            client_results.append(cr)

    # Also test the main function
    innertube_main = _fetch_email_innertube(channel_id) if channel_id else ''

    return jsonify({
        'channel_id':           channel_id,
        'scraper_email':        result.get('email'),
        'ydl_about_email':      ydl_email,
        'innertube_main':       innertube_main,
        'innertube_email':      it_email,
        'client_results':       client_results,
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
    socials, links, email, location, joined, views, video_count, last_video_date = fetch_about_page(url)
    return jsonify({
        'page_length':         len(ps),
        'has_ytInitialData':   'ytInitialData' in ps,
        'has_country':         '"country"' in ps,
        'has_viewCountText':   '"viewCountText"' in ps,
        'has_joinedDateText':  '"joinedDateText"' in ps,
        'has_videoCountText':  '"videoCountText"' in ps or '"videosCountText"' in ps,
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'Duflat API starting... http://localhost:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)
