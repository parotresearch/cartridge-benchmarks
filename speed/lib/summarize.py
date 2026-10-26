#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Print the speed claims table from the search logs written by 20-speed.sh (or the stored ones in results/speed).

    uv run speed/lib/summarize.py results/speed/http_logs/speed

Reads the `S ...` search lines and the `WARM ...` lines. It never measures anything.
"""

import re
import sys
from pathlib import Path

STEP = re.compile(
    r"^S (?P<cfg>\w+) (?P<chain>\w+) (?P<sys>es|cart-exact) step=(?P<id>[a-z0-9]+) ms=(?P<ms>\w+) verdict=(?P<verdict>\w+) .*?out_sha=(?P<sha>\w+)"
)
WARM = re.compile(
    r"^WARM \w+ (?P<chain>\w+) (?P<sys>[\w-]+) .*?t_first_answer_ms=(?P<first>\w+)"
)


def steps(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text().splitlines():
        m = STEP.match(line)
        if m:
            out[m["id"]] = {
                "ms": None if m["ms"] in ("none", "na") else int(m["ms"]),
                "verdict": m["verdict"],
                "sha": m["sha"],
                "chain": m["chain"],
            }
    return out


def first_answers(path: Path) -> list[float]:
    return [
        int(m["first"]) / 1000
        for m in map(WARM.match, path.read_text().splitlines())
        if m and m["first"].isdigit()
    ]


def total(s: dict[str, dict], ids=None) -> float:
    return sum(v["ms"] for k, v in s.items() if ids is None or k in ids) / 1000


def exact(s: dict[str, dict]) -> int:
    return sum(v["verdict"] in ("exact", "exact_tie") for v in s.values())


def answered(s: dict[str, dict]) -> set[str]:
    return {k for k, v in s.items() if v["verdict"] in ("exact", "exact_tie", "approx")}


def main(d: Path) -> None:
    f = lambda n: steps(d / n)  # noqa: E731
    hot_es, hot_c, hot_c0 = (
        f("hot-es.log"),
        f("hot-cart-field-index.log"),
        f("hot-cart-no-field-index.log"),
    )
    warm_er, warm_c = f("warm-es-restore.log"), f("warm-cart-field-index.log")
    cold_es, cold_c = f("cold-es-frozen.log"), f("cold-cart.log")
    cold_ids = answered(cold_es) & {
        k for k, v in cold_c.items() if v["verdict"] == "exact"
    }
    fa_es = first_answers(d / "warm-es-fullcopy.log") + first_answers(
        d / "warm-es-restore.log"
    )
    fa_c = first_answers(d / "warm-cart-field-index.log")
    rows = [
        (
            "Hot: all 39, local disk",
            f"{total(hot_c):.1f} s, {exact(hot_c)} exact",
            f"{total(hot_es):.1f} s, {exact(hot_es)} exact",
        ),
        (
            "Warm: first answer",
            f"{min(fa_c):.0f} to {max(fa_c):.0f} s",
            f"{min(fa_es):.0f} to {max(fa_es):.0f} s",
        ),
        (
            "Warm: all 39 once local",
            f"{total(warm_c):.1f} s",
            f"{total(warm_er):.1f} s",
        ),
        (
            f"Cold: {len(cold_ids)} searches both answer",
            f"{total(cold_c, cold_ids):.0f} s",
            f"{total(cold_es, cold_ids):.0f} s",
        ),
        (
            "Hot, Cartridge without the field index",
            f"{total(hot_c0):.1f} s, {exact(hot_c0)} exact",
            "",
        ),
    ]
    print("| Test | Cartridge | Elasticsearch |\n| --- | ---: | ---: |")
    for r in rows:
        print("| " + " | ".join(r) + " |")
    inexact = sorted(k for k, v in hot_es.items() if v["verdict"] == "approx")
    print(f"\nElasticsearch searches not exact at its defaults: {', '.join(inexact)}")
    print(
        f"Cartridge cold searches with no answer (timeout): {', '.join(sorted(k for k, v in cold_c.items() if v['verdict'] == 'timeout'))}"
    )
    both = [
        k
        for k in hot_es
        if k in hot_c
        and hot_es[k]["verdict"] == "exact"
        and hot_es[k]["sha"] != hot_c[k]["sha"]
    ]
    print(
        f"Searches where both systems were exact but their canonical answers differ: {both or 'none'}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
