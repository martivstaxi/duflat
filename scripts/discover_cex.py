"""
Discover known/labeled addresses among top NOT holders via tonapi.io,
classify into cex / protocol / named, and emit a JS LABELS map.

Output:
  C:\\Users\\livea\\duflat\\exchanges.json   — { addr: {name, kind, is_scam} }
  C:\\Users\\livea\\duflat\\exchanges.js     — `const LABELS = {...};` snippet

Usage: python discover_cex.py [TOP_N=9000]   # 9000 = tonapi.io holders cap
"""
import urllib.request, urllib.error, json, base64, os, sys, time

JETTON   = "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".tonapi_key")
OUT_JSON = r"C:\Users\livea\duflat\exchanges.json"
OUT_JS   = r"C:\Users\livea\duflat\exchanges.js"
PAGE     = 1000   # tonapi holders page size cap
BULK     = 100    # accounts/_bulk cap

CEX_KEYWORDS = [
    "binance", "okx", "bybit", "mexc", "gate.io", "gateio", "bitget",
    "kucoin", "htx", "huobi", "bitrue", "coinspot", "lbank", "rapira",
    "ompfinex", "bitkub", "coinbase", "kraken", "telegram wallet",
    "wallet in telegram", "bitfinex", "crypto.com", "bitmart", "bitstamp",
    "bingx", "whitebit", "phemex", "poloniex", "fragment market",
    "paribu", "btcturk", "btc-turk", "binance tr", "garantex", "exmo",
    "farhad exchange", "exchange", "exch.io", "cwallet",
    "bitvavo", "upbit", "bithumb", "korbit", "bitflyer", "indodax",
    "max maicoin", "ascendex", "deepcoin",
]
PROTOCOL_KEYWORDS = [
    "ston.fi", "dedust", "voucher swap", "minter", "vault", "elector",
    "tonstakers", "evaa", "storm", "megaton", "notcoin", "fragment",
    "tonkeeper battery", "tonhub", "tonco", "ton diamonds",
    "ton foundation",
]

# Manual overrides — wins over tonapi.io's name + auto-classification.
# Use for cases where on-chain flow analysis reveals the true owner
# (e.g. CEX consolidation wallets that ops staff renamed to junk .ton domains).
MANUAL_OVERRIDES = {
    # Binance deposit/consolidation wallet (was labeled "selling-domain-dogs.ton"):
    # 100% outflow to Binance Hot, 70% inflow from Binance Hot, 42M TON balance.
    "UQD4uGNdB4a3f52mYOZf0x1nCmdd1DAvrLppL0a1cetTYCQx":
        {"name": "Binance Deposit", "kind": "cex"},
    # Second Binance hot wallet — tonapi already names it "Binance Hot Wallet"
    # but it wasn't in our top-9000 NOT holders so the discovery missed it.
    "UQCOkbUDgcNt1CrM21H1y12WhIVotJJPgHmxpa5-EPQ-2iNl":
        {"name": "Binance Hot Wallet 2", "kind": "cex"},

    # ---- 2026-05-01 batch: top-100 unlabeled holders, NOT-flow analysis ----
    # All entries below: tonapi has no name; flow shows >=85% inflow from a
    # single CEX family with ~zero outflow (sub/cold pattern) — or both sides
    # >=85% same family (internal). Source: scripts/batch_flow_report.json.
    # rank#10, in:97.0% OKX, out~0, ev=10, bal=1438M NOT
    "UQB_LPN1koEFYocWeuKaAkDTQMFFycDs9CGrwPLpnJQ0U6Gy":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#15, in:85.8%/out:99.5% OKX, ev=45, bal=1172M NOT
    "UQCkdi_s8DUFA1kjX5jrr7oLG0SbVTGK4-Q52Yvdw1cRGfku":
        {"name": "OKX Internal", "kind": "cex"},
    # rank#18, in:85.7% OKX, out~0, ev=7, bal=994M NOT
    "UQBmlAmSmKc6GbesAPi3Pk6i-ooyUPXgFS2LmLv0uTXqP-ei":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#24, in:100.0% Binance, out~0, ev=3, bal=696M NOT
    "UQDYM0YvFy2-1J4vTsn_GKUx8UKBCvs2A5QKJt8wVTXqhsK0":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#25, in:100.0%/out:100.0% OKX, ev=499, bal=644M NOT
    "UQDY4-KtVxawZU_Vva7KTOhlhx8Ho0jI0ahyebYT5YuJkYSf":
        {"name": "OKX Internal", "kind": "cex"},
    # rank#27, in:100.0% Binance, out~0, ev=130, bal=610M NOT
    "UQCiErgR_u2U30EI2G5RzLfLANOhzOz8jXU5K2bkVOtczTcP":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#28, in:100.0% Binance, out~0, ev=17, bal=598M NOT
    "UQAPykgBUhbI2Fz_JNhT89NhT8HTKSw3Im32EipXtqLSIkmt":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#44, in:87.4% OKX, out~0, ev=8, bal=201M NOT
    "UQCgJMAdLq3CtecfGqKY3bJye9kjrDp6BW_MnW_7zwclJQKz":
        {"name": "OKX Cold", "kind": "cex"},
    # rank#50, in:100.0% lbank.info, out~0, ev=3, bal=151M NOT
    "UQDg5iDIqj8O4xHM0rsL26Vo_a4OKZnblc_EI6LJ37kRC1AC":
        {"name": "lbank.info Cold", "kind": "cex"},
    # rank#56, in:100.0% Binance, out~0, ev=2, bal=122M NOT
    "UQDQKawuKNAAC6NJuiBsnyr8ewqCLuFmYWavUoP7BIVxAmVC":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#57, in:100.0% Binance, out~0, ev=2, bal=120M NOT
    "UQDmTo2Aun0l40gEng6BiidXALpwEdAOdxNzHOGYQ3p5x5Sj":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#74, in:100.0% Binance, out~0, ev=2, bal=80M NOT
    "UQCJGVn5fz2lGruG3QUfKhU07MvKHEhxQhzheiyvSFlraxwP":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#78, in:100.0% Bitget, out~0, ev=22, bal=71M NOT
    "UQDNVsqiDSHhUKPCp6tf0kRXvYpGkXaKmNtXKJ5nxiUPqRD0":
        {"name": "Bitget Cold", "kind": "cex"},
    # rank#80, in:87.4% Binance, out~0, ev=26, bal=68M NOT
    "UQDEYl2dmHSU2pvoSE8CS-PwkjGNcrq3A6v-B7X6Ly44OcE1":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#83, in:100.0% Binance, out~0, ev=2, bal=63M NOT
    "UQCEfvjUxopnkTkFfAR9LEvQhwEm_1CEOTUWausV2BfnTcUy":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#88, in:100.0% Binance, out~0, ev=3, bal=58M NOT
    "UQArhe9wZz4NYlLdaJHJHX70fxUKhUlmAP2t1nSGcf2k3Sw3":
        {"name": "Binance Cold", "kind": "cex"},
    # rank#92, in:100.0% OKX, out~0, ev=3, bal=56M NOT
    "UQAD8XEJQppmZDZvlTAKopt2E_c-Xbhzt7_vKH98W4qB5HOs":
        {"name": "OKX Cold", "kind": "cex"},
}


