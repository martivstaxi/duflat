"""Fetch BONK hourly OHLC from CoinMarketCap data-api in 400-hour chunks.

CMC returns at most 400 hourly rows per request, anchored to timeEnd. So we
walk forward in time, advancing timeEnd by ~16 days each step, dedup by
hour timestamp, and write to data/bonk_hourly.json.
"""
import urllib.request, json, time, datetime as dt, os, sys

CMC_ID = 23095          # BONK
CONVERT_ID = 2781       # USD
OUT = os.path.join(os.path.dirname(__file__), 'data', 'bonk_hourly.json')

START = dt.datetime(2022, 12, 30, 0, 0, tzinfo=dt.timezone.utc)
END   = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)

CHUNK_HOURS = 400        # API max
STEP_HOURS = 380         # leave overlap so chunks join cleanly

def fetch(ts_start, ts_end, retries=3):
    url = (f'https://api.coinmarketcap.com/data-api/v3.1/cryptocurrency/historical'
           f'?id={CMC_ID}&convertId={CONVERT_ID}&timeStart={ts_start}&timeEnd={ts_end}&interval=1h')
    last_err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r).get('data', {}).get('quotes', [])
        except Exception as e:
            last_err = e
            time.sleep(2 + i*2)
    raise RuntimeError(f'fetch failed after {retries}: {last_err}')

def main():
    by_t = {}  # 'YYYY-MM-DDTHH:00' -> {p,v}
    cursor = START
    chunks = 0
    while cursor < END + dt.timedelta(hours=CHUNK_HOURS):
        ts_end = int((cursor + dt.timedelta(hours=CHUNK_HOURS)).timestamp())
        ts_start = int((cursor - dt.timedelta(hours=4)).timestamp())  # tiny pad
        try:
            quotes = fetch(ts_start, ts_end)
        except Exception as e:
            print(f'! chunk {chunks} fail: {e}', file=sys.stderr)
            quotes = []
        chunks += 1
        added = 0
        for q in quotes:
            t = q['timeOpen'][:13] + ':00'   # 'YYYY-MM-DDTHH:00'
            qq = q.get('quote', {})
            p = qq.get('close')
            v = qq.get('volume')
            if p is None: continue
            if t not in by_t:
                added += 1
            by_t[t] = {'t': t, 'p': p, 'v': v if v is not None else 0}
        first_t = quotes[0]['timeOpen'][:16] if quotes else '-'
        last_t  = quotes[-1]['timeOpen'][:16] if quotes else '-'
        print(f'chunk {chunks:>3} cursor={cursor.strftime("%Y-%m-%d %H:%M")} got={len(quotes):>4} new={added:>4} range={first_t}..{last_t} total={len(by_t)}')
        if not quotes:
            break
        cursor = cursor + dt.timedelta(hours=STEP_HOURS)
        time.sleep(0.4)

    rows = sorted(by_t.values(), key=lambda r: r['t'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(rows, f, separators=(',', ':'))
    print(f'\nwrote {len(rows)} rows -> {OUT}')
    print(f'span: {rows[0]["t"]} .. {rows[-1]["t"]}')

if __name__ == '__main__':
    main()
