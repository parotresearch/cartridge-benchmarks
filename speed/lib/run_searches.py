#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Run one chain of the 39 searches against Elasticsearch or Cartridge and judge every answer.

Each search is timed, capped, and its answer reduced to one canonical text per kind, so the two systems'
answers can be compared byte for byte:

  int        a single number
  lines      up to 100 matching lines (any 100). Every returned line must be present in the full match set
             (speed/http_logs/reference/*.gz). If the match set is larger than 100 the canonical text is the
             count plus one line stating that check passed.
  histdays   non-empty UTC day buckets   `YYYY-MM-DD<TAB>count`
  histhours  non-empty hour buckets in local time (-05:00)   `YYYY-MM-DDTHH:MM:SS-05:00<TAB>count`
  topn       exactly N rows `key<TAB>count`, count descending then key ascending; the answer is the sha256 of that text

An answer is compared with `want` from searches.json. A wrong answer exits non-zero. The first search that
exceeds the per-search cap ends the chain (a later search would only measure the wait). An Elasticsearch top-N
that differs at the default `shard_size` is reported `approx`; after the chain an untimed ladder doubles
`shard_size` until the answer is exact.

Output, one line per search (read by summarize.py):
  S <cfg> <chain> <system> step=<id> ms=<ms> verdict=<exact|approx|timeout> answer=<..> want=<..> out_sha=<..> out_lines=<n> cap_s=<s>
"""

import argparse
import collections
import gzip
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

LOCAL = timezone(timedelta(hours=-5))


def local_ts(epoch_s: float) -> str:
    return (
        datetime.fromtimestamp(epoch_s, LOCAL).strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"
    )


def utc_day(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, timezone.utc).strftime("%Y-%m-%d")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---- canonical forms ----------------------------------------------------------------------------------------


def lines_form(rows: list[str], search: dict, ref_dir: pathlib.Path, cap: int) -> str:
    full = gzip.open(ref_dir / (search["full_set"] + ".gz"), "rt").read().splitlines()
    extra = collections.Counter(rows) - collections.Counter(full)
    if extra:
        raise SystemExit(
            f"{search['id']}: returned line(s) not in the full match set: {list(extra)[:3]}"
        )
    want = min(search["want"], cap)
    if len(rows) != want:
        raise SystemExit(
            f"{search['id']}: returned {len(rows)} lines, expected exactly {want}"
        )
    body = sorted(rows)
    if search["want"] > cap:
        return f"{len(rows)}\nsample of {len(rows)} lines, each present in the full match set of {len(full)} lines\n"
    return "\n".join([str(len(rows)), *body]) + "\n"


def topn_form(pairs: list[tuple[str, int]], n: int) -> str:
    keys = [k for k, _ in pairs]
    if len(pairs) != n or len(set(keys)) != n:
        raise SystemExit(f"topn: expected exactly {n} distinct rows, got {len(pairs)}")
    return "".join(
        f"{k}\t{c}\n" for k, c in sorted(pairs, key=lambda p: (-p[1], p[0].encode()))
    )


def es_canon(search: dict, body: dict, cap: int, ref_dir: pathlib.Path) -> str:
    kind = search["kind"]
    if kind == "int":
        return f"{body['hits']['total']['value']}\n"
    if kind == "lines":
        rows = [
            f"{h['_source']['clientip']} - - [{local_ts(datetime.fromisoformat(h['_source']['@timestamp'].replace('Z', '+00:00')).timestamp())}] "
            f'"{h["_source"]["request"]}" {h["_source"]["status"]} {h["_source"]["size"]}'
            for h in body["hits"]["hits"]
        ]
        return lines_form(rows, search, ref_dir, cap)
    if kind in ("histhours", "histdays"):
        agg = body["aggregations"]["per_hour" if kind == "histhours" else "per_day"][
            "buckets"
        ]
        fmt = local_ts if kind == "histhours" else utc_day
        # histhours buckets are keyed in the -05:00 zone: the key is already the local midnight-aligned epoch
        rows = [
            f"{fmt(b['key'] / 1000)}\t{b['doc_count']}\n"
            for b in agg
            if b["doc_count"] > 0
        ]
        if not rows:
            raise SystemExit(f"{search['id']}: no non-empty bucket")
        return "".join(rows)
    if kind == "topn":
        return topn_form(
            [
                (str(b["key"]), b["doc_count"])
                for b in body["aggregations"]["top"]["buckets"]
            ],
            search["top"],
        )
    raise SystemExit(f"unknown kind {kind}")


def cart_canon(
    search: dict, argv: list[str], out: str, cap: int, ref_dir: pathlib.Path
) -> str:
    kind = search["kind"]
    if kind == "int":
        return out.strip() + "\n"
    if kind == "lines":
        prefix = re.compile(r"^([^ :]+\.cart:)?row/[0-9]+: ")
        raw = out.splitlines()
        if not all(prefix.match(r) for r in raw):
            raise SystemExit(f"{search['id']}: unexpected output row shape: {raw[:2]}")
        return lines_form([prefix.sub("", r) for r in raw], search, ref_dir, cap)
    if kind in ("histhours", "histdays"):
        objs = [json.loads(line) for line in out.splitlines() if line.strip()]
        if not objs:
            raise SystemExit(f"{search['id']}: no buckets")
        if all(set(o) == {"bucket", "count"} for o in objs):  # field sidecar shape
            pairs = [(int(o["bucket"]), o["count"]) for o in objs]
        elif all(
            o.get("exact") is True for o in objs
        ):  # text shape: every bucket, empty ones too
            pairs = [(o["from"], next(iter(o["counts"].values()))) for o in objs]
        else:
            raise SystemExit(f"{search['id']}: not exact buckets")
        fmt = local_ts if kind == "histhours" else utc_day
        return "".join(f"{fmt(f)}\t{n}\n" for f, n in pairs if n > 0)
    if kind == "topn":
        cols = argv[argv.index("--group-by") + 1].split(",")
        data = json.loads(out)
        if isinstance(data, dict) and data.get("approximate") is True:
            raise SystemExit(
                f"{search['id']}: Cartridge answered with an ESTIMATE; an estimate is never an answer"
            )
        if len(cols) == 1:
            pairs = [(k, v) for k, v in data.items()]
        else:
            pairs = [(" ".join(o[c] for c in cols), o["count"]) for o in data]
        return topn_form(pairs, search["top"])
    raise SystemExit(f"unknown kind {kind}")


def answer_of(kind: str, canon: str) -> str:
    if kind == "topn":
        return sha(canon)
    first = canon.splitlines()[0]
    if kind in ("histhours", "histdays"):
        return str(sum(int(line.split("\t")[1]) for line in canon.splitlines()))
    return first


# ---- running one search -------------------------------------------------------------------------------------


def run_es(args, search: dict, body: dict) -> tuple[int, dict | None]:
    t0 = time.perf_counter()
    r = subprocess.run(
        [
            "curl",
            "-sS",
            "-m",
            str(args.cap),
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            f"{args.es_url}/{args.index}/_search?request_cache=false",
            "--data-binary",
            json.dumps(body),
        ],
        capture_output=True,
        text=True,
    )
    ms = int((time.perf_counter() - t0) * 1000)
    if r.returncode == 28:
        return ms, None
    if r.returncode != 0:
        raise SystemExit(
            f"{search['id']}: curl failed ({r.returncode}): {r.stderr[:300]}"
        )
    out = json.loads(r.stdout)
    if "error" in out:
        raise SystemExit(
            f"{search['id']}: Elasticsearch error: {json.dumps(out['error'])[:300]}"
        )
    return ms, out


def run_cart(args, argv: list[str]) -> tuple[int, str | None]:
    # timed inside the container, so docker's own start-up is not counted
    script = 'a=$(date +%s%N); timeout -s KILL "$0" "$@"; rc=$?; b=$(date +%s%N); echo "$rc $(( (b-a)/1000000 ))" >&2'
    r = subprocess.run(
        [
            "sudo",
            "docker",
            "exec",
            args.container,
            "sh",
            "-c",
            script,
            str(args.cap),
            "/opt/bin/cartridge",
            *argv,
        ],
        capture_output=True,
        text=True,
    )
    rc, ms = r.stderr.strip().splitlines()[-1].split()
    if int(rc) == 137:
        return int(ms), None
    if int(rc) != 0:
        raise SystemExit(f"cartridge exited {rc}: {r.stderr[:300]}")
    return int(ms), r.stdout


def cart_argv(args, search: dict) -> list[str]:
    raw = (
        search["cart_facets"]
        if args.facets and search.get("cart_facets")
        else search["cart"]
    )
    return [
        a.replace("{TARGET}", args.target).replace("{LINE_CAP}", str(args.line_cap))
        for a in raw
    ]


def ladder(args, search: dict, want: str) -> None:
    n = search["top"]
    size = (n * 3 // 2 + 10) * 2
    while True:
        body = json.loads(json.dumps(search["es"]))
        body["aggs"]["top"]["terms"]["shard_size"] = size
        _, out = run_es(args, search, body)
        exact = (
            out is not None
            and sha(es_canon(search, out, args.line_cap, args.reference)) == want
        )
        print(
            f"S {args.cfg} {args.chain} es step={search['id']} topn_rung shard_size={size} verdict={'exact' if exact else 'approx'}",
            flush=True,
        )
        if exact or size >= 10000:
            return
        size = min(size * 2, 10000)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--system", choices=["es", "cart"], required=True)
    p.add_argument("--chain", required=True)
    p.add_argument("--cfg", default="A")
    p.add_argument(
        "--searches",
        type=pathlib.Path,
        default=pathlib.Path(__file__).parents[1] / "http_logs/searches.json",
    )
    p.add_argument(
        "--reference",
        type=pathlib.Path,
        default=pathlib.Path(__file__).parents[1] / "http_logs/reference",
    )
    p.add_argument("--cap", type=int, default=60, help="per-search cap, seconds")
    p.add_argument("--es-url", default="http://127.0.0.1:9200")
    p.add_argument("--index", default="logs-history-*", help="ES index pattern")
    p.add_argument("--container", default="cart")
    p.add_argument(
        "--target", help="Cartridge target: a path inside the container or an s3:// URL"
    )
    p.add_argument(
        "--facets",
        action="store_true",
        help="use the field-sidecar form of a search where one exists",
    )
    p.add_argument(
        "--t0-ns",
        type=int,
        help="epoch ns of the tier's clock start; also prints a WARM line",
    )
    p.add_argument(
        "--warm-extra", default="", help="extra key=value pairs for the WARM line"
    )
    args = p.parse_args()
    doc = json.loads(args.searches.read_text())
    args.line_cap = doc["line_cap"]
    chain = next(c for c in doc["chains"] if c["id"] == args.chain)
    label = "es" if args.system == "es" else "cart-exact"
    first_ms = done_ms = None
    approx: list[tuple[dict, str]] = []
    for s in chain["searches"]:
        if args.system == "es":
            ms, out = run_es(args, s, s["es"])
            canon = (
                None if out is None else es_canon(s, out, args.line_cap, args.reference)
            )
        else:
            argv = cart_argv(args, s)
            ms, out = run_cart(args, argv)
            canon = (
                None
                if out is None
                else cart_canon(s, argv, out, args.line_cap, args.reference)
            )
        want = str(s["want"])
        if canon is None:
            print(
                f"S {args.cfg} {args.chain} {label} step={s['id']} ms={ms} verdict=timeout answer=none want={want} cap_s={args.cap}",
                flush=True,
            )
            break
        ans = answer_of(s["kind"], canon)
        if ans == want:
            verdict = "exact"
        elif s["kind"] == "topn" and args.system == "es":
            verdict = "approx"
            approx.append((s, want))
        else:
            print(
                f"S {args.cfg} {args.chain} {label} step={s['id']} ms={ms} verdict=wrong answer={ans} want={want}",
                flush=True,
            )
            return 1
        now = time.time_ns()
        first_ms = (
            first_ms
            if first_ms is not None
            else (now - args.t0_ns) // 1_000_000
            if args.t0_ns
            else None
        )
        done_ms = (now - args.t0_ns) // 1_000_000 if args.t0_ns else None
        print(
            f"S {args.cfg} {args.chain} {label} step={s['id']} ms={ms} verdict={verdict} answer={ans} want={want} "
            f"out_sha={sha(canon)} out_lines={len(canon.splitlines())} cap_s={args.cap}",
            flush=True,
        )
    if args.t0_ns:
        print(
            f"WARM {args.cfg} {args.chain} {label} t_first_answer_ms={first_ms} t_chain_done_ms={done_ms} {args.warm_extra}".rstrip(),
            flush=True,
        )
    for (
        s,
        want,
    ) in approx:  # untimed: how far shard_size has to go for Elasticsearch to be exact
        ladder(args, s, want)
    return 0


if __name__ == "__main__":
    sys.exit(main())