def classify(name: str) -> str:
    n = (name or "").lower()
    is_domain = n.endswith(".ton") or n.endswith(".t.me")
    for kw in CEX_KEYWORDS:
        if kw in n:
            return "cex"
    # personal .ton / .t.me domains shouldn't match protocol keywords
    # (e.g. "notnotcoiner.ton", "durovfragment.t.me" are people, not protocols)
    if not is_domain:
        for kw in PROTOCOL_KEYWORDS:
            if kw in n:
                return "protocol"
    return "named"


def load_key():
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def to_uq(raw: str) -> str:
    wc, h = raw.split(":")
    payload = bytes([0x51, int(wc) & 0xFF]) + bytes.fromhex(h)
    crc = crc16_xmodem(payload)
    return base64.urlsafe_b64encode(payload + crc.to_bytes(2, "big")).decode()


def http(method, url, key, body=None):
    headers = {"Accept": "application/json", "User-Agent": "DuflatCEXDiscover/1.0"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def fetch_holders(target, key):
    rows = []
    offset = 0
    while len(rows) < target:
        limit = min(PAGE, target - len(rows))
        url = f"https://tonapi.io/v2/jettons/{JETTON}/holders?limit={limit}&offset={offset}"
        data = http("GET", url, key)
        addrs = data.get("addresses", [])
        if not addrs:
            break
        for h in addrs:
            owner = h.get("owner") or {}
            raw = owner.get("address") or h.get("address")
            if not raw:
                continue
            try:
                rows.append(to_uq(raw))
            except Exception:
                rows.append(raw)
            if len(rows) >= target:
                break
        offset += len(addrs)
        time.sleep(0.15 if key else 1.1)
    return rows


def bulk_accounts(addrs, key):
    out = {}
    for i in range(0, len(addrs), BULK):
        chunk = addrs[i:i + BULK]
        url = "https://tonapi.io/v2/accounts/_bulk"
        try:
            data = http("POST", url, key, {"account_ids": chunk})
        except urllib.error.HTTPError as e:
            print(f"  bulk {i}: HTTP {e.code} — skipping batch", file=sys.stderr)
            time.sleep(2)
            continue
        for acc in data.get("accounts", []):
            addr = acc.get("address")
            name = acc.get("name")
            is_scam = acc.get("is_scam", False)
            if not addr:
                continue
            try:
                addr_uq = to_uq(addr) if ":" in addr else addr
            except Exception:
                addr_uq = addr
            if name or is_scam:
                out[addr_uq] = {"name": name or "", "is_scam": is_scam}
        print(f"  bulk {i}/{len(addrs)} -> {len(out)} labeled so far")
        time.sleep(0.15 if key else 1.1)
    return out


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    key = load_key()
    print(f"key={'VAR(' + str(len(key)) + ')' if key else 'YOK'} target={target}")
    print("fetching holders...")
    addrs = fetch_holders(target, key)
    print(f"got {len(addrs)} addresses")
    print("querying account labels...")
    labels = bulk_accounts(addrs, key)

    # classify
    counts = {"cex": 0, "protocol": 0, "named": 0}
    for addr, meta in labels.items():
        meta["kind"] = classify(meta.get("name", ""))
        counts[meta["kind"]] += 1
    print(f"\n{len(labels)} labeled  |  cex={counts['cex']}  protocol={counts['protocol']}  named={counts['named']}")

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)
    print(f"saved -> {OUT_JSON}")

    # emit JS snippet for inline embedding in NOT.html
    items = sorted(labels.items(), key=lambda kv: (kv[1]["kind"], kv[1]["name"]))
    lines = ["const LABELS = {"]
    last_kind = None
    for addr, meta in items:
        if meta["kind"] != last_kind:
            lines.append(f"  // {meta['kind']}")
            last_kind = meta["kind"]
        name_js = json.dumps(meta["name"])
        lines.append(f'  "{addr}": {{ name: {name_js}, kind: "{meta["kind"]}" }},')
    lines.append("};")
    with open(OUT_JS, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"saved -> {OUT_JS}")


if __name__ == "__main__":
    main()
