# pro_versions — Sürüm Arşivi

Bu klasör, projenin önemli milestone'larında alınan tam kod yedeklerini içerir.

## Nasıl Kullanılır

- **Normal geliştirmede bu klasöre bakılmaz.**
- Yalnızca şu durumlarda açılır:
  1. Proje bozulur ve geri dönük versiyon gerekir
  2. Önceki bir versiyonun nasıl yapıldığı öğrenilmek istenir
  3. Karşılaştırma / diff yapmak gerekir

Her sürüm kendi alt klasöründe `VERSION_INFO.md` içerir — ne içerdiği, hangi tarihe ait olduğu ve bilinen durumu.

## Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|---|---|---|
| [pro_version_1](./pro_version_1/VERSION_INFO.md) | 2026-04-04 | İlk stabil versiyon — scraping, email, ajans, AI özet hepsi çalışıyor |
| [pro_version_2](./pro_version_2/VERSION_INFO.md) | 2026-04-04 | Bug fixes + AI Summary yeniden yazıldı: manuel buton, tablo rapor, algoritmik dil tespiti |
| [pro_version_3](./pro_version_3/VERSION_INFO.md) | 2026-04-04 | UI yeniden yapılandırıldı + kanal avatar + description fix (video desc bug) + email finder timeout |
| [pro_version_4](./pro_version_4/VERSION_INFO.md) | 2026-04-04 | Apple-inspired UI redesign — header kaldırıldı, shadow kartlar, refined spacing, profesyonel görünüm |
| [pro_version_5](./pro_version_5/VERSION_INFO.md) | 2026-04-04 | Manuel agency butonu + description bug kalıcı fix (4 kaynak + yt-dlp fallback) |
| [pro_version_6](./pro_version_6/VERSION_INFO.md) | 2026-04-04 | Apify email finder yenilendi (exporter24 + endspec), UI temizlendi, Haiku geçici kapalı |
| [pro_version_7](./pro_version_7/VERSION_INFO.md) | 2026-04-04 | Avatar bug fix (shorts/video URL'lerinde yanlış resim sorunu çözüldü) |
| [pro_version_8](./pro_version_8/VERSION_INFO.md) | 2026-04-04 | AI Report v2 — video transkript analizi, avatar fix, bullet point key insight |
| [pro_version_9](./pro_version_9/VERSION_INFO.md) | 2026-04-04 | UI polish — Apple-style butonlar, spacing fix, profesyonel görünüm |
| [pro_version_10](./pro_version_10/VERSION_INFO.md) | 2026-04-04 | Personalized Email Generator — Bilibili davet emaili, Sonnet ile |
| [pro_version_11](./pro_version_11/VERSION_INFO.md) | 2026-04-04 | Email prompt profesyonel ton + UX juice animasyonlari |
| [pro_version_12](./pro_version_12/VERSION_INFO.md) | 2026-04-04 | Agency kaldirildi, UI sadeleşti, retry + custom smooth scroll |
| [pro_version_13](./pro_version_13/VERSION_INFO.md) | 2026-04-05 | Hero text, YouTube kanal autocomplete (Data API v3), isim arama |
| [pro_version_14](./pro_version_14/VERSION_INFO.md) | 2026-04-05 | UI polish: icon-only buton, placeholder, label guncellemeleri |
| [pro_version_15](./pro_version_15/VERSION_INFO.md) | 2026-04-05 | Email regenerate butonu, fade animasyonlari, dots kaldirildi |
| [pro_version_16](./pro_version_16/VERSION_INFO.md) | 2026-04-06 | Email dissolve/resolve efekti, overlay spinner, kart iskeleti korunuyor |
| [pro_version_17](./pro_version_17/VERSION_INFO.md) | 2026-04-06 | last_video_date fix: regex genisletme + coklu fallback |
