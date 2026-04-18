/* ============================================================
   TON wallet keypair derivation
   Python referans:
       entropy = HMAC-SHA512(mnemonic, "")
       seed    = PBKDF2-SHA512(entropy, "TON default seed", 100000, 64)[:32]
       signingKey = nacl.signing.SigningKey(seed)
       publicKey  = signingKey.verify_key
   ============================================================ */

(function () {
  'use strict';

  if (!window.nacl) {
    console.error('[ton-wallet] tweetnacl (window.nacl) not loaded');
    return;
  }
  if (!window.TON_CRYPTO) {
    console.error('[ton-wallet] TON_CRYPTO not loaded');
    return;
  }

  const nacl = window.nacl;
  const TON = window.TON_CRYPTO;

  /**
   * Derive TON keypair from a 24-word mnemonic (or any word array).
   * @param {string[]} mnemonic
   * @returns {Promise<{publicKey: Uint8Array, secretKey: Uint8Array, seed: Uint8Array}>}
   */
  async function deriveKeypair(mnemonic) {
    const entropy = await TON.tonMnemonicToEntropy(mnemonic, '');
    const seed = await TON.tonSeedForKeypair(entropy); // 32 bytes
    const kp = nacl.sign.keyPair.fromSeed(seed);
    return {
      publicKey: kp.publicKey,    // 32 bytes
      secretKey: kp.secretKey,    // 64 bytes (includes pub at [32:])
      seed: seed                  // 32 bytes
    };
  }

  window.TON_WALLET = Object.freeze({
    deriveKeypair: deriveKeypair
  });
})();
