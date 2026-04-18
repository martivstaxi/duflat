/* ============================================================
   TON Native crypto (Web Crypto API)
   Python referans: reference/ton_w5_finder.py
   ============================================================

   Python eslenikleri:

   ton_mnemonic_to_entropy(words, password=""):
       mnemonic_str = " ".join(words)
       return HMAC-SHA512(key=mnemonic_str, data=password)

   ton_is_basic_seed(entropy):
       seed = PBKDF2-SHA512(entropy, "TON seed version", 390, 64)
       return seed[0] == 0

   ton_seed_for_keypair(entropy):  # Ed25519 icin
       seed = PBKDF2-SHA512(entropy, "TON default seed", 100000, 64)
       return seed[0:32]
   ============================================================ */

(function () {
  'use strict';

  const textEncoder = new TextEncoder();

  // ----------------------------------------------------------
  // Utils
  // ----------------------------------------------------------
  function strToBytes(s) {
    return textEncoder.encode(s);
  }

  function bytesToHex(bytes) {
    const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    let hex = '';
    for (let i = 0; i < b.length; i++) {
      const h = b[i].toString(16);
      hex += h.length === 1 ? '0' + h : h;
    }
    return hex;
  }

  // ----------------------------------------------------------
  // HMAC-SHA512
  // entropy = HMAC-SHA512(key=mnemonic, data=password)
  // ----------------------------------------------------------
  async function hmacSha512(key, data) {
    const cryptoKey = await crypto.subtle.importKey(
      'raw',
      key,
      { name: 'HMAC', hash: { name: 'SHA-512' } },
      false,
      ['sign']
    );
    const sig = await crypto.subtle.sign('HMAC', cryptoKey, data);
    return new Uint8Array(sig);
  }

  async function tonMnemonicToEntropy(words, password) {
    const mnemonicStr = words.join(' ');
    const keyBytes = strToBytes(mnemonicStr);
    const dataBytes = strToBytes(password || '');
    return hmacSha512(keyBytes, dataBytes);
  }

  // ----------------------------------------------------------
  // PBKDF2-SHA512
  // ----------------------------------------------------------
  async function pbkdf2Sha512(password, salt, iterations, bytesLen) {
    const baseKey = await crypto.subtle.importKey(
      'raw',
      password,
      { name: 'PBKDF2' },
      false,
      ['deriveBits']
    );
    const bits = await crypto.subtle.deriveBits(
      {
        name: 'PBKDF2',
        salt: salt,
        iterations: iterations,
        hash: 'SHA-512'
      },
      baseKey,
      bytesLen * 8
    );
    return new Uint8Array(bits);
  }

  // ----------------------------------------------------------
  // TON basic seed check
  // PBKDF2(entropy, "TON seed version", 390, 64) -> seed[0] == 0
  // ----------------------------------------------------------
  const SALT_SEED_VERSION = strToBytes('TON seed version');
  const SALT_DEFAULT_SEED = strToBytes('TON default seed');
  const BASIC_SEED_ITERS = Math.max(1, Math.floor(100000 / 256)); // = 390
  const DEFAULT_SEED_ITERS = 100000;

  async function tonIsBasicSeed(entropy) {
    const seed = await pbkdf2Sha512(entropy, SALT_SEED_VERSION, BASIC_SEED_ITERS, 64);
    return seed[0] === 0;
  }

  async function tonSeedForKeypair(entropy) {
    const seed = await pbkdf2Sha512(entropy, SALT_DEFAULT_SEED, DEFAULT_SEED_ITERS, 64);
    return seed.slice(0, 32);
  }

  // ----------------------------------------------------------
  // Scan 2048 wordlist for valid 24th candidates
  // Returns: Array<{ word, idx, mnemonic }>
  // onProgress(done, total) called periodically
  // ----------------------------------------------------------
  async function tonFindCandidates(words23, wordlist, onProgress) {
    if (!Array.isArray(words23) || words23.length !== 23) {
      throw new Error('words23 must be an array of length 23');
    }
    if (!Array.isArray(wordlist) || wordlist.length !== 2048) {
      throw new Error('wordlist must be an array of 2048 BIP-39 words');
    }

    const candidates = [];
    const total = wordlist.length;

    for (let i = 0; i < total; i++) {
      const word = wordlist[i];
      const testWords = words23.concat([word]);
      const entropy = await tonMnemonicToEntropy(testWords, '');
      const isBasic = await tonIsBasicSeed(entropy);
      if (isBasic) {
        candidates.push({ word: word, idx: i, mnemonic: testWords });
      }
      if (onProgress && (i % 32 === 0 || i === total - 1)) {
        onProgress(i + 1, total, candidates.length);
        // yield to UI
        await new Promise((r) => setTimeout(r, 0));
      }
    }

    return candidates;
  }

  // ----------------------------------------------------------
  // Export
  // ----------------------------------------------------------
  window.TON_CRYPTO = Object.freeze({
    hmacSha512: hmacSha512,
    pbkdf2Sha512: pbkdf2Sha512,
    tonMnemonicToEntropy: tonMnemonicToEntropy,
    tonIsBasicSeed: tonIsBasicSeed,
    tonSeedForKeypair: tonSeedForKeypair,
    tonFindCandidates: tonFindCandidates,
    bytesToHex: bytesToHex,
    BASIC_SEED_ITERS: BASIC_SEED_ITERS,
    DEFAULT_SEED_ITERS: DEFAULT_SEED_ITERS,
  });
})();
