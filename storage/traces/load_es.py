#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["elasticsearch==9.1.0", "typer"]
# ///
"""Bulk-load an NDJSON file (one document per line) into a data stream with the official client (pinned above). Lines go through verbatim;
the stock template for the data-stream name decides everything else. Prints one JSON line of stats; exits 1 on any rejected document."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path

import typer
from elasticsearch import Elasticsearch

CREATE = '{"create":{}}'


def main(path: Path, stream: str, out: Path, url: str = "http://127.0.0.1:9200", batch: int = 5000, workers: int = 8) -> None:
    es = Elasticsearch(url, request_timeout=600, retry_on_timeout=True, max_retries=5)
    st = {"lines": 0, "indexed": 0, "errors": 0, "err_samples": []}

    def send(lines: list[str]) -> None:
        ops = [x for line in lines for x in (CREATE, line)]
        res = es.bulk(operations=ops, index=stream)
        bad = [i["create"] for i in res["items"] if i["create"].get("status", 200) >= 300]
        st["indexed"] += len(lines) - len(bad)
        st["errors"] += len(bad)
        room = 5 - len(st["err_samples"])
        st["err_samples"] += [b.get("error") for b in bad[: max(room, 0)]]
        if st["indexed"] == 0 and bad:  # the mapping rejects documents from the first batch on: stop now, not after the whole file
            raise SystemExit(f"first batch rejected ({len(bad)}/{len(lines)} documents), samples {st['err_samples']}")

    t0 = time.time()
    with path.open(encoding="utf-8", newline="\n") as fh, ThreadPoolExecutor(workers) as ex:
        pending = []
        while chunk := [x.rstrip("\n") for x in islice(fh, batch)]:
            st["lines"] += len(chunk)
            pending.append(ex.submit(send, chunk))
            if len(pending) >= workers * 2:
                pending.pop(0).result()
            if st["lines"] % 5_000_000 < batch:
                print(f"{st['lines']} lines {time.time() - t0:.0f}s errors={st['errors']}", flush=True)
        for f in pending:
            f.result()
    st["wall_s"] = round(time.time() - t0, 1)
    out.write_text(json.dumps(st))
    print(json.dumps(st))
    if st["errors"] or st["indexed"] != st["lines"]:
        raise SystemExit(f"rejections: {st['errors']} errors, samples {st['err_samples']}")


if __name__ == "__main__":
    typer.run(main)
