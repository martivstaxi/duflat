/* ============================================================
   W5 Wallet Finder - app.js
   Adim 2 sonu: UI iskelet (stub). Kripto logic Adim 3-7'de eklenecek.
   ============================================================ */

(function () {
  'use strict';

  const WORD_COUNT = 23;

  const state = {
    words: new Array(WORD_COUNT).fill(''),
    suggestionIdx: 0,
    suggestionList: [],
    activeInputIdx: -1,
    searching: false,
  };

  // ----------------------------------------------------------
  // DOM helpers
  // ----------------------------------------------------------
  const $ = (sel) => document.querySelector(sel);

  function toast(message, kind) {
    const container = $('#toastContainer');
    const el = document.createElement('div');
    el.className = 'toast ' + (kind || '');
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.remove(), 2700);
  }

  // ----------------------------------------------------------
  // Word grid render
  // ----------------------------------------------------------
  function renderWordGrid() {
    const grid = $('#wordGrid');
    grid.innerHTML = '';
    for (let i = 0; i < WORD_COUNT; i++) {
      const wrap = document.createElement('div');
      wrap.className = 'word-input-wrap';
      wrap.dataset.index = String(i);

      const num = document.createElement('span');
      num.className = 'word-num';
      num.textContent = String(i + 1) + '.';

      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'word-input';
      input.autocomplete = 'off';
      input.autocapitalize = 'none';
      input.spellcheck = false;
      input.dataset.index = String(i);
      input.setAttribute('inputmode', 'text');
      input.addEventListener('input', handleWordInput);
      input.addEventListener('keydown', handleWordKeydown);
      input.addEventListener('paste', handleWordPaste);
      input.addEventListener('focus', handleWordFocus);
      input.addEventListener('blur', handleWordBlur);

      const sugg = document.createElement('div');
      sugg.className = 'word-suggestions';
      sugg.dataset.index = String(i);

      wrap.appendChild(num);
      wrap.appendChild(input);
      wrap.appendChild(sugg);
      grid.appendChild(wrap);
    }
  }

  function handleWordInput(ev) {
    const idx = Number(ev.target.dataset.index);
    const val = ev.target.value.toLowerCase().trim();
    state.words[idx] = val;
    updateWordValidation(idx, val);
    updateWordCount();
    updateFindButton();
    updateSuggestions(idx, val);
  }

  function handleWordFocus(ev) {
    const idx = Number(ev.target.dataset.index);
    state.activeInputIdx = idx;
    updateSuggestions(idx, ev.target.value.toLowerCase());
    // Klavye acildiktan sonra input'u ekranin ustune scroll et ki altinda oneri icin yer acilsin
    setTimeout(() => {
      const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
      if (wrap) wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 320);
  }

  function handleWordBlur(ev) {
    const idx = Number(ev.target.dataset.index);
    setTimeout(() => {
      const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
      if (wrap) {
        const sugg = wrap.querySelector('.word-suggestions');
        if (sugg) sugg.classList.remove('open');
      }
    }, 150);
  }

  function handleWordKeydown(ev) {
    const idx = Number(ev.target.dataset.index);
    const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
    const sugg = wrap ? wrap.querySelector('.word-suggestions') : null;
    const suggOpen = sugg && sugg.classList.contains('open');

    if (suggOpen && (ev.key === 'ArrowDown' || ev.key === 'ArrowUp')) {
      ev.preventDefault();
      const delta = ev.key === 'ArrowDown' ? 1 : -1;
      state.suggestionIdx = Math.max(0,
        Math.min(state.suggestionList.length - 1, state.suggestionIdx + delta));
      renderSuggestions(idx);
      return;
    }

    if (ev.key === ' ' || ev.key === 'Enter' || ev.key === 'Tab') {
      if (suggOpen && state.suggestionList.length > 0) {
        ev.preventDefault();
        const picked = state.suggestionList[state.suggestionIdx];
        ev.target.value = picked;
        state.words[idx] = picked;
        updateWordValidation(idx, picked);
        updateWordCount();
        updateFindButton();
        sugg.classList.remove('open');
      } else if (ev.key === ' ' || ev.key === 'Enter') {
        ev.preventDefault();
      }
      if (ev.key !== 'Tab' || !ev.shiftKey) {
        const next = document.querySelector('.word-input[data-index="' + (idx + 1) + '"]');
        if (next) {
          if (ev.key === ' ' || ev.key === 'Enter') next.focus();
        }
      }
      return;
    }

    if (ev.key === 'Escape' && suggOpen) {
      sugg.classList.remove('open');
      return;
    }

    if (ev.key === 'Backspace' && !ev.target.value && idx > 0) {
      const prev = document.querySelector('.word-input[data-index="' + (idx - 1) + '"]');
      if (prev) prev.focus();
    }
  }

  function updateWordValidation(idx, val) {
    const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
    if (!wrap) return;
    wrap.classList.remove('valid', 'invalid');
    if (!val) return;
    if (window.BIP39_INDEX && val in window.BIP39_INDEX) {
      wrap.classList.add('valid');
    } else {
      wrap.classList.add('invalid');
    }
  }

  function updateSuggestions(idx, prefix) {
    const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
    if (!wrap) return;
    const sugg = wrap.querySelector('.word-suggestions');
    if (!sugg) return;

    if (!prefix || prefix.length < 3 || !window.BIP39_WORDLIST) {
      sugg.classList.remove('open');
      state.suggestionList = [];
      return;
    }

    if (window.BIP39_INDEX && prefix in window.BIP39_INDEX) {
      sugg.classList.remove('open');
      state.suggestionList = [];
      return;
    }

    const matches = [];
    for (const w of window.BIP39_WORDLIST) {
      if (w.startsWith(prefix)) {
        matches.push(w);
        if (matches.length >= 6) break;
      }
    }
    state.suggestionList = matches;
    state.suggestionIdx = 0;
    if (matches.length === 0) {
      sugg.classList.remove('open');
      return;
    }
    renderSuggestions(idx);
    sugg.classList.add('open');
  }

  function renderSuggestions(idx) {
    const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
    if (!wrap) return;
    const sugg = wrap.querySelector('.word-suggestions');
    if (!sugg) return;
    sugg.innerHTML = '';
    state.suggestionList.forEach((w, i) => {
      const item = document.createElement('div');
      item.className = 'word-suggestion-item' + (i === state.suggestionIdx ? ' active' : '');
      item.textContent = w;
      item.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        const input = wrap.querySelector('.word-input');
        input.value = w;
        state.words[idx] = w;
        updateWordValidation(idx, w);
        updateWordCount();
        updateFindButton();
        sugg.classList.remove('open');
        const next = document.querySelector('.word-input[data-index="' + (idx + 1) + '"]');
        if (next) next.focus();
      });
      sugg.appendChild(item);
    });
  }

  function handleWordPaste(ev) {
    const text = (ev.clipboardData || window.clipboardData).getData('text');
    if (!text) return;
    const words = extractWords(text);
    if (words.length >= 2) {
      ev.preventDefault();
      const startIdx = Number(ev.target.dataset.index);
      fillWordsFrom(startIdx, words);
    }
  }

  function extractWords(text) {
    return text
      .replace(/[\r\n,;\t]+/g, ' ')
      .split(/\s+/)
      .map((w) => w.toLowerCase().trim())
      .filter((w) => w && /^[a-z]+$/.test(w));
  }

  function fillWordsFrom(startIdx, words) {
    const inputs = document.querySelectorAll('.word-input');
    for (let i = 0; i < words.length && startIdx + i < WORD_COUNT; i++) {
      const targetIdx = startIdx + i;
      inputs[targetIdx].value = words[i];
      state.words[targetIdx] = words[i];
      updateWordValidation(targetIdx, words[i]);
    }
    updateWordCount();
    updateFindButton();
  }

  function updateWordCount() {
    const filled = state.words.filter((w) => w.length > 0).length;
    $('#wordCount').textContent = String(filled);
  }

  function updateFindButton() {
    const btn = $('#findBtn');
    const hint = $('#btnHint');
    const filled = state.words.filter((w) => w.length > 0).length;

    if (filled < WORD_COUNT) {
      btn.disabled = true;
      hint.textContent = (WORD_COUNT - filled) + ' kelime daha girin';
      return;
    }

    if (!window.BIP39_INDEX) {
      btn.disabled = true;
      hint.textContent = 'Kelime listesi yukleniyor...';
      return;
    }

    const invalid = state.words.filter((w) => !(w in window.BIP39_INDEX));
    if (invalid.length > 0) {
      btn.disabled = true;
      hint.textContent = invalid.length + ' gecersiz kelime (BIP-39 disi)';
      return;
    }

    btn.disabled = false;
    hint.textContent = 'Tum kelimeler gecerli, aramaya hazir';
  }

  // ----------------------------------------------------------
  // Paste-all modal
  // ----------------------------------------------------------
  function openPasteModal() {
    $('#pasteModal').classList.remove('hidden');
    setTimeout(() => $('#pasteTextarea').focus(), 50);
  }

  function closePasteModal() {
    $('#pasteModal').classList.add('hidden');
    $('#pasteTextarea').value = '';
  }

  function confirmPaste() {
    const text = $('#pasteTextarea').value;
    const words = extractWords(text);
    if (words.length === 0) {
      toast('Gecerli kelime bulunamadi', 'error');
      return;
    }
    fillWordsFrom(0, words);
    closePasteModal();
    toast(words.length + ' kelime eklendi', 'success');
  }

  function clearAll() {
    state.words = new Array(WORD_COUNT).fill('');
    document.querySelectorAll('.word-input').forEach((inp) => {
      inp.value = '';
    });
    document.querySelectorAll('.word-input-wrap').forEach((w) => {
      w.classList.remove('valid', 'invalid');
    });
    updateWordCount();
    updateFindButton();
    $('#resultsSection').classList.add('hidden');
    $('#progressCard').classList.add('hidden');
  }

  // ----------------------------------------------------------
  // Find button: full pipeline
  //   1) scan 2048 words -> candidates (entropy + basic-seed check)
  //   2) per candidate -> Ed25519 keypair + W5R1 address
  //   3) render result cards
  // ----------------------------------------------------------
  async function handleFind() {
    if (state.searching) return;
    state.searching = true;

    if (!window.TON_CRYPTO || !window.TON_WALLET || !window.TON_ADDRESS || !window.BIP39_WORDLIST) {
      toast('Kripto motoru hazir degil (sayfayi yenileyin)', 'error');
      state.searching = false;
      return;
    }

    const btn = $('#findBtn');
    const btnLabel = btn.querySelector('.btn-label');
    const progressCard = $('#progressCard');
    const progressFill = $('#progressBarFill');
    const progressPct = $('#progressPercent');
    const progressDetail = $('#progressDetail');
    const progressTitle = progressCard.querySelector('.progress-title');
    const resultsSection = $('#resultsSection');

    btn.disabled = true;
    btnLabel.textContent = 'Tarama devam ediyor...';
    $('#btnHint').textContent = 'Lutfen bekleyin';

    resultsSection.classList.add('hidden');
    $('#resultsList').innerHTML = '';
    progressCard.classList.remove('hidden');
    progressFill.style.width = '0%';
    progressPct.textContent = '0%';
    progressTitle.textContent = '24. kelime araniyor...';
    progressDetail.textContent = '2048 kelime kontrol ediliyor';

    const t0 = performance.now();

    try {
      const candidates = await window.TON_CRYPTO.tonFindCandidates(
        state.words.slice(),
        window.BIP39_WORDLIST,
        (done, total, found) => {
          const pct = Math.min(100, Math.floor((done * 100) / total));
          progressFill.style.width = pct + '%';
          progressPct.textContent = pct + '%';
          progressDetail.textContent = done + ' / ' + total + ' (' + found + ' aday)';
        }
      );

      const scanMs = Math.round(performance.now() - t0);

      if (candidates.length === 0) {
        progressCard.classList.add('hidden');
        toast('Gecerli 24. kelime bulunamadi', 'error');
        return;
      }

      // Phase 2: W5 address for each candidate
      progressTitle.textContent = 'W5 adresleri hesaplaniyor...';
      progressFill.style.width = '0%';
      progressPct.textContent = '0%';

      const results = [];
      for (let i = 0; i < candidates.length; i++) {
        const c = candidates[i];
        const kp = await window.TON_WALLET.deriveKeypair(c.mnemonic);
        const addr = await window.TON_ADDRESS.w5AddressFromPubkey(kp.publicKey);
        results.push({
          word: c.word,
          idx: c.idx,
          publicKey: window.TON_CRYPTO.bytesToHex(kp.publicKey),
          address: addr
        });
        const pct = Math.floor(((i + 1) * 100) / candidates.length);
        progressFill.style.width = pct + '%';
        progressPct.textContent = pct + '%';
        progressDetail.textContent = (i + 1) + ' / ' + candidates.length + ' adres hesaplandi';
      }

      const totalMs = Math.round(performance.now() - t0);

      progressCard.classList.add('hidden');
      renderResults(results, scanMs, totalMs);
    } catch (err) {
      progressCard.classList.add('hidden');
      console.error(err);
      toast('Hata: ' + (err && err.message ? err.message : 'bilinmeyen'), 'error');
    } finally {
      state.searching = false;
      btnLabel.textContent = '24. Kelimeyi Bul';
      updateFindButton();
    }
  }

  // ----------------------------------------------------------
  // Results rendering
  // ----------------------------------------------------------
  function renderResults(results, scanMs, totalMs) {
    const section = $('#resultsSection');
    const list = $('#resultsList');
    const count = $('#resultsCount');

    list.innerHTML = '';
    count.textContent = results.length + ' aday';

    results.forEach((r, i) => {
      list.appendChild(createResultCard(r, i));
    });

    section.classList.remove('hidden');

    if (scanMs && totalMs) {
      toast(results.length + ' aday bulundu (' + (totalMs / 1000).toFixed(1) + 's)', 'success');
    }

    setTimeout(() => {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  }

  function createResultCard(r, i) {
    const card = document.createElement('div');
    card.className = 'result-card';

    const header = document.createElement('div');
    header.className = 'result-header';

    const word = document.createElement('span');
    word.className = 'result-word';
    word.textContent = '#' + (i + 1) + ' - ' + r.word.toUpperCase();
    header.appendChild(word);

    const badge = document.createElement('span');
    badge.className = 'result-badge';
    badge.textContent = 'W5 / V5R1';
    header.appendChild(badge);

    card.appendChild(header);

    card.appendChild(buildField('Adres (UQ, non-bounceable)', r.address.non_bounceable));
    card.appendChild(buildField('Bounceable (EQ)', r.address.bounceable));
    card.appendChild(buildField('Public key', r.publicKey));

    return card;
  }

  function buildField(label, value) {
    const field = document.createElement('div');
    field.className = 'result-field';

    const lbl = document.createElement('div');
    lbl.className = 'result-label';
    lbl.textContent = label;
    field.appendChild(lbl);

    const val = document.createElement('div');
    val.className = 'result-value';

    const span = document.createElement('span');
    span.textContent = value;
    val.appendChild(span);

    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.type = 'button';
    btn.textContent = 'Kopyala';
    btn.addEventListener('click', () => copyToClipboard(value, btn));
    val.appendChild(btn);

    field.appendChild(val);
    return field;
  }

  function copyToClipboard(text, btn) {
    const done = () => {
      btn.textContent = 'Kopyalandi';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = 'Kopyala';
        btn.classList.remove('copied');
      }, 1500);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, btn));
    } else {
      fallbackCopy(text, btn);
    }

    function fallbackCopy(t, b) {
      const ta = document.createElement('textarea');
      ta.value = t;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        done();
      } catch (e) {
        toast('Kopyalanamadi', 'error');
      }
      document.body.removeChild(ta);
    }
  }

  // ----------------------------------------------------------
  // Wire up
  // ----------------------------------------------------------
  function init() {
    renderWordGrid();
    updateWordCount();
    updateFindButton();

    $('#findBtn').addEventListener('click', handleFind);
    $('#pasteAllBtn').addEventListener('click', openPasteModal);
    $('#clearAllBtn').addEventListener('click', clearAll);
    $('#pasteCancelBtn').addEventListener('click', closePasteModal);
    $('#pasteConfirmBtn').addEventListener('click', confirmPaste);

    document.querySelectorAll('[data-close="1"]').forEach((el) => {
      el.addEventListener('click', closePasteModal);
    });

    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && !$('#pasteModal').classList.contains('hidden')) {
        closePasteModal();
      }
    });

  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ----------------------------------------------------------
  // Service worker registration (offline support)
  // ----------------------------------------------------------
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('./service-worker.js').catch((err) => {
        console.warn('[sw] registration failed:', err);
      });
    });
  }
})();
