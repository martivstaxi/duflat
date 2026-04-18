/* ============================================================
   TON W5 (Wallet V5 R1) address computation
   Uses tonweb (window.TonWeb) primitives: Cell, BOC, Address
   Python referans: reference/ton_w5_finder.py :: create_w5_address
   ============================================================ */

(function () {
  'use strict';

  if (!window.TonWeb) {
    console.error('[ton-address] TonWeb not loaded');
    return;
  }

  const TonWeb = window.TonWeb;

  // W5R1 contract code BOC (657 bytes) — mainnet Wallet V5 R1
  // Hex of the exact bytes from reference/ton_w5_finder.py
  const W5R1_CODE_HEX =
    'b5ee9c7241021401000281000114ff00f4a413f4bcf2c80b01020120020d020148030402dcd020d7' +
    '49c120915b8f6320d70b1f2082106578746ebd21821073696e74bdb0925f03e082106578746eba8e' +
    'b48020d72101d074d721fa4030fa44f828fa443058bd915be0ed44d0810141d721f4058307f40e6f' +
    'a1319130e18040d721707fdb3ce03120d749810280b99130e070e2100f020120050c020120060902' +
    '016e07080019adce76a2684020eb90eb85ffc00019af1df6a2684010eb90eb858fc00201480a0b00' +
    '17b325fb51341c75c875c2c7e00011b262fb513435c280200019be5f0f6a2684080a0eb90fa02c01' +
    '02f20e011e20d70b1f82107369676ebaf2e08a7f0f01e68ef0eda2edfb218308d722028308d72320' +
    '8020d721d31fd31fd31fed44d0d200d31f20d31fd3ffd70a000af90140ccf9109a28945f0adb31e1' +
    'f2c087df02b35007b0f2d0845125baf2e0855036baf2e086f823bbf2d0882292f800de01a47fc8ca' +
    '00cb1f01cf16c9ed542092f80fde70db3cd81003f6eda2edfb02f404216e926c218e4c0221d73930' +
    '709421c700b38e2d01d72820761e436c20d749c008f2e09320d74ac002f2e09320d71d06c712c200' +
    '5230b0f2d089d74cd7393001a4e86c128407bbf2e093d74ac000f2e093ed55e2d20001c000915be0' +
    'ebd72c08142091709601d72c081c12e25210b1e30f20d74a111213009601fa4001fa44f828fa4430' +
    '58baf2e091ed44d0810141d718f405049d7fc8ca0040048307f453f2e08b8e14038307f45bf2e08c' +
    '22d70a00216e01b3b0f2d090e2c85003cf1612f400c9ed54007230d72c08248e2d21f2e092d200ed' +
    '44d0d2005113baf2d08f54503091319c01810140d721d70a00f2e08ee2c8ca0058cf16c9ed5493f2' +
    'c08de20010935bdb31e1d74cd0b4d6c35e';

  // W5R1 constants
  const NETWORK_GLOBAL_ID = -239; // mainnet
  const WORKCHAIN = 0;
  const VERSION = 0;
  const SUBWALLET = 0;

  let _cachedCodeCell = null;

  function getCodeCell() {
    if (_cachedCodeCell) return _cachedCodeCell;
    const bytes = TonWeb.utils.hexToBytes(W5R1_CODE_HEX);
    _cachedCodeCell = TonWeb.boc.Cell.oneFromBoc(bytes);
    return _cachedCodeCell;
  }

  function computeWalletId() {
    // context = (1 << 31) | (workchain << 23) | (version << 15) | subwallet
    const context = ((1 << 31) >>> 0) | (WORKCHAIN << 23) | (VERSION << 15) | SUBWALLET;
    // (network_global_id ^ context) mod 2^32
    return ((NETWORK_GLOBAL_ID ^ context) >>> 0);
  }

  /**
   * Build W5R1 data cell for a given public key.
   *   is_signature_allowed (1) || seqno (32 = 0) || wallet_id (32) || pubkey (256) || extensions (1 = 0)
   */
  function buildDataCell(pubKey) {
    const walletId = computeWalletId();
    const cell = new TonWeb.boc.Cell();
    cell.bits.writeBit(1);
    cell.bits.writeUint(0, 32);
    cell.bits.writeUint(walletId, 32);
    cell.bits.writeBytes(pubKey);
    cell.bits.writeBit(0);
    return cell;
  }

  /**
   * Build StateInit cell:
   *   split_depth+special (2) || code present (1) || data present (1) || library absent (1)
   *   refs: [code, data]
   */
  function buildStateInit(codeCell, dataCell) {
    const cell = new TonWeb.boc.Cell();
    cell.bits.writeUint(0, 2);
    cell.bits.writeBit(1);
    cell.bits.writeBit(1);
    cell.bits.writeBit(0);
    cell.refs.push(codeCell);
    cell.refs.push(dataCell);
    return cell;
  }

  /**
   * Derive W5R1 address for a public key (Uint8Array, 32 bytes).
   * Returns { raw, bounceable, non_bounceable }.
   */
  async function w5AddressFromPubkey(pubKey) {
    if (!(pubKey instanceof Uint8Array) || pubKey.length !== 32) {
      throw new Error('pubKey must be a 32-byte Uint8Array');
    }

    const codeCell = getCodeCell();
    const dataCell = buildDataCell(pubKey);
    const stateInit = buildStateInit(codeCell, dataCell);

    const addrHash = await stateInit.hash();
    const hashHex = TonWeb.utils.bytesToHex(addrHash);

    const address = new TonWeb.Address(WORKCHAIN + ':' + hashHex);

    // Address.toString(isUserFriendly, isUrlSafe, isBounceable, isTestOnly)
    return {
      raw: address.toString(false),
      bounceable: address.toString(true, true, true, false),
      non_bounceable: address.toString(true, true, false, false)
    };
  }

  window.TON_ADDRESS = Object.freeze({
    w5AddressFromPubkey: w5AddressFromPubkey,
    W5R1_CODE_HEX: W5R1_CODE_HEX,
    WALLET_ID: computeWalletId(),
    NETWORK_GLOBAL_ID: NETWORK_GLOBAL_ID,
    WORKCHAIN: WORKCHAIN
  });
})();
