#!/usr/bin/env bash
# Step 0: download the 1998 World Cup web logs and check them.
#
#   bash speed/http_logs/00-data.sh
#
# Downloads the 7 weekly files from Elastic's public Rally track store, extracts the raw log line of
# each record into $WORK/raw/access-<week>.log, then checks:
#   * the size of every download against the size the track publishes,
#   * the total raw size (23,475,280,341 bytes) and line count (247,249,096),
#   * the number of lines with status 403, 404 and 500 (224, 1,224,876, 6,134), counted straight from the text.
# It prints a SHA-256 for every download so you can pin them; the files are public and unversioned.
# Needs: curl, lbzip2, jq, rg (ripgrep).
set -euo pipefail
BUCKET=${BUCKET:-unused}   # this step never touches S3
# shellcheck source=../lib/env.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/env.sh"
need curl "install curl"; need lbzip2 "apt install lbzip2"; need jq "apt install jq"; need rg "apt install ripgrep"

mkdir -p "$RAW"; cd "$RAW"

file_bytes() { stat -c %s "$1" 2>/dev/null || stat -f %z "$1"; }

# bytes of each download, as published in the track (rally-track/track.json)
published_bytes() {
  grep -A2 -F "documents-$1.unparsed.json.bz2" "$HTTP_LOGS/rally-track/track.json" \
    | sed -n 's/.*"compressed-bytes": *\([0-9]*\).*/\1/p' | head -1
}

fetch_week() {
  local w=$1 f=documents-$1.unparsed.json.bz2 got want
  [[ -s access-$w.log ]] && return 0
  curl -fL --retry 5 --retry-delay 5 -sS -o "$f.part" "$RALLY_BASE/$f"
  got=$(file_bytes "$f.part"); want=$(published_bytes "$w")
  [[ $got == "$want" ]] || die "$f is $got bytes, the track publishes $want"
  echo "sha256 $(sha256sum "$f.part" | cut -d' ' -f1)  $f"
  lbzip2 -dc "$f.part" | jq -r .message > "access-$w.log.part"
  mv "access-$w.log.part" "access-$w.log"; rm -f "$f.part"
}
export -f fetch_week published_bytes file_bytes die; export RALLY_BASE HTTP_LOGS
printf '%s\n' "${WEEKS[@]}" | xargs -P 4 -I{} bash -c 'set -euo pipefail; fetch_week {}'

bytes=0; lines=0
for w in "${WEEKS[@]}"; do
  bytes=$(( bytes + $(file_bytes "access-$w.log") ))
  lines=$(( lines + $(wc -l < "access-$w.log") ))
done
[[ $bytes == "$RAW_BYTES" ]] || die "raw logs total $bytes bytes, expected $RAW_BYTES"
[[ $lines == "$DOCS" ]] || die "raw logs hold $lines lines, expected $DOCS"

count() { rg -c -- "$1" access-*.log | awk -F: '{t += $NF} END {print t + 0}'; }
for pair in "403 224" "404 1224876" "500 6134"; do
  read -r code want <<<"$pair"
  got=$(count "\" $code ")
  [[ $got == "$want" ]] || die "lines with status $code: $got, expected $want"
done
log "data ok: $lines lines, $bytes bytes, status counts 403/404/500 verified"
