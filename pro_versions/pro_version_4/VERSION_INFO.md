# pro_version_4

**Tarih:** 2026-04-04
**Commit:** a665315
**Durum:** Stabil — bilinen bug yok

## Bu Sürümde Ne Var

### Tamamlanan Ozellikler
- Kanal scraping (yt-dlp + monkey-patch + InnerTube API)
- Email finder (7 adim pipeline + 45s deadline)
- Ajans arastirma (6 adim pipeline + deep enrichment + Claude Haiku)
- AI kanal raporu (manuel buton, tablo rapor, algoritmik dil tespiti)
- Kanal avatari (yt3.ggpht.com filtreli)
- Kanal description bug fix (video URL'de about-page fallback)

### UI Degisiklikler (bu surum)
- Header kaldirildi, merkezi hero layout
- Apple-inspired tasarim: antialiased font, sans-serif basliklar
- Search bar tek birlesiK kart (input + buton ayni kutu, box-shadow derinlik)
- Kartlar: 16px border-radius, yumusak golge (0 4px 24px)
- Daha genis padding (30px), max-width 720px
- "Duflat" marka yazisi kaldirildi — sade, profesyonel gorunum
- Tum hover gecisleri 0.2s, buton hover'da renk degisimi
- Mobil: stats 2x2 grid, responsive padding

### Bilinen Bug
Yok.
