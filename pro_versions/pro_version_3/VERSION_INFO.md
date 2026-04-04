# pro_version_3

**Tarih:** 2026-04-04  
**Commit:** 21ffb38  
**Branch:** main  

## Bu Versiyonda Çalışan Özellikler

- Kanal scraping (yt-dlp + monkey-patch + InnerTube)
- Ajans araştırma (6-adım pipeline + Claude Haiku)
- Email finder (7-adım pipeline, 45s deadline, shallow scrape)
- AI Summary (manuel buton, tablo raporu, algoritmik dil tespiti)
- **YENİ:** Kanal avatarı — yt-dlp thumbnails listesinden yt3.ggpht.com filtreli
- **YENİ:** Kanal description — is_video=True'da about-page'den çekiliyor (video desc gösterilmiyor)
- **YENİ:** UI yeniden yapılandırıldı — metadata satırları, About bölümü, consistent section dividers

## UI Yapısı (bu versiyonda)

```
[Avatar] Kanal Adı / @handle / URL
─────────────────────────────────
Subs | Videos | Total Views | Last Video
─────────────────────────────────
EMAIL    contact@example.com  [Find Email]
LOCATION Turkey
JOINED   Jan 2019
─────────────────────────────────
[✨ Generate AI Report]
ABOUT
[description box]
─────────────────────────────────
Social badges (varsa)
─────────────────────────────────
External Links (varsa)
```

## Bug Fixes Bu Versiyonda

1. `normalize_url` video→channel dönüştürmez — `is_video=True`'da yt-dlp description yerine about-page description kullanılıyor
2. `aboutChannelViewModel` yeni YouTube layout'u — hem `"description":"string"` hem `{"content":"string"}` formatı destekleniyor
3. Email validator sıkılaştırıldı — `qm@w.jk` gibi garbage emailler reddediliyor (local ≥3 char, total ≥10 char)
4. Email finder timeout — 45s deadline, DDG/Bing shallow scrape (subpage yok)

## Bilinen Bug / Sınırlama

- Açık bug yok.
- normalize_url video→channel dönüştürmüyor (tasarım kararı, about-page fallback ile çözülüyor)
