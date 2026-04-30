"""
Tek URL uzerinde ytb_scraper calistir, sonucu JSON'a kaydet.
Kullanim: python test_single.py
"""
import sys
import json
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

from ytb_scraper import setup_driver, process_single_url

TEST_URL = "https://www.youtube.com/watch?v=uSTkFItEavI&t=4s"
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "test_result_local.json")

def main():
    print(f"Test URL: {TEST_URL}")
    print("Chrome baslatiliyor...")
    driver = setup_driver()
    try:
        driver.get("https://www.youtube.com")
        import time; time.sleep(1)
        result = process_single_url(driver, TEST_URL, 1, 1)
    finally:
        driver.quit()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n=== SONUCLAR ===")
    fields = [
        ("name", "Kanal Adi"),
        ("handle", "Handle"),
        ("subscribers", "Abone Sayisi"),
        ("videos", "Video Sayisi"),
        ("views", "Goruntulenme"),
        ("last_video_date", "Son Video Tarihi"),
        ("description", "Aciklama"),
        ("email", "Email"),
        ("location", "Konum"),
        ("joined", "Katilim Tarihi"),
        ("instagram", "Instagram"),
        ("tiktok", "TikTok"),
        ("twitter", "Twitter/X"),
        ("facebook", "Facebook"),
        ("discord", "Discord"),
        ("twitch", "Twitch"),
        ("myanimelist", "MyAnimeList"),
        ("all_links", "Tüm Linkler"),
    ]
    for key, label in fields:
        val = result.get(key, "")
        status = "✓" if val else "✗"
        print(f"  {status} {label}: {val[:80] if val else '(boş)'}")

    print(f"\nDurum: {result.get('status', '')}")
    print(f"\nJSON kaydedildi: {OUTPUT_FILE}", flush=True)

if __name__ == "__main__":
    main()
