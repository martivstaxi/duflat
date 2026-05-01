"""Scan 24h NOT transfer flow for all known CEX wallets in exchanges.json.

For each CEX address, walk its NOT transfer history backward and stop once
events fall outside the 24h window. Aggregate inflow/outflow by family and
by wallet-type (Hot/Cold/Deposit/Internal). Output:
  flow_reports/cex_flow_YYYY-MM-DD.json
"""
import urllib.request, urllib.error, json, base64, os, sys, time
from datetime import datetime, timezone, timedelta

JETTON     = "EQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"
KEY_FILE   = os.path.join(os.path.expanduser("~"), ".tonapi_key")
LABELS_JSON = r"C:\Users\livea\duflat\exchanges.json"
DEST_DIR   = r"C:\Users\livea\duflat\flow_reports"
PAGE       = 100         # max per history page
SLEEP      = 0.4         # between addresses
WINDOW_S   = 24 * 3600   # 24 hours


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


def http_get(url, key):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def fetch_24h_events(addr, key, since_ts):
    """Pull NOT transfer events backward until we cross since_ts. Returns the
    in-window event list."""
    events = []
    before_lt = None
    pages = 0
    while pages < 20:  # safety cap
        url = f"https://tonapi.io/v2/accounts/{addr}/jettons/{JETTON}/history?limit={PAGE}"
        if before_lt:
            url += f"&before_lt={before_lt}"
        try:
            data = http_get(url, key)
        except urllib.error.HTTPError as e:
            return events, f"HTTP {e.code}"
        except Exception as e:
            return events, str(e)
        evs = data.get("events", [])
        if not evs:
            break
        oldest_ts = min((e.get("timestamp") or 0) for e in evs)
        # keep only events inside the window
        in_window = [e for e in evs if (e.get("timestamp") or 0) >= since_ts]
        events.extend(in_window)
        if oldest_ts < since_ts:
            break  # crossed window — done
        before_lt = data.get("next_from") or evs[-1].get("lt")
        if not before_lt:
            break
        pages += 1
        time.sleep(0.05)
    return events, None


def wallet_type(name):
    """Hot / Cold / Deposit / Internal / Other based on name suffix."""
    n = (name or "").lower()
    for kw in ("cold", "deposit", "internal", "hot"):
        if kw in n:
            return kw.capitalize()
    return "Other"


def family(name):
    """Family = first whitespace-separated token, with a couple of fix-ups."""
    if not name:
        return "?"
    fam = name.split()[0]
    # 'Wallet in Telegram' -> 'Telegram Wallet'
    if fam == "Wallet" and "telegram" in name.lower():
        return "Telegram Wallet"
    # numeric suffix variants like 'Bitget12' -> 'Bitget'
    base = fam.rstrip("0123456789")
    if base in ("Bitget", "OKX", "Binance", "MEXC", "Gate.io"):
        return base
    return fam


