# pro_version_5

**Tarih:** 2026-04-04
**Commit:** 22bb572
**Durum:** Stabil — bilinen bug yok

## Bu Surumde Ne Var

### Tum Ozellikler
- Kanal scraping (yt-dlp + monkey-patch + InnerTube API)
- Email finder (7 adim pipeline + 45s deadline)
- Ajans arastirma (6 adim pipeline + deep enrichment + Claude Haiku)
- AI kanal raporu (manuel buton, tablo rapor, algoritmik dil tespiti)
- Kanal avatari (yt3.ggpht.com filtreli)
- Apple-inspired UI (shadow kartlar, refined spacing, 720px max-width)

### Bu Surumdeki Degisiklikler
- Agency investigation: otomatik degil, manuel buton ile tetikleniyor
- Description bug fix (kalici): is_video=True ise info.get('description') kullanilmiyor
- About page description extraction: 4 kaynak (channelMetadataRenderer, aboutChannelViewModel, microformatDataRenderer, channelAboutFullMetadataRenderer) + yt-dlp channel fallback
- aboutChannelViewModel: object form {"content":"..."} once deneniyor

### Bilinen Bug
Yok.
