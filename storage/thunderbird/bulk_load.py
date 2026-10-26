"""Stdlib bulk loader: Thunderbird.log lines -> {"@timestamp", "message"}. usage: bulk_load.py FILE INDEX OP(create|index) WORKERS"""
import http.client, json, os, sys, time
from multiprocessing import Pool
from datetime import datetime, timezone

FILE, INDEX, OP, W = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
BATCH = 20000
ACTION = json.dumps({OP: {}}) + "\n"

def iso(e):
    return datetime.fromtimestamp(e, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def bounds():
    n = os.path.getsize(FILE); cuts = [0]
    with open(FILE, "rb") as f:
        for i in range(1, W):
            f.seek(n * i // W); f.readline(); cuts.append(f.tell())
    return list(zip(cuts, cuts[1:] + [n]))

def post(conn, body):
    conn.request("POST", f"/{INDEX}/_bulk?filter_path=errors,items.*.error", body.encode("utf-8"), {"Content-Type": "application/x-ndjson"})
    r = conn.getresponse(); d = json.loads(r.read())
    if r.status != 200 or d.get("errors"):
        raise SystemExit(f"bulk failed: {r.status} {json.dumps(d)[:600]}")

def work(span):
    lo, hi = span; conn = http.client.HTTPConnection("127.0.0.1", 9200, timeout=600)
    docs = fb = 0; prev = None; cache_e = None; cache_s = None; buf = []
    with open(FILE, "rb") as f:
        f.seek(lo)
        while f.tell() < hi:
            line = f.readline()
            if not line: break
            text = line.rstrip(b"\n").decode("utf-8", "replace")
            parts = text.split(" ", 2)
            try: e = int(parts[1])
            except (IndexError, ValueError): e = None
            if e is None:
                fb += 1; e = prev if prev is not None else 0
            prev = e
            if e != cache_e: cache_e, cache_s = e, iso(e)
            buf.append(ACTION + '{"@timestamp":"' + cache_s + '","message":' + json.dumps(text, ensure_ascii=False) + "}\n")
            docs += 1
            if len(buf) == BATCH: post(conn, "".join(buf)); buf = []
    if buf: post(conn, "".join(buf))
    return docs, fb

if __name__ == "__main__":
    t = time.time()
    with Pool(W) as p: res = p.map(work, bounds(), chunksize=1)
    print(json.dumps({"index": INDEX, "docs_sent": sum(r[0] for r in res), "fallback_ts_lines": sum(r[1] for r in res), "load_s": round(time.time() - t, 1)}))
