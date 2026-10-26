# shellcheck shell=bash
# Download and verify. Source after common.sh.

# fetch_verify URL SHA256 OUT: download (skipped when OUT already has the right hash) and check the SHA-256.
fetch_verify() {
  local url=$1 sha=$2 out=$3
  if [[ ! -s $out ]] || [[ $(sha256sum "$out" | cut -d' ' -f1) != "$sha" ]]; then
    curl -fL --retry 5 --retry-delay 5 -sS -o "$out.part" "$url"
    mv "$out.part" "$out"
  fi
  echo "$sha  $out" | sha256sum -c - || die "$out does not match the expected SHA-256 $sha"
}

# expect_input FILE BYTES LINES: the prepared input must be exactly the file the stored numbers were measured on.
expect_input() {
  local f=$1 bytes=$2 lines=$3
  [[ $(stat -c %s "$f") == "$bytes" ]] || die "$f is $(stat -c %s "$f") bytes, expected $bytes"
  [[ $(wc -l < "$f") == "$lines" ]] || die "$f has $(wc -l < "$f") lines, expected $lines"
}
