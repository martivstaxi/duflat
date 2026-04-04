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
from modules.email_detective import find_email_v2
from modules.summarizer   import summarize_channel
from modules.summarizer_v2 import summarize_channel_v2

app = Flask(__name__, static_folder='.')
CORS(app)

# ─────────────────────────────────────────────
# MAIN ROUTES
# ─────────────────────────────────────────────

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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'Duflat API starting... http://localhost:{port}')
    app.run(host='0.0.0.0', port=port, debug=False)
