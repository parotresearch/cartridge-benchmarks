#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Run the 39 searches once on a local cart and compare each answer with reference-answers.json (made by reference.py).

    uv run verify_cart.py CART --answers reference-answers.json --sets-dir SETS_DIR [--cap 10]

CART is a local .cart; if CART.facets sits next to it, the searches that have a field-sidecar form run in that form
too (and in the text form), so both are checked. Each search runs once with a hard cap. A case that fails stays a
line in the output: the sweep runs to the end, then the exit status says whether every case matched.

One line per case:
  VERIFY <id> form=<text|field> verdict=<match|mismatch|timeout|not computable> ms=<ms> answer=<..> reference=<..> sha_match=<0|1>
"""

import argparse
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import run_searches as rs  # noqa: E402


def run(argv: list[str], cap: int) -> tuple[int, str | None]:
    t0 = time.perf_counter()
    r = subprocess.run(
        ["timeout", "-s", "KILL", str(cap), "cartridge", *argv],
        capture_output=True,
        text=True,
    )
    ms = int((time.perf_counter() - t0) * 1000)
    if r.returncode == 137:
        return ms, None
    if r.returncode != 0:
        raise SystemExit(f"cartridge exited {r.returncode}: {r.stderr[:300]}")
    return ms, r.stdout


def judge(
    search: dict, ref: dict, argv: list[str], out: str, sets_dir: pathlib.Path
) -> tuple[str, str, bool]:
    canon = rs.cart_canon(search, argv, out, 100, sets_dir)
    ans = rs.answer_of(search["kind"], canon)
    return ans, str(ref["answer"]), rs.sha(canon) == ref["canonical_sha256"]


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("cart", type=pathlib.Path)
    p.add_argument("--answers", type=pathlib.Path, required=True)
    p.add_argument("--sets-dir", type=pathlib.Path, required=True)
    p.add_argument("--searches", type=pathlib.Path, default=HERE / "searches.json")
    p.add_argument("--cap", type=int, default=10, help="per-search cap, seconds")
    args = p.parse_args()
    doc = json.loads(args.searches.read_text())
    answers = json.loads(args.answers.read_text())["searches"]
    sidecar = pathlib.Path(str(args.cart) + ".facets").exists()
    counts = {"match": 0, "mismatch": 0, "timeout": 0, "not computable": 0}
    for s in (s for c in doc["chains"] for s in c["searches"]):
        ref = answers[s["id"]]
        forms = [("text", s["cart"])] + (
            [("field", s["cart_facets"])] if sidecar and s.get("cart_facets") else []
        )
        for form, raw in forms:
            argv = [
                a.replace("{TARGET}", str(args.cart)).replace(
                    "{LINE_CAP}", str(doc["line_cap"])
                )
                for a in raw
            ]
            if ref["status"] != "computed":
                verdict, ms, ans, want, sha_ok = (
                    "not computable",
                    0,
                    "-",
                    ref["reason"],
                    False,
                )
            else:
                ms, out = run(argv, args.cap)
                if out is None:
                    verdict, ans, want, sha_ok = "timeout", "none", ref["answer"], False
                else:
                    try:  # case boundary: a malformed answer is this case's verdict, the sweep goes on
                        ans, want, sha_ok = judge(s, ref, argv, out, args.sets_dir)
                        verdict = "match" if ans == want and sha_ok else "mismatch"
                    except SystemExit as e:
                        verdict, ans, want, sha_ok = (
                            "mismatch",
                            f"error: {e}",
                            ref["answer"],
                            False,
                        )
            counts[verdict] += 1
            print(
                f"VERIFY {s['id']} form={form} verdict={verdict} ms={ms} answer={ans} reference={want} sha_match={int(sha_ok)}",
                flush=True,
            )
    print(f"SUMMARY {json.dumps(counts)}")
    return 0 if counts["match"] and not (counts["mismatch"] or counts["timeout"]) else 1


if __name__ == "__main__":
    sys.exit(main())
