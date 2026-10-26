#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Expected answers for the 39 searches, computed straight from the raw log text. No Cartridge, no Elasticsearch.

    uv run reference.py RAW_DIR [--out reference-answers.json] [--sets-dir DIR] [--workers N]

RAW_DIR holds the seven files access-<week>.log written by 00-data.sh (one raw log line per record). One streaming
pass per file, files in parallel (standard library only). For every search in searches.json it takes the pattern,
time window and grouping from the search's Cartridge command, computes the answer from the lines, and writes it in
the form run_searches.py compares:

  int       the count
  hist*     the sum of the non-empty buckets (UTC days; hours aligned to the hour), plus the canonical text's sha256
  lines     the number of matching lines (any 100 of them are returned, so also the canonical text's sha256);
            the full match set is written to SETS_DIR/<full_set>.gz, and compared with the copy in reference/
  topn      sha256 of the canonical `key<TAB>count` text (count descending, key ascending)

Matching follows the command: a pattern is a literal piece of the raw line, `--since/--until` bound the timestamp.
Everything the patterns used by the 39 searches can mean is spelled out below (`classify`). A search whose command
uses a pattern or option this script does not understand is reported as "not computable" with the reason; it never
gets a guessed value.
"""

import argparse
import collections
import concurrent.futures
import gzip
import hashlib
import json
import pathlib
import re
import sys
import time
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import run_searches as rs  # noqa: E402  canonical forms shared with the runner

WEEKS = ["181998", "191998", "201998", "211998", "221998", "231998", "241998"]
IP_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
STATUS_RE = re.compile(r'^" (\d{3}) $')
REQ_RE = re.compile(r'^"([^"]+)"(?: (\d{3}) ?)?$')
HOUR = 3600


# ---- classify a Cartridge command into a match spec ---------------------------------------------------------


def to_epoch(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())


def classify(argv: list[str]) -> dict:
    """{ip, status, req, vti, since, until, bucket, group, top, error} from the command's tokens."""
    spec = {
        "ip": None,
        "status": None,
        "req": None,
        "vti": False,
        "since": None,
        "until": None,
        "bucket": None,
        "group": None,
        "top": None,
        "error": None,
    }
    pats: list[str] = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ("--since", "--until"):
            spec[a[2:]] = to_epoch(argv[i + 1])
            i += 2
        elif a in ("--bucket", "--group-by", "--top", "--budget", "-m"):
            if a == "--bucket":
                spec["bucket"] = argv[i + 1]
            elif a == "--group-by":
                spec["group"] = argv[i + 1]
            elif a == "--top":
                spec["top"] = int(argv[i + 1])
            i += 2
        elif a in ("-F", "-L", "--by-time", "--ndjson", "--json", "{TARGET}"):
            i += 1
        elif a.startswith("-"):
            spec["error"] = f"unsupported option {a}"
            return spec
        else:
            pats.append(a)
            i += 1
    for p in pats:
        if m := STATUS_RE.match(p):
            spec["status"] = int(m[1])
        elif IP_RE.match(p):
            spec["ip"] = p
        elif p == "_vti_bin":
            spec["vti"] = True
        elif m := REQ_RE.match(p):
            spec["req"] = m[1]
            if m[2]:
                spec["status"] = int(m[2])
        else:
            spec["error"] = (
                f"pattern {p!r} is not one of: status ' NNN ', client IP, _vti_bin, quoted request [status]"
            )
            return spec
    return spec


# ---- one pass over one file ---------------------------------------------------------------------------------

_HOURS: dict[str, int] = {}


def hour_of(ts: str) -> int:
    local = ts[:13]
    h = _HOURS.get(local)
    if h is None:
        if not ts.endswith("-05:00"):
            raise SystemExit(
                f"timestamp {ts!r} is not UTC-5: the hour table assumes one fixed offset"
            )
        h = _HOURS[local] = to_epoch(local + ":00:00-05:00")
    return h


def scan(path: str, targets: dict) -> dict:
    ips, reqs, win = targets["ips"], targets["reqs"], targets["windows"]
    hs = collections.Counter()  # (hour, status)
    ip_h = collections.Counter()  # (ip literal, hour)
    ip_eq = (
        collections.Counter()
    )  # (ip, hour): field equality, for comparison with Elasticsearch's term query
    ip_stat = collections.Counter()  # (ip literal, status)
    ip_req = collections.Counter()  # (ip literal, request)
    r_hs = collections.Counter()  # (request, hour, status)
    v_h, v_stat, v_ip = (
        collections.Counter(),
        collections.Counter(),
        collections.Counter(),
    )
    top_ip, top_req = (
        collections.Counter(),
        collections.Counter(),
    )  # (status, ip) / (status, request)
    kept: list[tuple] = []  # candidate lines for the `lines` searches
    n = 0
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        for line in f:
            line = line.rstrip("\n")
            n += 1
            ip = line[: line.index(" ")]
            a = line.index("[") + 1
            h = hour_of(line[a : line.index("]")])
            q = line.index('"')
            r = line.rindex('"')
            req = line[q + 1 : r]
            status = int(line[r + 2 : r + 5])
            hs[h, status] += 1
            if status in (500, 403):
                top_ip[status, ip] += 1
                top_req[status, req] += 1
            keep = False
            for t in ips:
                if t in line:
                    ip_h[t, h] += 1
                    ip_stat[t, status] += 1
                    ip_req[t, req] += 1
                    keep = True
                    if ip == t:
                        ip_eq[t, h] += 1
            if req in reqs:
                r_hs[req, h, status] += 1
            if "_vti_bin" in line:
                v_h[h] += 1
                v_stat[status] += 1
                v_ip[ip] += 1
                keep = True
            if not keep and status in win:
                keep = any(s <= h < e for s, e in win[status])
            if keep:
                kept.append((h, ip, req, status, line))
    return {
        "n": n,
        "hs": hs,
        "ip_h": ip_h,
        "ip_eq": ip_eq,
        "ip_stat": ip_stat,
        "ip_req": ip_req,
        "r_hs": r_hs,
        "v_h": v_h,
        "v_stat": v_stat,
        "v_ip": v_ip,
        "top_ip": top_ip,
        "top_req": top_req,
        "kept": kept,
    }


def merge(parts: list[dict]) -> dict:
    out: dict = {
        "n": sum(p["n"] for p in parts),
        "kept": [x for p in parts for x in p["kept"]],
    }
    for k in parts[0]:
        if k not in ("n", "kept"):
            out[k] = sum((p[k] for p in parts), collections.Counter())
    return out


# ---- answers ------------------------------------------------------------------------------------------------


def in_window(h: int, spec: dict) -> bool:
    return (spec["since"] is None or h >= spec["since"]) and (
        spec["until"] is None or h < spec["until"] + 1
    )


def hour_counts(agg: dict, spec: dict) -> dict[int, int]:
    """Matching-line count per hour for specs the aggregates cover directly."""
    c = collections.Counter()
    if spec["req"] is not None:
        for (r, h, st), v in agg["r_hs"].items():
            if (
                r == spec["req"]
                and (spec["status"] is None or st == spec["status"])
                and spec["ip"] is None
                and not spec["vti"]
            ):
                c[h] += v
        return c
    if spec["ip"] is not None and spec["status"] is None and not spec["vti"]:
        for (t, h), v in agg["ip_h"].items():
            if t == spec["ip"]:
                c[h] += v
        return c
    if spec["vti"] and spec["ip"] is None and spec["status"] is None:
        return collections.Counter(agg["v_h"])
    if spec["status"] is not None and spec["ip"] is None and not spec["vti"]:
        for (h, st), v in agg["hs"].items():
            if st == spec["status"]:
                c[h] += v
        return c
    raise KeyError("combination of patterns not aggregated")


def matches(rec: tuple, spec: dict) -> bool:
    _, ip, req, status, line = rec
    return (
        (spec["ip"] is None or spec["ip"] in line)
        and (spec["status"] is None or status == spec["status"])
        and (spec["req"] is None or req == spec["req"])
        and (not spec["vti"] or "_vti_bin" in line)
    )


def topn_pairs(agg: dict, spec: dict) -> list[tuple[str, int]]:
    g = spec["group"]
    if (
        spec["status"] is not None
        and spec["ip"] is None
        and not spec["vti"]
        and spec["req"] is None
    ):
        src = (
            agg["top_ip"]
            if g == "ip"
            else agg["top_req"]
            if g == "method,path,proto"
            else None
        )
        if src is None:
            raise KeyError("group column")
        return [(k, v) for (st, k), v in src.items() if st == spec["status"] and v > 0]
    if (
        spec["ip"] is not None
        and spec["status"] is None
        and spec["req"] is None
        and not spec["vti"]
    ):
        if g == "status":
            return [
                (str(st), v) for (t, st), v in agg["ip_stat"].items() if t == spec["ip"]
            ]
        if g == "method,path,proto":
            return [(k, v) for (t, k), v in agg["ip_req"].items() if t == spec["ip"]]
    if (
        spec["vti"]
        and spec["ip"] is None
        and spec["status"] is None
        and spec["req"] is None
    ):
        if g == "status":
            return [(str(k), v) for k, v in agg["v_stat"].items()]
        if g == "ip":
            return list(agg["v_ip"].items())
    raise KeyError("pattern/group combination not aggregated")


def answer(search: dict, agg: dict, sets_dir: pathlib.Path | None) -> dict:
    spec = classify(search["cart"])
    if spec["error"]:
        return {"status": "not computable", "reason": spec["error"]}
    kind = search["kind"]
    base = {"status": "computed", "kind": kind}
    if kind == "int":
        c = hour_counts(agg, spec)
        total = sum(v for h, v in c.items() if in_window(h, spec))
        extra = {}
        if (
            spec["ip"]
            and spec["status"] is None
            and spec["req"] is None
            and not spec["vti"]
        ):  # Elasticsearch matches the clientip field exactly
            extra["clientip_field_equality_answer"] = str(
                sum(
                    v
                    for (t, h), v in agg["ip_eq"].items()
                    if t == spec["ip"] and in_window(h, spec)
                )
            )
        return (
            base
            | extra
            | {"answer": str(total), "canonical_sha256": rs.sha(f"{total}\n")}
        )
    if kind in ("histdays", "histhours"):
        c = hour_counts(agg, spec)
        day = kind == "histdays"
        buckets: dict[int, int] = collections.Counter()
        for h, v in c.items():
            if in_window(h, spec):
                buckets[h // 86400 * 86400 if day else h] += v
        fmt = rs.utc_day if day else rs.local_ts
        text = "".join(
            f"{fmt(k)}\t{buckets[k]}\n" for k in sorted(buckets) if buckets[k] > 0
        )
        return base | {
            "answer": str(sum(buckets.values())),
            "canonical_sha256": rs.sha(text),
            "buckets": len([k for k in buckets if buckets[k] > 0]),
        }
    if kind == "lines":
        rows = sorted(
            r[4] for r in agg["kept"] if in_window(r[0], spec) and matches(r, spec)
        )
        full = len(rows)
        cap = 100
        text = (
            f"{min(full, cap)}\nsample of {min(full, cap)} lines, each present in the full match set of {full} lines\n"
            if full > cap
            else "\n".join([str(full), *rows]) + "\n"
        )
        out = base | {
            "answer": str(min(full, cap)),
            "total_matches": full,
            "canonical_sha256": rs.sha(text),
        }
        if sets_dir is not None:
            data = ("\n".join(rows) + "\n").encode()
            (sets_dir / (search["full_set"] + ".gz")).write_bytes(
                gzip.compress(data, mtime=0)
            )
            committed = HERE / "reference" / (search["full_set"] + ".gz")
            out["full_set_sha256"] = hashlib.sha256(data).hexdigest()
            if committed.exists():
                out["full_set_equals_committed_reference"] = (
                    gzip.open(committed).read() == data
                )
        return out
    if kind == "topn":
        pairs = topn_pairs(agg, spec)
        n = spec["top"]
        if spec["group"] == "method,path,proto":
            bad = [
                k
                for k, _ in sorted(pairs, key=lambda p: (-p[1], p[0]))[:n]
                if len(k.split(" ")) != 3
            ]
            if bad:
                return {
                    "status": "not computable",
                    "reason": f"a top-{n} request does not split into method, path, protocol: {bad[0]!r}",
                }
        if len(pairs) < n:
            return {
                "status": "not computable",
                "reason": f"only {len(pairs)} groups exist, the search asks for the top {n}",
            }
        ordered = sorted(pairs, key=lambda p: (-p[1], p[0].encode()))
        text = rs.topn_form(ordered[:n], n)
        return base | {
            "answer": rs.sha(text),
            "canonical_sha256": rs.sha(text),
            "boundary_tie": len(ordered) > n and ordered[n - 1][1] == ordered[n][1],
            "rows": text.splitlines(),
        }
    return {"status": "not computable", "reason": f"unknown kind {kind}"}


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("raw_dir", type=pathlib.Path)
    p.add_argument("--searches", type=pathlib.Path, default=HERE / "searches.json")
    p.add_argument("--out", type=pathlib.Path, default=HERE / "reference-answers.json")
    p.add_argument(
        "--sets-dir",
        type=pathlib.Path,
        help="write each lines search's full match set here (gzipped)",
    )
    p.add_argument("--workers", type=int, default=7)
    args = p.parse_args()
    doc = json.loads(args.searches.read_text())
    searches = [s for c in doc["chains"] for s in c["searches"]]
    files = [args.raw_dir / f"access-{w}.log" for w in WEEKS]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        raise SystemExit(f"missing raw files: {missing}")
    specs = {s["id"]: classify(s["cart"]) for s in searches}
    ips = sorted({sp["ip"] for sp in specs.values() if sp["ip"]})
    reqs = sorted({sp["req"] for sp in specs.values() if sp["req"]})
    win: dict[int, list[tuple[int, int]]] = collections.defaultdict(list)
    for s in searches:
        sp = specs[s["id"]]
        if (
            s["kind"] == "lines"
            and sp["status"] is not None
            and sp["since"] is not None
        ):
            win[sp["status"]].append((sp["since"], sp["until"] + 1))
    targets = {"ips": ips, "reqs": set(reqs), "windows": dict(win)}
    if args.sets_dir:
        args.sets_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with concurrent.futures.ProcessPoolExecutor(args.workers) as ex:
        agg = merge(list(ex.map(scan, map(str, files), [targets] * len(files))))
    scan_s = round(time.time() - t0, 1)
    results = {s["id"]: answer(s, agg, args.sets_dir) for s in searches}
    for s in (
        searches
    ):  # compare with the expected answers searches.json carries, and say so
        r = results[s["id"]]
        if r["status"] == "computed":
            want = (
                str(s["want"])
                if s["kind"] != "lines"
                else str(min(s["want"], doc["line_cap"]))
            )
            r["searches_json_want"] = want
            r["agrees_with_searches_json"] = (
                r["answer"] == want
                if s["kind"] != "lines"
                else r["total_matches"] == s["want"]
            )
    out = {
        "lines": agg["n"],
        "scan_seconds": scan_s,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "searches": results,
    }
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    bad = [k for k, v in results.items() if v["status"] != "computed"]
    off = [k for k, v in results.items() if v.get("agrees_with_searches_json") is False]
    print(
        f"{agg['n']} lines in {scan_s}s; computed {len(results) - len(bad)} of {len(results)}; not computable: {bad}; differ from searches.json: {off}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
