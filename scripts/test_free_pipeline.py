"""
Quick test: free web pipeline for Ece Ronay channel.
Run locally with: py scripts/test_free_pipeline.py
Or test via Railway after deploy.
"""
import requests
import json
import time

API = 'https://duflat-production.up.railway.app'
# API = 'http://localhost:5000'

TEST_CHANNEL = 'https://www.youtube.com/channel/UCysm5Itfgc7VZ75gO_gtIpQ'

print('=== Step 1: Scrape channel ===')
t0 = time.time()
r = requests.post(f'{API}/scrape', json={'url': TEST_CHANNEL}, timeout=120)
scrape_data = r.json()
print(f'Scrape took {time.time()-t0:.1f}s')
print(f'Channel: {scrape_data.get("name")} ({scrape_data.get("handle")})')
print(f'Email on page: {scrape_data.get("email", "none")}')
print(f'Links: {len(scrape_data.get("all_links", []))}')
print()

print('=== Step 2: Find email v2 (with free pipeline) ===')
t0 = time.time()
r = requests.post(f'{API}/find-email-v2', json={'channel_data': scrape_data}, timeout=120)
email_data = r.json()
elapsed = time.time() - t0
print(f'Email search took {elapsed:.1f}s')
print(f'Found: {email_data.get("found")}')
if email_data.get('found'):
    print(f'Email: {email_data.get("email")}')
    print(f'Source: {email_data.get("source")}')
    print(f'Confidence: {email_data.get("confidence")}')
    print(f'Reasoning: {email_data.get("reasoning")}')
print()
print('Steps:')
for s in email_data.get('steps', []):
    print(f'  - {s}')
