"""
Discover known/labeled addresses among top NOT holders via tonapi.io.

Output: C:\\Users\\livea\\duflat\\exchanges.json
        { "address_uq": { "name": "Binance Hot Wallet", "is_scam": false }, ... }

Usage: python discover_cex.py [TOP_N=1000]
"""
import urllib.request, urllib.error, json, base64, os, sys, time

JETTON   = "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".tonapi_key")
OUT_FILE = r"C:\Users\livea\duflat\exchanges.json"
PAGE     = 1000   # tonapi holders page size cap
BULK     = 100    # accounts/_bulk cap


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
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    key = load_key()
    print(f"key={'VAR(' + str(len(key)) + ')' if key else 'YOK'} target={target}")
    print("fetching holders...")
    addrs = fetch_holders(target, key)
    print(f"got {len(addrs)} addresses")
    print("querying account labels...")
    labels = bulk_accounts(addrs, key)
    print(f"\n{len(labels)} labeled addresses:")
    for addr, meta in sorted(labels.items(), key=lambda kv: kv[1]["name"]):
        print(f"  {meta['name']:<40} {addr}")
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)
    print(f"\nsaved -> {OUT_FILE}")


if __name__ == "__main__":
    main()
