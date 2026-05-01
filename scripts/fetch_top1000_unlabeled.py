"""Fetch top 1000 NOT holders, return rank 101-1000 unlabeled subset."""
import urllib.request, json, base64, os, sys, time

JETTON   = "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".tonapi_key")
LABELS   = r"C:\Users\livea\duflat\exchanges.json"
OUT      = r"C:\Users\livea\duflat\scripts\top1000_unlabeled.json"
START_RANK = 101  # skip top 100 (already done)
END_RANK   = 1000


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
    labels = json.load(open(LABELS, encoding="utf-8"))

    # tonapi page cap = 1000
    print(f"fetching top 1000 NOT holders...")
    data = fetch_page(key, 0, 1000)
    addrs = data.get("addresses", [])
    print(f"got {len(addrs)} holders\n")

    holders = []
    for i, h in enumerate(addrs, 1):
        owner = h.get("owner") or {}
        raw = owner.get("address") or h.get("address")
        bal = int(h.get("balance", "0")) / 1e9
        addr = to_uq(raw)
        holders.append({
            "rank": i,
            "address": addr,
            "balance_NOT": round(bal, 2),
            "tonapi_name": owner.get("name", ""),
            "is_scam": owner.get("is_scam", False),
            "labeled": addr in labels,
            "label": labels.get(addr, {}).get("name", ""),
            "label_kind": labels.get(addr, {}).get("kind", ""),
        })

    # filter to rank 101-1000 unlabeled
    target = [h for h in holders if START_RANK <= h["rank"] <= END_RANK and not h["labeled"]]
    print(f"rank {START_RANK}-{END_RANK}: {sum(1 for h in holders if START_RANK <= h['rank'] <= END_RANK)} total, "
          f"{len(target)} unlabeled\n")

    # quick label distribution sanity
    labeled_in_range = sum(1 for h in holders if START_RANK <= h["rank"] <= END_RANK and h["labeled"])
    print(f"already labeled in this range: {labeled_in_range}")

    json.dump(target, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nsaved -> {OUT}")
    print(f"first 5 sample:")
    for h in target[:5]:
        print(f"  rank#{h['rank']:<4} bal={h['balance_NOT']:>14,.0f}  {h['address']}  tonapi={h['tonapi_name']!r}")


if __name__ == "__main__":
    main()
