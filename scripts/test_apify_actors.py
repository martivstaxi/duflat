"""
Test different Apify actors for YouTube hidden email extraction.
Target: @tuas / UCdVda6ZYDgfnA2z8D7k20-A -> taygenumut@gmail.com
"""

import os
import json
import time
from apify_client import ApifyClient

TOKEN = os.environ.get('APIFY_API_TOKEN', '')
if not TOKEN:
    print("ERROR: APIFY_API_TOKEN not set")
    exit(1)

client = ApifyClient(token=TOKEN)

CHANNEL_ID = 'UCdVda6ZYDgfnA2z8D7k20-A'
CHANNEL_HANDLE = '@tuas'
CHANNEL_URL = f'https://www.youtube.com/channel/{CHANNEL_ID}'
EXPECTED_EMAIL = 'taygenumut@gmail.com'


def test_actor(actor_id, run_input, label):
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"Actor: {actor_id}")
    print(f"Input: {json.dumps(run_input, ensure_ascii=False)}")
    print(f"{'='*60}")

    try:
        start = time.time()
        run = client.actor(actor_id).call(
            run_input=run_input,
            timeout_secs=120,
        )
        elapsed = time.time() - start

        items = client.dataset(run['defaultDatasetId']).list_items().items
        print(f"Time: {elapsed:.1f}s")
        print(f"Items returned: {len(items)}")

        for i, item in enumerate(items):
            print(f"\nItem {i}:")
            print(json.dumps(item, ensure_ascii=False, indent=2, default=str))

            # Check for email
            email = (item.get('email') or item.get('business_email')
                     or item.get('businessEmail') or item.get('contact_email') or '')
            if email:
                match = 'MATCH' if email.lower().strip() == EXPECTED_EMAIL else 'WRONG'
                print(f"\nEmail found: {email} --> {match}")
            else:
                print("\nNo email field found")

        if not items:
            print("No items returned!")

    except Exception as e:
        print(f"ERROR: {e}")


# ---- Test 1: endspec/youtube-channel-contacts-extractor ($0.01) ----
# Needs: id or channelHandle (not channelUrls)
test_actor(
    'endspec/youtube-channel-contacts-extractor',
    {'id': CHANNEL_ID},
    'endspec contacts extractor (id)'
)

# ---- Test 2: exporter24/youtube-email-scraper ($0.03) ----
# Needs: url (singular string)
test_actor(
    'exporter24/youtube-email-scraper',
    {'url': CHANNEL_URL},
    'exporter24 email scraper (url string)'
)

# ---- Test 3: endspec/youtube-instant-email-scraper ($0.075) ----
# Needs: channelId (not channelHandle)
test_actor(
    'endspec/youtube-instant-email-scraper',
    {'channelId': CHANNEL_ID},
    'endspec instant email (channelId)'
)

# ---- Test 3b: endspec/youtube-instant-email-scraper with handle ----
test_actor(
    'endspec/youtube-instant-email-scraper',
    {'channelHandle': CHANNEL_HANDLE},
    'endspec instant email (handle @tuas)'
)

print("\n\nDONE - all tests complete.")
