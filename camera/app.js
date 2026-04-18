/* ============================================================
   W5 Wallet Finder - app.js
   Adim 2 sonu: UI iskelet (stub). Kripto logic Adim 3-7'de eklenecek.
   ============================================================ */

(function () {
  'use strict';

  const WORD_COUNT = 23;

  const state = {
    words: new Array(WORD_COUNT).fill(''),
    searching: false,
    results: [],
    selectedIdx: -1,
    cameraStream: null,
    ocrWords: [],
    ocrEditingIdx: -1,
  };

  const COPY_ICON_SVG =
    '<svg class="copy-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="9" y="9" width="13" height="13" rx="2"></rect>' +
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>' +
    '</svg>';

  function sanitizeWord(val) {
    return (val || '').toLowerCase().replace(/[^a-z]/g, '');
  }

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
      input.setAttribute('autocorrect', 'off');
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
    const raw = ev.target.value;
    const val = sanitizeWord(raw);
    // sanitize sirasinda stripped = kullanici/klavye space/noktalama eklediyse
    // (iOS predictive text "elbow " gibi trailing space gonderiyor) → advance sinyali
    const stripped = raw.length > val.length;
    if (val !== raw) ev.target.value = val;
    state.words[idx] = val;
    updateWordValidation(idx, val);
    updateWordCount();
    updateFindButton();

    const isExact = val && window.BIP39_INDEX && val in window.BIP39_INDEX;

    // Eger tam BIP-39 kelime girildi VE kullanici space/noktalama ekleyip "bitti"
    // sinyali verdiyse → sonraki kutuya gec
    if (isExact && stripped) {
      hideSuggestions(idx);
      focusNext(idx);
      return;
    }

    if (val.length < 3 || isExact || !window.BIP39_WORDLIST) {
      hideSuggestions(idx);
      return;
    }

    const matches = [];
    for (const w of window.BIP39_WORDLIST) {
      if (w.startsWith(val)) {
        matches.push(w);
        if (matches.length >= 8) break;
      }
    }

    if (matches.length === 1) {
      const full = matches[0];
      ev.target.value = full;
      state.words[idx] = full;
      updateWordValidation(idx, full);
      updateWordCount();
      updateFindButton();
      hideSuggestions(idx);
      focusNext(idx);
    } else if (matches.length > 1) {
      renderSuggestions(idx, matches);
    } else {
      hideSuggestions(idx);
    }
  }

  function focusNext(idx) {
    const next = document.querySelector('.word-input[data-index="' + (idx + 1) + '"]');
    if (next) next.focus();
  }

  function handleWordFocus(ev) {
    const idx = Number(ev.target.dataset.index);
    setTimeout(() => {
      const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
      if (wrap) wrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 320);
  }

  function handleWordBlur(ev) {
    const idx = Number(ev.target.dataset.index);
    // mousedown handler tetiklensin diye hafif gecikme
    setTimeout(() => hideSuggestions(idx), 150);
  }

  function hideSuggestions(idx) {
    const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
    if (!wrap) return;
    const sugg = wrap.querySelector('.word-suggestions');
    if (sugg) {
      sugg.classList.remove('open');
      sugg.innerHTML = '';
    }
  }

  function renderSuggestions(idx, matches) {
    const wrap = document.querySelector('.word-input-wrap[data-index="' + idx + '"]');
    if (!wrap) return;
    const sugg = wrap.querySelector('.word-suggestions');
    if (!sugg) return;
    sugg.innerHTML = '';
    matches.forEach((w) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'word-chip';
      chip.textContent = w;
      chip.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        const input = wrap.querySelector('.word-input');
        input.value = w;
        state.words[idx] = w;
        updateWordValidation(idx, w);
        updateWordCount();
        updateFindButton();
        hideSuggestions(idx);
        const next = document.querySelector('.word-input[data-index="' + (idx + 1) + '"]');
        if (next) next.focus();
      });
      sugg.appendChild(chip);
    });
    sugg.classList.add('open');
  }

  function handleWordKeydown(ev) {
    const idx = Number(ev.target.dataset.index);

    if (ev.key === ' ' || ev.key === 'Enter') {
      ev.preventDefault();
      const next = document.querySelector('.word-input[data-index="' + (idx + 1) + '"]');
      if (next) next.focus();
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
    const filled = state.words.filter((w) => w.length > 0).length;

    if (filled < WORD_COUNT) { btn.disabled = true; return; }
    if (!window.BIP39_INDEX) { btn.disabled = true; return; }

    const invalid = state.words.filter((w) => !(w in window.BIP39_INDEX));
    btn.disabled = invalid.length > 0;
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
  // Results rendering  (iki asamali: kelime sec -> detay)
  // ----------------------------------------------------------
  function renderResults(results, scanMs, totalMs) {
    state.results = results;
    state.selectedIdx = -1;

    const section = $('#resultsSection');
    section.classList.remove('hidden');

    showCandidatePicker();

    setTimeout(() => {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  }

  function showCandidatePicker() {
    const section = $('#resultsSection');
    section.innerHTML = '';

    const header = document.createElement('div');
    header.className = 'results-header';

    const title = document.createElement('h2');
    title.className = 'results-title';
    title.textContent = '24. Kelimeyi Sec';
    header.appendChild(title);

    const count = document.createElement('span');
    count.className = 'results-count';
    count.textContent = state.results.length + ' olasilik';
    header.appendChild(count);

    section.appendChild(header);

    const sub = document.createElement('p');
    sub.className = 'picker-sub';
    sub.textContent = 'Bir kelime sec, cuzdan adresini gor.';
    section.appendChild(sub);

    const grid = document.createElement('div');
    grid.className = 'candidate-grid';
    state.results.forEach((r, i) => {
      const chip = document.createElement('button');
      chip.className = 'candidate-chip';
      chip.type = 'button';
      chip.style.animationDelay = (i * 45) + 'ms';

      const num = document.createElement('span');
      num.className = 'candidate-num';
      num.textContent = String(i + 1);
      chip.appendChild(num);

      const word = document.createElement('span');
      word.className = 'candidate-word';
      word.textContent = r.word;
      chip.appendChild(word);

      chip.addEventListener('click', () => selectCandidate(i));
      grid.appendChild(chip);
    });
    section.appendChild(grid);
  }

  function selectCandidate(i) {
    state.selectedIdx = i;
    showSelectedDetail();
  }

  function showSelectedDetail() {
    const section = $('#resultsSection');
    const r = state.results[state.selectedIdx];
    section.innerHTML = '';

    const back = document.createElement('button');
    back.className = 'back-link';
    back.type = 'button';
    back.innerHTML = '<span class="back-arrow">&larr;</span> Farkli kelime sec';
    back.addEventListener('click', showCandidatePicker);
    section.appendChild(back);

    const hero = document.createElement('div');
    hero.className = 'hero-card';

    const check = document.createElement('div');
    check.className = 'hero-check';
    check.innerHTML = '&#10003;';
    hero.appendChild(check);

    const heroLabel = document.createElement('div');
    heroLabel.className = 'hero-label';
    heroLabel.textContent = 'Sectigin 24. kelime';
    hero.appendChild(heroLabel);

    const heroWord = document.createElement('div');
    heroWord.className = 'hero-word';
    heroWord.textContent = r.word;
    hero.appendChild(heroWord);

    section.appendChild(hero);

    const addrCard = document.createElement('div');
    addrCard.className = 'card detail-card';
    addrCard.appendChild(buildField('Cuzdan Adresi (UQ)', r.address.non_bounceable));
    section.appendChild(addrCard);

    const mnemonic = state.words.slice();
    mnemonic.push(r.word);
    const mnemonicText = mnemonic.join(', ');

    const wordsCard = document.createElement('div');
    wordsCard.className = 'card words-card';

    const wordsHeader = document.createElement('div');
    wordsHeader.className = 'words-card-header';

    const wordsLabel = document.createElement('div');
    wordsLabel.className = 'words-label';
    wordsLabel.textContent = 'Tum 24 Kelime';
    wordsHeader.appendChild(wordsLabel);

    const mnemoCopy = document.createElement('button');
    mnemoCopy.className = 'copy-btn copy-btn-inline';
    mnemoCopy.type = 'button';
    mnemoCopy.innerHTML = COPY_ICON_SVG + '<span class="copy-label">Kopyala</span>';
    mnemoCopy.addEventListener('click', () => {
      copyText(mnemonicText).then((ok) => {
        if (!ok) { toast('Kopyalanamadi', 'error'); return; }
        mnemoCopy.classList.add('copied');
        mnemoCopy.querySelector('.copy-label').textContent = 'Kopyalandi';
        setTimeout(() => {
          mnemoCopy.classList.remove('copied');
          mnemoCopy.querySelector('.copy-label').textContent = 'Kopyala';
        }, 1500);
      });
    });
    wordsHeader.appendChild(mnemoCopy);

    wordsCard.appendChild(wordsHeader);

    const wordsGrid = document.createElement('div');
    wordsGrid.className = 'words-grid';
    mnemonic.forEach((w, idx) => {
      const item = document.createElement('div');
      item.className = 'word-item';
      if (idx === 23) item.classList.add('is-selected');
      const wNum = document.createElement('span');
      wNum.className = 'word-item-num';
      wNum.textContent = String(idx + 1) + '.';
      const wVal = document.createElement('span');
      wVal.className = 'word-item-word';
      wVal.textContent = w;
      item.appendChild(wNum);
      item.appendChild(wVal);
      wordsGrid.appendChild(item);
    });
    wordsCard.appendChild(wordsGrid);
    section.appendChild(wordsCard);

    setTimeout(() => {
      section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
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
    btn.innerHTML = COPY_ICON_SVG + '<span class="copy-label">Kopyala</span>';
    btn.addEventListener('click', () => {
      copyText(value).then((ok) => {
        if (!ok) { toast('Kopyalanamadi', 'error'); return; }
        btn.classList.add('copied');
        btn.querySelector('.copy-label').textContent = 'Kopyalandi';
        setTimeout(() => {
          btn.classList.remove('copied');
          btn.querySelector('.copy-label').textContent = 'Kopyala';
        }, 1500);
      });
    });
    val.appendChild(btn);

    field.appendChild(val);
    return field;
  }

  function copyText(text) {
    return new Promise((resolve) => {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => resolve(true)).catch(() => fallback());
      } else {
        fallback();
      }
      function fallback() {
        try {
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed';
          ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          const ok = document.execCommand('copy');
          document.body.removeChild(ta);
          resolve(!!ok);
        } catch (e) {
          resolve(false);
        }
      }
    });
  }

  // ----------------------------------------------------------
  // Camera + OCR flow
  // ----------------------------------------------------------
  async function openCameraModal() {
    const proto = window.location.protocol;
    const host = window.location.hostname;
    const isSecure = proto === 'https:' || host === 'localhost' || host === '127.0.0.1';
    if (!isSecure) {
      toast('Kamera HTTPS gerekir', 'error');
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      toast('Bu tarayici kamerayi desteklemiyor', 'error');
      return;
    }

    $('#cameraModal').classList.remove('hidden');
    const video = $('#cameraVideo');
    const processing = $('#cameraProcessing');
    processing.classList.add('hidden');
    $('#cameraShotBtn').disabled = false;

    try {
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } },
          audio: false,
        });
      } catch (_e) {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      }
      state.cameraStream = stream;
      video.srcObject = stream;
      await video.play().catch(() => {});
    } catch (err) {
      closeCameraModal();
      const name = err && err.name ? err.name : '';
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        toast('Kamera izni verilmedi', 'error');
      } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        toast('Kamera bulunamadi', 'error');
      } else {
        toast('Kamera acilamadi', 'error');
      }
    }
  }

  function stopCameraStream() {
    if (state.cameraStream) {
      state.cameraStream.getTracks().forEach((t) => t.stop());
      state.cameraStream = null;
    }
    const video = $('#cameraVideo');
    if (video) video.srcObject = null;
  }

  function closeCameraModal() {
    stopCameraStream();
    $('#cameraModal').classList.add('hidden');
    $('#cameraProcessing').classList.add('hidden');
  }

  async function captureAndOCR() {
    const video = $('#cameraVideo');
    const canvas = $('#cameraCanvas');
    const processing = $('#cameraProcessing');
    const processLabel = $('#cameraProcessLabel');
    const processFill = $('#cameraProcessBarFill');
    const shotBtn = $('#cameraShotBtn');

    if (!video.videoWidth || !video.videoHeight) {
      toast('Kamera henuz hazir degil', 'error');
      return;
    }

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    shotBtn.disabled = true;
    processing.classList.remove('hidden');
    processLabel.textContent = 'Hazirlaniyor...';
    processFill.style.width = '0%';

    try {
      if (!window.OCR) throw new Error('OCR modulu yuklenmedi');

      const text = await window.OCR.runOCR(canvas, (m) => {
        if (m.phase === 'recognize') {
          const pct = Math.max(0, Math.min(100, Math.floor((m.progress || 0) * 100)));
          processLabel.textContent = 'Okunuyor ' + pct + '%';
          processFill.style.width = pct + '%';
        } else if (m.phase === 'loading tesseract core' || m.phase === 'initializing tesseract') {
          processLabel.textContent = 'Motor yukleniyor...';
          processFill.style.width = '10%';
        } else if (m.phase === 'loading language traineddata' || m.phase === 'downloading') {
          processLabel.textContent = 'Dil paketi yukleniyor...';
          const pct = Math.max(10, Math.min(40, 10 + Math.floor((m.progress || 0) * 30)));
          processFill.style.width = pct + '%';
        } else if (m.phase === 'initializing api' || m.phase === 'loaded language traineddata') {
          processLabel.textContent = 'Motor hazirlaniyor...';
          processFill.style.width = '50%';
        }
      });

      const raw = window.OCR.parseWords(text);
      if (raw.length === 0) {
        toast('Metin okunamadi, tekrar cek', 'error');
        processing.classList.add('hidden');
        shotBtn.disabled = false;
        return;
      }

      state.ocrWords = window.OCR.resolveWords(raw, WORD_COUNT);
      closeCameraModal();
      openOcrConfirmModal();
    } catch (err) {
      console.error(err);
      toast('OCR hata: ' + (err && err.message ? err.message : 'bilinmeyen'), 'error');
      processing.classList.add('hidden');
      shotBtn.disabled = false;
    }
  }

  function openOcrConfirmModal() {
    $('#ocrConfirmModal').classList.remove('hidden');
    renderOcrConfirm();
  }

  function closeOcrConfirmModal() {
    $('#ocrConfirmModal').classList.add('hidden');
    state.ocrEditingIdx = -1;
  }

  function renderOcrConfirm() {
    const list = $('#ocrWordList');
    const stats = $('#ocrStats');
    list.innerHTML = '';

    let matched = 0;
    state.ocrWords.forEach((ow, idx) => {
      if (ow.matched) matched++;
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'ocr-word-chip';
      if (ow.matched) chip.classList.add('valid');
      else if (ow.value) chip.classList.add('invalid');

      const num = document.createElement('span');
      num.className = 'ocr-chip-num';
      num.textContent = (idx + 1) + '.';
      chip.appendChild(num);

      if (state.ocrEditingIdx === idx) {
        chip.classList.add('editing');
        chip.classList.remove('valid', 'invalid');
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'ocr-chip-input';
        input.value = ow.value || '';
        input.autocomplete = 'off';
        input.autocapitalize = 'none';
        input.spellcheck = false;
        input.setAttribute('autocorrect', 'off');
        input.addEventListener('input', (ev) => {
          const val = (ev.target.value || '').toLowerCase().replace(/[^a-z]/g, '');
          if (val !== ev.target.value) ev.target.value = val;
          updateOcrWord(idx, val, /* reRender */ false);
        });
        input.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter') {
            ev.preventDefault();
            finalizeOcrEdit(idx);
          } else if (ev.key === 'Escape') {
            ev.preventDefault();
            state.ocrEditingIdx = -1;
            renderOcrConfirm();
          }
        });
        input.addEventListener('blur', () => {
          setTimeout(() => finalizeOcrEdit(idx), 100);
        });
        chip.appendChild(input);
        setTimeout(() => {
          input.focus();
          input.select();
        }, 30);
      } else {
        const word = document.createElement('span');
        word.className = 'ocr-chip-word';
        word.textContent = ow.value || '—';
        chip.appendChild(word);
        chip.addEventListener('click', () => {
          state.ocrEditingIdx = idx;
          renderOcrConfirm();
        });
      }

      list.appendChild(chip);
    });

    stats.textContent = matched + ' / ' + WORD_COUNT + ' BIP-39 esleme';
    stats.classList.toggle('ok', matched === WORD_COUNT);
    stats.classList.toggle('warn', matched < WORD_COUNT);

    $('#ocrApplyBtn').disabled = false;
  }

  function updateOcrWord(idx, val, reRender) {
    const ow = state.ocrWords[idx];
    if (!ow) return;
    if (!val) {
      ow.value = '';
      ow.matched = false;
      ow.distance = null;
    } else if (window.BIP39_INDEX && val in window.BIP39_INDEX) {
      ow.value = val;
      ow.matched = true;
      ow.distance = 0;
    } else {
      ow.value = val;
      ow.matched = false;
      ow.distance = null;
    }
    if (reRender) renderOcrConfirm();
  }

  function finalizeOcrEdit(idx) {
    if (state.ocrEditingIdx !== idx) return;
    state.ocrEditingIdx = -1;
    renderOcrConfirm();
  }

  function applyOcrWords() {
    const words = state.ocrWords.map((w) => w.value || '');
    clearAll();
    fillWordsFrom(0, words);
    closeOcrConfirmModal();
    const matched = state.ocrWords.filter((w) => w.matched).length;
    if (matched === WORD_COUNT) {
      toast('23 kelime dogru eslesti', 'success');
    } else {
      toast(matched + ' / ' + WORD_COUNT + ' esleme — eksikleri elle duzelt', 'error');
    }
  }

  function retryCameraFromOcr() {
    closeOcrConfirmModal();
    openCameraModal();
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

    $('#cameraBtn').addEventListener('click', openCameraModal);
    $('#cameraCloseBtn').addEventListener('click', closeCameraModal);
    $('#cameraCancelBtn').addEventListener('click', closeCameraModal);
    $('#cameraShotBtn').addEventListener('click', captureAndOCR);

    $('#ocrCloseBtn').addEventListener('click', closeOcrConfirmModal);
    $('#ocrRetryBtn').addEventListener('click', retryCameraFromOcr);
    $('#ocrApplyBtn').addEventListener('click', applyOcrWords);

    document.querySelectorAll('[data-close="1"]').forEach((el) => {
      el.addEventListener('click', closePasteModal);
    });
    document.querySelectorAll('[data-close-camera="1"]').forEach((el) => {
      el.addEventListener('click', closeCameraModal);
    });
    document.querySelectorAll('[data-close-ocr="1"]').forEach((el) => {
      el.addEventListener('click', closeOcrConfirmModal);
    });

    document.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Escape') return;
      if (!$('#pasteModal').classList.contains('hidden')) { closePasteModal(); return; }
      if (!$('#cameraModal').classList.contains('hidden')) { closeCameraModal(); return; }
      if (!$('#ocrConfirmModal').classList.contains('hidden')) { closeOcrConfirmModal(); return; }
    });

  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ----------------------------------------------------------
  // Service worker registration (offline support + aggressive update)
  // ----------------------------------------------------------
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('./service-worker.js', {
        updateViaCache: 'none'
      }).then((reg) => {
        // Her sayfa yuklemesinde SW guncel mi kontrol et
        reg.update().catch(() => {});
      }).catch((err) => {
        console.warn('[sw] registration failed:', err);
      });

      // Yeni SW aktif oldugunda sayfayi yenile (bir kere)
      let reloaded = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (reloaded) return;
        reloaded = true;
        window.location.reload();
      });
    });
  }
})();
