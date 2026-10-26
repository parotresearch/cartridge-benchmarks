#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["typer", "orjson"]
# ///
"""Alibaba cluster-trace-microservices-v2022 CallGraph CSV (stdin) -> OpenTelemetry span NDJSON (stdout), one line per CSV row, in the
document layout Elasticsearch's stock traces-otel@template maps (data streams traces-*.otel-*; that template is dynamic:false, so any field
outside its layout would sit in _source unsearchable).

Source columns: timestamp,traceid,service,rpc_id,rpctype,um,uminstanceid,interface,dm,dminstanceid,rt
Every output field is a direct copy or a pure function of one source column; nothing is invented, nothing is dropped:
  trace_id=traceid  span_id=rpc_id  parent_span_id=rpc_id minus its last dotted component (absent for a comma-joined rpc_id)
  name=interface  resource.attributes: service.name=um, service.instance.id=uminstanceid
  @timestamp=span start=timestamp_ms (an offset in ms from the trace epoch, NOT wall-clock: read as offset from 1970-01-01; ms is the source precision)
  duration=rt_ms*1e6 ns (rt is the call's response time in ms; rt=None -> no duration)
  attributes: alibaba.service_id=service, rpc.system=rpctype, peer.service=dm, peer.service.instance.id=dminstanceid
The source has no span kind and no status/error column, so neither is emitted. A remote call is recorded twice in the source (once per side,
same rpc_id); both rows are kept as two spans. A few rows carry an unquoted comma inside rpc_id (12 fields): the two pieces are re-joined.
"""
import sys
from datetime import datetime, timezone

import orjson
import typer

COLS = "timestamp,traceid,service,rpc_id,rpctype,um,uminstanceid,interface,dm,dminstanceid,rt".split(",")


def convert(f: list[str]) -> dict:
    ts_ms, trace, svc, rpc_id, rpctype, um, uminst, iface, dm, dminst, rt = f
    doc = {
        "@timestamp": datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "trace_id": trace,
        "span_id": rpc_id,
        "name": iface,
        "resource": {"attributes": {"service.name": um, "service.instance.id": uminst}},
        "attributes": {"alibaba.service_id": svc, "rpc.system": rpctype, "peer.service": dm, "peer.service.instance.id": dminst},
    }
    # the source writes rt=None when no response time was recorded: that span carries no duration (none invented)
    if rt != "None":
        doc["duration"] = round(float(rt) * 1_000_000)
    if "," not in rpc_id and "." in rpc_id:
        doc["parent_span_id"] = rpc_id.rsplit(".", 1)[0]
    return doc


def main() -> None:
    out = sys.stdout.buffer
    header = sys.stdin.readline().rstrip("\n").split(",")
    if header != COLS:
        raise SystemExit(f"unexpected CSV header {header}, expected {COLS}")
    n = 0
    for line in sys.stdin:
        f = line.rstrip("\n").split(",")
        if len(f) == 12:
            f[3:5] = [f[3] + "," + f[4]]
        if len(f) != 11:
            raise SystemExit(f"row {n + 2}: {len(f)} fields, expected 11 or 12: {line[:200]!r}")
        out.write(orjson.dumps(convert(f)) + b"\n")
        n += 1


if __name__ == "__main__":
    typer.run(main)
