#!/usr/bin/env python3
"""Bulk-load the CloudTrail NDJSON into one ES index and report indexed vs rejected docs.

usage: 03-es-load.py <index> <A|B|C> <events.ndjson> <out.json>
  A  default dynamic mapping (expect `Limit of total fields [1000] has been exceeded` rejections)
  B  requestParameters / responseElements / additionalEventData / serviceEventDetails mapped `flattened`, rest dynamic
  C  B plus index.mode=logsdb (copies eventTime into @timestamp, which logsdb requires)
Stdlib only. Never retries a rejected doc: a rejection is the measurement.
"""
import collections
import json
import sys
import time
import urllib.request

ES = "http://127.0.0.1:9200"
FLAT = ["requestParameters", "responseElements", "additionalEventData", "serviceEventDetails"]
BATCH = 2000


def call(method: str, path: str, body=None, raw: bytes | None = None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(ES + path, data=data, method=method, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read()[:500]!r}")


def settings(kind: str) -> dict:
    s: dict = {"number_of_shards": 1, "number_of_replicas": 0}
    if kind == "C":
        s["index.mode"] = "logsdb"
    return s


def mappings(kind: str) -> dict:
    if kind == "A":
        return {}
    props = {f: {"type": "flattened"} for f in FLAT}
    if kind == "C":
        props["@timestamp"] = {"type": "date"}
    return {"properties": props}


def main(index: str, kind: str, src: str, out: str) -> None:
    call("DELETE", f"/{index}?ignore_unavailable=true")
    call("PUT", f"/{index}", {"settings": settings(kind), "mappings": mappings(kind)})
    sent = ok = bad = 0
    reasons: collections.Counter = collections.Counter()
    t0 = time.time()

    def flush(lines: list[bytes]) -> None:
        nonlocal ok, bad
        res = call("POST", f"/{index}/_bulk?refresh=false", raw=b"".join(lines), ctype="application/x-ndjson")
        for it in res["items"]:
            v = it["index"]
            if v["status"] < 300:
                ok += 1
            else:
                bad += 1
                reasons[(v["error"]["type"], v["error"]["reason"][:140])] += 1

    buf: list[bytes] = []
    with open(src, "rb") as fh:
        for line in fh:
            if kind == "C":
                d = json.loads(line)
                d["@timestamp"] = d["eventTime"]
                line = json.dumps(d, separators=(",", ":")).encode()
            buf += [b'{"index":{}}\n', line.rstrip(b"\n") + b"\n"]
            sent += 1
            if sent % BATCH == 0:
                flush(buf)
                buf = []
    if buf:
        flush(buf)
    call("POST", f"/{index}/_refresh")
    fields = call("GET", f"/{index}/_mapping")
    nfields = json.dumps(fields).count('"type"')
    res = {"index": index, "kind": kind, "sent": sent, "indexed": ok, "rejected": bad,
           "load_seconds": round(time.time() - t0, 1), "mapping_type_entries": nfields,
           "reject_reasons": [{"type": k[0], "reason": k[1], "n": n} for k, n in reasons.most_common(5)]}
    json.dump(res, open(out, "w"), indent=1)
    print(json.dumps(res))


if __name__ == "__main__":
    main(*sys.argv[1:5])
