"""Fetch FLOKI hourly OHLC from CoinMarketCap data-api in 400-hour chunks.

Range: 2023-01-27 → 2023-03-27 UTC (FLOKI Q1 2023 rally penceresi).
"""
import urllib.request, json, time, datetime as dt, os, sys

CMC_ID = 10804          # FLOKI
CONVERT_ID = 2781       # USD
OUT = os.path.join(os.path.dirname(__file__), 'data', 'floki_hourly.json')

START = dt.datetime(2023, 1, 27, 0, 0, tzinfo=dt.timezone.utc)
END   = dt.datetime(2023, 3, 27, 23, 0, tzinfo=dt.timezone.utc)

CHUNK_HOURS = 400
STEP_HOURS = 380

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
    by_t = {}
    cursor = START
    chunks = 0
    start_str = START.strftime('%Y-%m-%dT%H:00')
    end_str = END.strftime('%Y-%m-%dT%H:00')
    while cursor < END + dt.timedelta(hours=CHUNK_HOURS):
        ts_end = int((cursor + dt.timedelta(hours=CHUNK_HOURS)).timestamp())
        ts_start = int((cursor - dt.timedelta(hours=4)).timestamp())
        try:
            quotes = fetch(ts_start, ts_end)
        except Exception as e:
            print(f'! chunk {chunks} fail: {e}', file=sys.stderr)
            quotes = []
        chunks += 1
        added = 0
        for q in quotes:
            t = q['timeOpen'][:13] + ':00'
            if t < start_str or t > end_str:
                continue
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
        if cursor > END + dt.timedelta(hours=CHUNK_HOURS):
            break
        time.sleep(0.4)

    rows = sorted(by_t.values(), key=lambda r: r['t'])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(rows, f, separators=(',', ':'))
    print(f'\nwrote {len(rows)} rows -> {OUT}')
    if rows:
        print(f'span: {rows[0]["t"]} .. {rows[-1]["t"]}')

if __name__ == '__main__':
    main()
