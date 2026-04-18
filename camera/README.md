# W5 Wallet Finder

TON Wallet V5 R1 için **24. kelime bulucu PWA**.

23 kelimelik seed phrase'in eksik 24. kelimesini bulur. Tamamen **offline / istemci tarafında** çalışır — hiçbir veri sunucuya gitmez. Google Play / App Store gerektirmez; tarayıcıdan açılır, isteğe bağlı "Ana Ekrana Ekle" ile uygulama gibi davranır.

## Canlı

**https://wallet.duflat.com**

## Nasıl Çalışır

```
23 kelime + aday (2048 deneme)
  ↓ HMAC-SHA512
entropy
  ↓ PBKDF2-SHA512 (390 iter, "TON seed version")
seed[0] == 0 ?  → aday ✓
  ↓ PBKDF2-SHA512 (100k iter, "TON default seed")
32-byte seed
  ↓ Ed25519
public key
  ↓ W5R1 StateInit cell hash
UQ/EQ adres
```

Ortalama ~8 aday bulur (1/256 olasılık), gerçek cüzdan tek bir tanesi — TON explorer'da bakiye kontrolü ile bulunur.

## Güvenlik

- Tüm hesaplama tarayıcıda. **Hiçbir veri ağa çıkmaz**
- Analytics/tracking yok
- Service Worker cache'e alıp offline çalıştırır
- **Öneri:** Kullanırken cihazı internetten kesin (uçak modu)

## Stack

- Vanilla HTML/CSS/JS, framework yok
- Web Crypto API (HMAC-SHA512, PBKDF2-SHA512)
- [tweetnacl-js](https://github.com/dchest/tweetnacl-js) — Ed25519
- [tonweb](https://github.com/toncenter/tonweb) — Cell/BOC/Address primitives
- Service Worker (cache-first, offline)

## Yerel Geliştirme

```bash
node tools/serve.js 8080
# → http://localhost:8080
```

Kripto motoru testleri:

```bash
node test_crypto.js
node test_w5.js
```

## Referans

`reference/ton_w5_finder.py` — orijinal Python implementasyonu. Python'un `hashlib` + `pynacl` + `pytoniq_core` kullanarak yaptığı işi JS'te birebir karşılıyor.

## Lisans

MIT
