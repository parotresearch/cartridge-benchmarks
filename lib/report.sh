# shellcheck shell=bash
# Results table. Source after common.sh.

RESULTS_TSV=${RESULTS_TSV:-$PWD/results.tsv}

report_init() { : > "$RESULTS_TSV"; }
report_row()  { printf '%s\t%s\n' "$1" "$2" >> "$RESULTS_TSV"; }   # report_row "system label" BYTES

# report_table RAW_BYTES: label, stored bytes, stored/raw, and how many times smaller than raw
report_table() {
  awk -F'\t' -v raw="$1" '
    BEGIN { printf "%-52s %16s %9s %9s\n", "system", "stored bytes", "x of raw", "smaller"; printf "%-52s %16d %9s %9s\n", "raw input", raw, "1.000", "1.0x" }
    { printf "%-52s %16d %9.3f %8.1fx\n", $1, $2, $2 / raw, raw / $2 }' "$RESULTS_TSV"
}
