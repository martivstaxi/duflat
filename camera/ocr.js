/* ============================================================
   W5 Wallet Finder - ocr.js
   Tesseract.js worker + BIP-39 fuzzy match.
   Exposes window.OCR.
   ============================================================ */

(function () {
  'use strict';

  const TESSERACT_BASE = new URL('./vendor/tesseract/', window.location.href).href;

  let _worker = null;
  let _loadingPromise = null;

  function absUrl(name) {
    return TESSERACT_BASE + name;
  }

  function tesseractLogger(onStatus) {
    return (m) => {
      try { console.log('[tesseract]', m); } catch (_) {}
      if (!onStatus) return;
      if (m && m.status === 'recognizing text') {
        onStatus({ phase: 'recognize', progress: m.progress });
      } else if (m) {
        onStatus({ phase: m.status || 'init', progress: m.progress || 0 });
      }
    };
  }

  async function createWorkerWithOpts(opts) {
    try {
      return await window.Tesseract.createWorker('eng', 1, opts);
    } catch (err) {
      console.error('[OCR] createWorker failed:', err);
      // Hatanin ne oldugunu app katmaninda gostermek icin mesaji zenginlestir
      const suffix = err && err.message ? err.message : (typeof err === 'string' ? err : 'createWorker rejected');
      const e = new Error('Tesseract init: ' + suffix);
      e.cause = err;
      throw e;
    }
  }

  async function initWorker(onStatus) {
    if (_worker) return _worker;
    if (_loadingPromise) return _loadingPromise;

    if (!window.Tesseract) {
      throw new Error('Tesseract.js yuklenemedi (vendor/tesseract/tesseract.min.js)');
    }

    _loadingPromise = (async () => {
      const baseOpts = {
        workerPath: absUrl('worker.min.js'),
        corePath: TESSERACT_BASE,
        langPath: TESSERACT_BASE,
        logger: tesseractLogger(onStatus),
        errorHandler: (err) => {
          console.error('[tesseract errorHandler]', err);
        },
      };

      let worker;
      try {
        // 1. deneme: gzip:true (dosya .gz uzantili)
        worker = await createWorkerWithOpts(Object.assign({ gzip: true }, baseOpts));
      } catch (e1) {
        console.warn('[OCR] gzip:true failed, retrying with gzip:false', e1);
        // 2. deneme: gzip:false (Cloudflare double-decode yaptiysa)
        worker = await createWorkerWithOpts(Object.assign({ gzip: false }, baseOpts));
      }

      await worker.setParameters({
        tessedit_char_whitelist:
          'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789.',
        preserve_interword_spaces: '1',
      });

      _worker = worker;
      return worker;
    })();

    try {
      return await _loadingPromise;
    } catch (err) {
      _worker = null;
      throw err;
    } finally {
      _loadingPromise = null;
    }
  }

  async function runOCR(imageSource, onStatus) {
    const worker = await initWorker(onStatus);
    try {
      const ret = await worker.recognize(imageSource);
      return ret && ret.data ? (ret.data.text || '') : '';
    } catch (err) {
      console.error('[OCR] recognize failed:', err);
      const suffix = err && err.message ? err.message : (typeof err === 'string' ? err : 'recognize rejected');
      const e = new Error('Tesseract recognize: ' + suffix);
      e.cause = err;
      throw e;
    }
  }

  async function terminateWorker() {
    if (_worker) {
      try { await _worker.terminate(); } catch (_) {}
      _worker = null;
    }
  }

  // OCR text -> kelime dizisi
  // BIP-39: 3-8 karakter, sadece kucuk a-z. Esnek: 2-12 araligi al, fuzzy karar versin.
  function parseWords(text) {
    if (!text) return [];
    const cleaned = text.toLowerCase().replace(/[^a-z\s]/g, ' ');
    const parts = cleaned.split(/\s+/).filter((p) => p.length >= 2 && p.length <= 12);
    return parts;
  }

  // Levenshtein distance with early-exit at maxDist.
  function levenshtein(a, b, maxDist) {
    if (a === b) return 0;
    const la = a.length;
    const lb = b.length;
    if (!la) return lb;
    if (!lb) return la;
    if (Math.abs(la - lb) > maxDist) return maxDist + 1;

    let prev = new Array(lb + 1);
    let curr = new Array(lb + 1);
    for (let j = 0; j <= lb; j++) prev[j] = j;

    for (let i = 1; i <= la; i++) {
      curr[0] = i;
      let rowMin = curr[0];
      for (let j = 1; j <= lb; j++) {
        const cost = a.charCodeAt(i - 1) === b.charCodeAt(j - 1) ? 0 : 1;
        curr[j] = Math.min(
          prev[j] + 1,
          curr[j - 1] + 1,
          prev[j - 1] + cost
        );
        if (curr[j] < rowMin) rowMin = curr[j];
      }
      if (rowMin > maxDist) return maxDist + 1;
      const tmp = prev; prev = curr; curr = tmp;
    }
    return prev[lb];
  }

  // word -> { match, distance, candidates }
  function fuzzyMatchBip39(word, maxDist) {
    const limit = typeof maxDist === 'number' ? maxDist : 2;
    const wordlist = window.BIP39_WORDLIST;
    const index = window.BIP39_INDEX;
    if (!wordlist) return { match: null, distance: Infinity, candidates: [] };

    if (index && word in index) {
      return { match: word, distance: 0, candidates: [word] };
    }

    const close = [];
    let best = { w: null, d: Infinity };
    for (let i = 0; i < wordlist.length; i++) {
      const w = wordlist[i];
      if (Math.abs(w.length - word.length) > limit) continue;
      const d = levenshtein(word, w, limit);
      if (d <= limit) close.push({ w, d });
      if (d < best.d) best = { w, d };
    }
    close.sort((a, b) => a.d - b.d || (a.w < b.w ? -1 : 1));

    return {
      match: best.d <= limit ? best.w : null,
      distance: best.d,
      candidates: close.slice(0, 5).map((c) => c.w),
    };
  }

  // Tum OCR kelimelerini 23-uzunluk diziye cevir: { value, matched, distance }
  function resolveWords(rawWords, targetCount) {
    const n = typeof targetCount === 'number' ? targetCount : 23;
    const out = [];
    for (let i = 0; i < n; i++) {
      const raw = rawWords[i];
      if (!raw) {
        out.push({ value: '', matched: false, distance: null, original: '' });
        continue;
      }
      const r = fuzzyMatchBip39(raw, 2);
      if (r.match) {
        out.push({
          value: r.match,
          matched: true,
          distance: r.distance,
          original: raw,
        });
      } else {
        out.push({
          value: raw,
          matched: false,
          distance: r.distance === Infinity ? null : r.distance,
          original: raw,
        });
      }
    }
    return out;
  }

  window.OCR = {
    initWorker,
    runOCR,
    terminateWorker,
    parseWords,
    fuzzyMatchBip39,
    resolveWords,
    levenshtein,
  };
})();
