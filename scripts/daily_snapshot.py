"""Daily top 9K NOT-holder snapshot. Saves to snapshots/YYYY-MM-DD.json.
Idempotent — skips if today's snapshot already exists."""
import urllib.request, json, base64, os, sys, time
from datetime import datetime, timezone

JETTON   = "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".tonapi_key")
DEST_DIR = r"C:\Users\livea\duflat\snapshots"
PAGE     = 1000      # tonapi cap
TARGET   = 9000      # tonapi holders cap
SLEEP    = 0.3


def crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def to_uq(raw):
    if ":" not in raw:
        return raw
    wc, h = raw.split(":")
    payload = bytes([0x51, int(wc) & 0xFF]) + bytes.fromhex(h)
    return base64.urlsafe_b64encode(payload + crc16(payload).to_bytes(2, "big")).decode()


def fetch_page(key, offset, limit):
    url = f"https://tonapi.io/v2/jettons/{JETTON}/holders?limit={limit}&offset={offset}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    key = open(KEY_FILE).read().strip()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    os.makedirs(DEST_DIR, exist_ok=True)
    out = os.path.join(DEST_DIR, f"{today}.json")

    if os.path.exists(out) and "--force" not in sys.argv:
        print(f"snapshot already exists, skipping: {out}")
        return 0

    holders = []
    offset = 0
    while len(holders) < TARGET:
        limit = min(PAGE, TARGET - len(holders))
        try:
            data = fetch_page(key, offset, limit)
        except Exception as e:
            print(f"  fetch error at offset {offset}: {e}", file=sys.stderr)
            break
        addrs = data.get("addresses", [])
        if not addrs:
            break
        for h in addrs:
            owner = h.get("owner") or {}
            raw = owner.get("address") or h.get("address")
            if not raw:
                continue
            bal = int(h.get("balance", "0")) / 1e9
            holders.append({
                "rank":    len(holders) + 1,
                "addr":    to_uq(raw),
                "balance": round(bal, 4),
            })
            if len(holders) >= TARGET:
                break
        offset += len(addrs)
        print(f"  fetched {len(holders)}/{TARGET}")
        time.sleep(SLEEP)

    snap = {
        "date":          today,
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
        "total_holders": len(holders),
        "total_NOT":     round(sum(h["balance"] for h in holders), 2),
        "holders":       holders,
    }
    json.dump(snap, open(out, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    size_mb = os.path.getsize(out) / 1024 / 1024
    print(f"saved -> {out} ({len(holders)} holders, {size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
