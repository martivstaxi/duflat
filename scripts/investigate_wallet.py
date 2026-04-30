"""
Investigate a single TON wallet's NOT transfer history via tonapi.io.

Counts NOT transfers TO/FROM the wallet per counter-party so we can tell:
- Binance internal wallet (almost-100% Binance both sides)
- User deposit address (mostly Binance one-way)
- Trader/MM (mix of CEX + DEX + users)
- DEX pool / contract (matches DEX patterns)

Usage: python investigate_wallet.py <address> [PAGES=10]
"""
import urllib.request, urllib.error, json, base64, os, sys, time, collections

JETTON   = "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".tonapi_key")
PAGE     = 100   # max per page on this endpoint
LABELS_JSON = r"C:\Users\livea\duflat\exchanges.json"


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
    if ":" not in raw:
        return raw
    wc, h = raw.split(":")
    payload = bytes([0x51, int(wc) & 0xFF]) + bytes.fromhex(h)
    crc = crc16_xmodem(payload)
    return base64.urlsafe_b64encode(payload + crc.to_bytes(2, "big")).decode()


def http(url, key, body=None, method="GET"):
    headers = {"Accept": "application/json", "User-Agent": "DuflatInvestigate/1.0"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def fetch_account(addr, key):
    return http(f"https://tonapi.io/v2/accounts/{addr}", key)


def fetch_jetton_history(addr, key, pages=10):
    """NOT transfer events for this wallet. Paginates via before_lt cursor."""
    events = []
    before_lt = None
    for p in range(pages):
        url = (f"https://tonapi.io/v2/accounts/{addr}/jettons/{JETTON}/history"
               f"?limit={PAGE}")
        if before_lt:
            url += f"&before_lt={before_lt}"
        try:
            data = http(url, key)
        except urllib.error.HTTPError as e:
            print(f"page {p}: HTTP {e.code} — stopping", file=sys.stderr)
            break
        evs = data.get("events", [])
        if not evs:
            break
        events.extend(evs)
        before_lt = data.get("next_from") or evs[-1].get("lt")
        if not before_lt:
            break
        time.sleep(0.15 if key else 1.1)
    return events


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    target = sys.argv[1]
    pages  = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    key = load_key()
    try:
        labels = json.load(open(LABELS_JSON, encoding="utf-8"))
    except OSError:
        labels = {}

    print(f"target = {target}")
    print(f"key    = {'VAR' if key else 'YOK'}")
    print(f"pages  = {pages} (up to {pages * PAGE} events)\n")

    # 1) account info
    try:
        acc = fetch_account(target, key)
        print(f"name        : {acc.get('name')}")
        print(f"is_scam     : {acc.get('is_scam')}")
        print(f"status      : {acc.get('status')}")
        print(f"balance TON : {acc.get('balance', 0) / 1e9:.4f}")
        print(f"interfaces  : {acc.get('interfaces')}\n")
    except Exception as e:
        print(f"account fetch failed: {e}\n")

    # 2) NOT transfer history
    print("fetching NOT transfer history...")
    events = fetch_jetton_history(target, key, pages=pages)
    print(f"got {len(events)} events\n")

    # walk events, count per-counterparty inflow / outflow
    sent_to    = collections.defaultdict(lambda: {"count": 0, "amount": 0})
    received_from = collections.defaultdict(lambda: {"count": 0, "amount": 0})
    self_uq = to_uq(target) if target.startswith("0:") or target.startswith("-1:") else target

    first_ts = None
    last_ts  = None
    for ev in events:
        ts = ev.get("timestamp") or 0
        first_ts = ts if first_ts is None else min(first_ts, ts)
        last_ts  = ts if last_ts  is None else max(last_ts, ts)
        for action in ev.get("actions", []):
            if action.get("type") != "JettonTransfer":
                continue
            jt = action.get("JettonTransfer") or {}
            jetton = jt.get("jetton") or {}
            # filter to NOT only (history endpoint already filters, but be safe)
            if jetton.get("symbol") not in (None, "NOT"):
                continue
            sender    = (jt.get("sender")    or {}).get("address") or ""
            recipient = (jt.get("recipient") or {}).get("address") or ""
            amount    = int(jt.get("amount") or 0)
            sender_uq    = to_uq(sender)    if sender    else ""
            recipient_uq = to_uq(recipient) if recipient else ""

            if sender_uq == self_uq and recipient_uq:
                sent_to[recipient_uq]["count"]  += 1
                sent_to[recipient_uq]["amount"] += amount
            elif recipient_uq == self_uq and sender_uq:
                received_from[sender_uq]["count"]  += 1
                received_from[sender_uq]["amount"] += amount

    def fmt_addr(addr):
        lab = labels.get(addr, {})
        name = lab.get("name", "")
        kind = lab.get("kind", "")
        tag  = f"  [{kind}: {name}]" if name else ""
        return addr + tag

    def fmt_not(raw):
        return f"{raw / 10**9:>14,.2f} NOT"

    if first_ts and last_ts:
        from datetime import datetime, timezone
        fdate = datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        ldate = datetime.fromtimestamp(last_ts,  tz=timezone.utc).strftime("%Y-%m-%d")
        print(f"event window: {fdate} ... {ldate}\n")

    total_in  = sum(v["amount"] for v in received_from.values())
    total_out = sum(v["amount"] for v in sent_to.values())

    print("=" * 80)
    print(f"INFLOWS  (top 15)   total {fmt_not(total_in)}  from {len(received_from)} unique addresses")
    print("=" * 80)
    for addr, v in sorted(received_from.items(), key=lambda kv: -kv[1]["amount"])[:15]:
        share = v["amount"] / total_in * 100 if total_in else 0
        print(f"  {fmt_not(v['amount'])}  {share:5.1f}%  ×{v['count']:<4}  {fmt_addr(addr)}")

    print()
    print("=" * 80)
    print(f"OUTFLOWS (top 15)   total {fmt_not(total_out)}  to {len(sent_to)} unique addresses")
    print("=" * 80)
    for addr, v in sorted(sent_to.items(), key=lambda kv: -kv[1]["amount"])[:15]:
        share = v["amount"] / total_out * 100 if total_out else 0
        print(f"  {fmt_not(v['amount'])}  {share:5.1f}%  ×{v['count']:<4}  {fmt_addr(addr)}")

    # heuristic verdict
    print("\n" + "=" * 80)
    print("HEURISTIC VERDICT")
    print("=" * 80)
    binance_hot = "UQDKHZ7e70CzqdvZCC83Z4WVR8POC_ZB0J1Y4zo88G-zCSRH"
    in_binance  = received_from.get(binance_hot, {}).get("amount", 0)
    out_binance = sent_to.get(binance_hot, {}).get("amount", 0)

    in_pct  = in_binance  / total_in  * 100 if total_in  else 0
    out_pct = out_binance / total_out * 100 if total_out else 0

    cex_in  = sum(v["amount"] for a, v in received_from.items() if labels.get(a, {}).get("kind") == "cex")
    cex_out = sum(v["amount"] for a, v in sent_to.items()       if labels.get(a, {}).get("kind") == "cex")

    print(f"Binance inflow share : {in_pct:5.1f}%  ({fmt_not(in_binance)})")
    print(f"Binance outflow share: {out_pct:5.1f}%  ({fmt_not(out_binance)})")
    print(f"Total CEX inflow     : {cex_in / total_in * 100 if total_in else 0:5.1f}%")
    print(f"Total CEX outflow    : {cex_out / total_out * 100 if total_out else 0:5.1f}%")
    print(f"Unique counterparties: in={len(received_from)}  out={len(sent_to)}")

    print()
    if in_pct > 80 and out_pct > 80:
        print("=> Highly likely BINANCE-INTERNAL wallet (cold wallet / sub-wallet)")
        print("   Both sides dominated by Binance Hot Wallet — typical of CEX-controlled address.")
    elif in_pct > 60 and out_pct < 20 and len(sent_to) > 30:
        print("=> Likely a USER who deposits from Binance and trades elsewhere.")
    elif in_pct < 20 and out_pct > 60 and len(received_from) > 30:
        print("=> Likely a USER funding Binance from many sources.")
    elif in_pct + out_pct > 80:
        print("=> Strong Binance link — could be Binance-controlled OR an active trader using Binance only.")
    else:
        print("=> Mixed flow — likely a market maker or active trader.")


if __name__ == "__main__":
    main()
