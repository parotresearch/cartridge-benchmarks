#!/usr/bin/env python3
"""index D = stock data stream `logs-cloudtrail-default`, Elastic's built-in logs templates, NO custom mapping/settings.
Only change to the documents: eventTime is copied into @timestamp (data streams require it).
Records indexed vs rejected, effective settings, mapped field count, `_ignored` counts, store size after force-merge.
usage: 06-es-datastream-load.py <events.ndjson> <out.json>"""
import collections, json, sys, time, urllib.request, urllib.error

ES = "http://127.0.0.1:9200"
DS = "logs-cloudtrail-default"
BATCH = 2000


def call(method, path, body=None, raw=None, ctype="application/json", allow=()):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(ES + path, data=data, method=method, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in allow:
            return {}
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read()[:500]!r}")


def main(src, out):
    call("DELETE", f"/_data_stream/{DS}", allow=(404,))
    sent = ok = bad = 0
    reasons = collections.Counter()
    t0 = time.time()

    def flush(buf):
        nonlocal ok, bad
        res = call("POST", f"/{DS}/_bulk?refresh=false", raw=b"".join(buf), ctype="application/x-ndjson")
        for it in res["items"]:
            v = it["create"]
            if v["status"] < 300:
                ok += 1
            else:
                bad += 1
                reasons[(v["error"]["type"], v["error"]["reason"][:140])] += 1

    buf = []
    for line in open(src, "rb"):
        d = json.loads(line)
        d["@timestamp"] = d["eventTime"]
        buf += [b'{"create":{}}\n', json.dumps(d, separators=(",", ":")).encode() + b"\n"]
        sent += 1
        if sent % BATCH == 0:
            flush(buf); buf = []
    if buf:
        flush(buf)
    call("POST", f"/{DS}/_refresh")
    call("POST", f"/{DS}/_forcemerge?max_num_segments=1")
    call("POST", f"/{DS}/_refresh")
    st = call("GET", f"/{DS}/_settings?include_defaults=true&flat_settings=true")
    flat = next(iter(st.values()))
    eff = {**flat.get("defaults", {}), **flat.get("settings", {})}
    keys = ["index.mode", "index.mapping.total_fields.limit", "index.mapping.total_fields.ignore_dynamic_beyond_limit",
            "index.mapping.ignore_malformed", "index.mapping.dynamic"]
    settings = {k: eff.get(k) for k in keys}
    mapping = json.dumps(call("GET", f"/{DS}/_mapping"))
    ign_docs = call("POST", f"/{DS}/_count", {"query": {"exists": {"field": "_ignored"}}})["count"]
    agg = call("POST", f"/{DS}/_search?size=0", {"aggs": {"ig": {"terms": {"field": "_ignored", "size": 40}}}})["aggregations"]["ig"]["buckets"]
    size = call("GET", f"/_cat/indices/.ds-{DS}-*?bytes=b&format=json&h=index,docs.count,pri.store.size")
    res = {"index": DS, "sent": sent, "indexed": ok, "rejected": bad, "load_seconds": round(time.time() - t0, 1),
           "mapped_type_entries": mapping.count('"type"'), "docs_with_ignored": ign_docs,
           "ignored_top": [{"field": b["key"], "docs": b["doc_count"]} for b in agg],
           "effective_settings": settings, "store": size,
           "reject_reasons": [{"type": k[0], "reason": k[1], "n": n} for k, n in reasons.most_common(5)]}
    json.dump(res, open(out, "w"), indent=1)
    print(json.dumps(res))


if __name__ == "__main__":
    main(*sys.argv[1:3])
