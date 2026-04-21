"""
Standalone poll runner for the CS reviews pipeline.

Usage:
    python scripts/poll_cs_reviews.py                # both platforms
    python scripts/poll_cs_reviews.py apple          # apple only
    python scripts/poll_cs_reviews.py google_play    # google play only

Runs locally for testing. For production polling, point a free cron
service (cron-job.org, GitHub Actions, etc.) at POST /cs/poll instead.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import cs_reviews


def main():
    url = os.environ.get('SUPABASE_URL', '')
    key = os.environ.get('SUPABASE_KEY', '')
    if not url or not key:
        print('SUPABASE_URL and SUPABASE_KEY env vars required.', file=sys.stderr)
        sys.exit(1)
    cs_reviews.init_supabase(url, key)

    platform = sys.argv[1] if len(sys.argv) > 1 else None
    if platform not in (None, 'apple', 'google_play'):
        print(f'Unknown platform: {platform}', file=sys.stderr)
        sys.exit(2)

    print(f'Polling platform={platform or "both"}...')
    stats = cs_reviews.poll_all(platform=platform)
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
