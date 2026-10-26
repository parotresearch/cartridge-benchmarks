"""Rewrite a log with invalid UTF-8 replaced by U+FFFD per line (same as bulk_load.py: decode errors='replace'). usage: clean_utf8.py IN OUT"""
import json, sys
bad = badbytes = lines = 0
with open(sys.argv[1], "rb") as f, open(sys.argv[2], "wb") as o:
    for raw in f:
        lines += 1
        try: raw.decode("utf-8"); o.write(raw)
        except UnicodeDecodeError:
            fixed = raw.decode("utf-8", "replace").encode("utf-8"); bad += 1; badbytes += len(raw); o.write(fixed)
print(json.dumps({"lines": lines, "invalid_utf8_lines": bad, "invalid_lines_raw_bytes": badbytes}))