def main():
    key = open(KEY_FILE).read().strip()
    labels = json.load(open(LABELS_JSON, encoding="utf-8"))
    cex_addrs = {a: m for a, m in labels.items() if m.get("kind") == "cex"}
    print(f"scanning {len(cex_addrs)} CEX wallets, 24h window\n")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_ts = int(datetime.now(timezone.utc).timestamp())
    since_ts = now_ts - WINDOW_S

    os.makedirs(DEST_DIR, exist_ok=True)
    out_path = os.path.join(DEST_DIR, f"cex_flow_{today}.json")

    per_wallet = {}
    errors = []

    for i, (addr, meta) in enumerate(cex_addrs.items(), 1):
        events, err = fetch_24h_events(addr, key, since_ts)
        if err:
            errors.append({"addr": addr, "name": meta.get("name", ""), "err": err})

        # accumulate inflow/outflow on this CEX wallet
        in_amt = out_amt = 0
        in_cnt = out_cnt = 0
        for ev in events:
            for action in ev.get("actions", []):
                if action.get("type") != "JettonTransfer":
                    continue
                jt = action.get("JettonTransfer") or {}
                sender    = (jt.get("sender")    or {}).get("address") or ""
                recipient = (jt.get("recipient") or {}).get("address") or ""
                amount    = int(jt.get("amount") or 0)
                sender_uq    = to_uq(sender)    if sender    else ""
                recipient_uq = to_uq(recipient) if recipient else ""
                if recipient_uq == addr and sender_uq:
                    in_amt += amount
                    in_cnt += 1
                elif sender_uq == addr and recipient_uq:
                    out_amt += amount
                    out_cnt += 1

        per_wallet[addr] = {
            "name":        meta.get("name", ""),
            "family":      family(meta.get("name", "")),
            "type":        wallet_type(meta.get("name", "")),
            "inflow_NOT":  in_amt / 1e9,
            "outflow_NOT": out_amt / 1e9,
            "inflow_n":    in_cnt,
            "outflow_n":   out_cnt,
            "events":      len(events),
        }

        if i % 25 == 0 or i == len(cex_addrs):
            print(f"  [{i:>3}/{len(cex_addrs)}] last={meta.get('name','?')[:30]:<30}  ev={len(events)}  in={in_amt/1e9:>10,.0f}  out={out_amt/1e9:>10,.0f}")
        time.sleep(SLEEP)

    # rollup by family
    by_family = {}
    by_type = {}
    total_in = total_out = 0
    total_in_n = total_out_n = 0
    for w in per_wallet.values():
        fam = w["family"]
        typ = w["type"]
        by_family.setdefault(fam, {"inflow_NOT": 0, "outflow_NOT": 0, "inflow_n": 0, "outflow_n": 0, "wallets": 0})
        by_family[fam]["inflow_NOT"]  += w["inflow_NOT"]
        by_family[fam]["outflow_NOT"] += w["outflow_NOT"]
        by_family[fam]["inflow_n"]    += w["inflow_n"]
        by_family[fam]["outflow_n"]   += w["outflow_n"]
        by_family[fam]["wallets"]     += 1

        by_type.setdefault(typ, {"inflow_NOT": 0, "outflow_NOT": 0, "inflow_n": 0, "outflow_n": 0, "wallets": 0})
        by_type[typ]["inflow_NOT"]  += w["inflow_NOT"]
        by_type[typ]["outflow_NOT"] += w["outflow_NOT"]
        by_type[typ]["inflow_n"]    += w["inflow_n"]
        by_type[typ]["outflow_n"]   += w["outflow_n"]
        by_type[typ]["wallets"]     += 1

        total_in     += w["inflow_NOT"]
        total_out    += w["outflow_NOT"]
        total_in_n   += w["inflow_n"]
        total_out_n  += w["outflow_n"]

    report = {
        "date":         today,
        "since_ts":     since_ts,
        "now_ts":       now_ts,
        "window_hours": 24,
        "n_cex_wallets":len(cex_addrs),
        "totals": {
            "inflow_NOT":   round(total_in, 2),
            "outflow_NOT":  round(total_out, 2),
            "net_NOT":      round(total_in - total_out, 2),
            "inflow_n":     total_in_n,
            "outflow_n":    total_out_n,
        },
        "by_family": {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                      for k, v in sorted(by_family.items(), key=lambda kv: -kv[1]["inflow_NOT"] - kv[1]["outflow_NOT"])},
        "by_type":   {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                      for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]["inflow_NOT"] - kv[1]["outflow_NOT"])},
        "errors":    errors,
        "per_wallet": per_wallet,
    }

    json.dump(report, open(out_path, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"\nsaved -> {out_path} ({size_kb:.1f} KB)")

    print("\n=== TOTALS (24h) ===")
    print(f"  inflow:  {total_in:>14,.0f} NOT  ×{total_in_n}")
    print(f"  outflow: {total_out:>14,.0f} NOT  ×{total_out_n}")
    print(f"  net:     {total_in - total_out:>14,.0f} NOT")

    print("\n=== BY FAMILY ===")
    for fam, v in report["by_family"].items():
        net = v["inflow_NOT"] - v["outflow_NOT"]
        print(f"  {fam:<18} wallets={v['wallets']:<3}  in={v['inflow_NOT']:>12,.0f} ×{v['inflow_n']:<5}  out={v['outflow_NOT']:>12,.0f} ×{v['outflow_n']:<5}  net={net:>12,.0f}")

    print("\n=== BY TYPE ===")
    for typ, v in report["by_type"].items():
        net = v["inflow_NOT"] - v["outflow_NOT"]
        print(f"  {typ:<10} wallets={v['wallets']:<4}  in={v['inflow_NOT']:>12,.0f} ×{v['inflow_n']:<5}  out={v['outflow_NOT']:>12,.0f} ×{v['outflow_n']:<5}  net={net:>12,.0f}")

    if errors:
        print(f"\n{len(errors)} errors")


if __name__ == "__main__":
    main()
