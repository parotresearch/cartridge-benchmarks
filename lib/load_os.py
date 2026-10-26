#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["opensearch-py==3.0.0", "typer"]
# ///
"""Bulk-load one dataset into an OpenSearch index (Elasticsearch's python client refuses OpenSearch). One loader for the four OpenSearch passes of
storage/*/run.sh; --mode picks the per-line document, batch/workers mirror the Elasticsearch loader of the same dataset:
  tb      Thunderbird.log line "<label> <epoch> ..." -> {"@timestamp": iso(epoch), "message": line}   (storage/thunderbird/bulk_load.py: batch 20000, 8 workers)
  cr      CockroachDB NDJSON, "@timestamp" (epoch ms from "timestamp":"sec.nanos") spliced in front   (storage/cockroachdb/load.py: batch 4000, 4 workers)
  raw     the NDJSON line verbatim                                                                    (cloudtrail: batch 2000, 1 worker; traces: batch 5000, 8 workers)
The file is cut at line boundaries into --workers byte ranges, one process per range (the GIL would cap a thread pool well below ES's rate).
A worker stops the run when its first batch is 100% rejected. Rejected documents are counted and sampled, never retried; the exit code is 1 on any
rejection unless --allow-rejections (CloudTrail: the rejected count IS part of the measurement). Prints one JSON stats line and writes it to OUT."""
import collections
import json
import re
import time
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

import typer
from opensearchpy import OpenSearch
from opensearchpy.exceptions import TransportError

TS_RE = re.compile(rb'"timestamp":"(\d+)\.(\d+)"')


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ranges(path: Path, workers: int) -> list[tuple[int, int]]:
    n = path.stat().st_size
    cuts = [0]
    with path.open("rb") as f:
        for i in range(1, workers):
            f.seek(n * i // workers)
            f.readline()
            cuts.append(f.tell())
    return list(zip(cuts, cuts[1:] + [n]))


def make_doc(mode: str, raw: bytes, state: dict) -> bytes:
    line = raw.rstrip(b"\n")
    if mode == "raw":
        return line
    if mode == "cr":
        m = TS_RE.search(line)
        if not m:
            state["ts_fail"] += 1
            return line
        return b'{"@timestamp":' + m.group(1) + m.group(2)[:3].ljust(3, b"0") + b"," + line[1:]
    text = line.decode("utf-8", "replace")
    parts = text.split(" ", 2)
    try:
        e = int(parts[1])
    except (IndexError, ValueError):
        state["ts_fail"] += 1
        e = state["prev"] if state["prev"] is not None else 0
    state["prev"] = e
    if e != state["ce"]:
        state["ce"], state["cs"] = e, iso(e)
    return ('{"@timestamp":"' + state["cs"] + '","message":' + json.dumps(text, ensure_ascii=False) + "}").encode("utf-8")


def work(args: tuple) -> dict:
    path, lo, hi, url, index, mode, batch, limit = args
    client = OpenSearch(url, timeout=600, max_retries=5, retry_on_timeout=True)
    st = {"lines": 0, "indexed": 0, "errors": 0, "ts_fail": 0, "retries": 0, "reasons": collections.Counter(), "err_samples": []}
    state = {"prev": None, "ce": None, "cs": None, "ts_fail": 0}
    buf: list[bytes] = []

    def send() -> None:
        body = b"".join(buf)
        for attempt in range(8):
            try:
                res = client.bulk(body=body, index=index)
                break
            except TransportError as e:
                if e.status_code != 429:
                    raise
                st["retries"] += 1
                time.sleep(2 * (attempt + 1))
        else:
            raise SystemExit("bulk still HTTP 429 after 8 attempts")
        n = len(buf) // 2
        bad = [i["index"] for i in res["items"] if i["index"].get("status", 200) >= 300]
        st["indexed"] += n - len(bad)
        st["errors"] += len(bad)
        for b in bad:
            err = b.get("error") or {}
            st["reasons"][(err.get("type"), str(err.get("reason"))[:140])] += 1
            if len(st["err_samples"]) < 5:
                st["err_samples"].append(err)
        if st["indexed"] == 0 and bad:  # the mapping rejects everything from the first batch on: stop now, not after the whole file
            raise SystemExit(f"first batch rejected ({len(bad)}/{n} documents), samples {st['err_samples']}")
        buf.clear()

    with open(path, "rb") as f:
        f.seek(lo)
        while f.tell() < hi and (not limit or st["lines"] < limit):
            raw = f.readline()
            if not raw:
                break
            buf += [b'{"index":{}}\n', make_doc(mode, raw, state) + b"\n"]
            st["lines"] += 1
            if len(buf) >= 2 * batch:
                send()
        if buf:
            send()
    st["ts_fail"] = state["ts_fail"]
    st["reasons"] = [{"type": k[0], "reason": k[1], "n": n} for k, n in st["reasons"].most_common(5)]
    return st


def main(path: Path, index: str, out: Path, mode: str = typer.Option(..., help="tb | cr | raw"), batch: int = 5000, workers: int = 8,
         url: str = "http://127.0.0.1:9200", limit: int = 0, allow_rejections: bool = False) -> None:
    if mode not in {"tb", "cr", "raw"}:
        raise SystemExit(f"--mode must be tb, cr or raw, got {mode}")
    if limit and workers != 1:
        raise SystemExit("--limit (probe) needs --workers 1")
    t0 = time.time()
    with Pool(workers) as p:
        parts = p.map(work, [(str(path), lo, hi, url, index, mode, batch, limit) for lo, hi in ranges(path, workers)], chunksize=1)
    agg = collections.Counter()
    reasons: collections.Counter = collections.Counter()
    for s in parts:
        agg.update({k: s[k] for k in ("lines", "indexed", "errors", "ts_fail", "retries")})
        reasons.update({(r["type"], r["reason"]): r["n"] for r in s["reasons"]})
    st = {**agg, "mode": mode, "batch": batch, "workers": workers, "wall_s": round(time.time() - t0, 1),
          "reject_reasons": [{"type": k[0], "reason": k[1], "n": n} for k, n in reasons.most_common(5)],
          "err_samples": [e for s in parts for e in s["err_samples"]][:5]}
    out.write_text(json.dumps(st))
    print(json.dumps(st))
    if st["indexed"] + st["errors"] != st["lines"]:
        raise SystemExit(f"indexed {st['indexed']} + rejected {st['errors']} != lines {st['lines']}")
    if st["errors"] and not allow_rejections:
        raise SystemExit(f"rejections: {st['errors']} errors, samples {st['err_samples']}")


if __name__ == "__main__":
    typer.run(main)
