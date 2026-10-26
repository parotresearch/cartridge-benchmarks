#!/usr/bin/env python3 -I
"""Stdlib bulk loader: NDJSON file -> ES. Splices @timestamp (epoch ms from the line's "timestamp":"sec.nanos") in front of each document.
usage: load.py FILE TARGET ACTION(create|index) OUT_JSON"""
import http.client, json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

path, target, action, out = sys.argv[1:5]
BATCH, WORKERS = 4000, 4
ts_re = re.compile(r'"timestamp":"(\d+)\.(\d+)"')
lock = threading.Lock()
st = dict(lines=0, ts_fail=0, indexed=0, errors=0, err_samples=[], retries=0)
local = threading.local()

def conn():
    if not hasattr(local, "c"):
        local.c = http.client.HTTPConnection("127.0.0.1", 9200, timeout=600)
    return local.c

def send(body, n):
    for attempt in range(8):
        c = conn()
        c.request("POST", f"/{target}/_bulk", body, {"Content-Type": "application/x-ndjson"})
        r = c.getresponse(); data = r.read()
        if r.status == 429:
            with lock: st["retries"] += 1
            time.sleep(2 * (attempt + 1)); continue
        if r.status != 200:
            raise SystemExit(f"bulk HTTP {r.status}: {data[:500]!r}")
        res = json.loads(data)
        bad = [it[action] for it in res["items"] if it[action].get("status", 200) >= 300]
        with lock:
            st["indexed"] += n - len(bad); st["errors"] += len(bad)
            for b in bad:
                if len(st["err_samples"]) < 5: st["err_samples"].append(b.get("error"))
        return
    raise SystemExit("bulk still 429 after 8 attempts")

def main():
    t0 = time.time()
    ex = ThreadPoolExecutor(WORKERS); sem = threading.BoundedSemaphore(WORKERS * 2); futs = []
    meta = '{"%s":{}}\n' % action
    buf, n = [], 0
    def flush():
        nonlocal buf, n
        if not n: return
        sem.acquire(); body = "".join(buf).encode(); cnt = n; buf, n = [], 0
        f = ex.submit(lambda: (send(body, cnt), sem.release())); futs.append(f)
        if len(futs) > 64: [x.result() for x in futs]; futs.clear()
    with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="\n") as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = ts_re.search(line)
            if m: line = '{"@timestamp":%s%s,%s' % (m.group(1), m.group(2)[:3].ljust(3, "0"), line[1:])
            else: st["ts_fail"] += 1
            buf.append(meta); buf.append(line + "\n"); n += 1; st["lines"] += 1
            if n >= BATCH: flush()
            if st["lines"] % 1_000_000 == 0: print(f"{st['lines']} lines {time.time()-t0:.0f}s errors={st['errors']}", flush=True)
    flush(); [x.result() for x in futs]; ex.shutdown()
    st["wall_s"] = round(time.time() - t0, 1)
    json.dump(st, open(out, "w")); print(json.dumps(st))
    if st["errors"] or st["indexed"] != st["lines"]: print("WARN: rejections", file=sys.stderr)

main()
