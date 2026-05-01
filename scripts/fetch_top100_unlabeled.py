"""Fetch top 100 NOT holders, filter out already-labeled (in exchanges.json),
print the unlabeled ones with rank + balance for the next investigation pass."""
import urllib.request, json, base64, os, sys, time

JETTON   = "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".tonapi_key")
LABELS   = r"C:\Users\livea\duflat\exchanges.json"
OUT      = r"C:\Users\livea\duflat\scripts\top100_unlabeled.json"


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


def main():
    key = open(KEY_FILE).read().strip()
    url = f"https://tonapi.io/v2/jettons/{JETTON}/holders?limit=100&offset=0"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())

    labels = json.load(open(LABELS, encoding="utf-8"))

    holders = []
    for i, h in enumerate(data.get("addresses", []), 1):
        owner = h.get("owner") or {}
        raw = owner.get("address") or h.get("address")
        bal = int(h.get("balance", "0")) / 1e9  # NOT has 9 decimals
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

    unlabeled = [h for h in holders if not h["labeled"]]
    print(f"Top 100: {len(holders)} holders, {len(unlabeled)} unlabeled\n")
    print(f"{'#':>3} {'NOT':>14}  address                                            tonapi_name")
    print("-" * 110)
    for h in unlabeled:
        print(f"{h['rank']:>3} {h['balance_NOT']:>14,.2f}  {h['address']}  {h['tonapi_name']}")

    json.dump(holders, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
