# shellcheck shell=bash
# OpenSearch 3.9.0 with every storage setting at its default (no codec, no derived or synthetic source, no index sorting).
# Source after common.sh and es.sh. One fresh node per dataset, 1 shard, 0 replicas.

OS_NAME=opensearch
OS_DATA=${OS_DATA:-$PWD/os-data}
OS_MEM=24g
OS_HEAP=12g   # the heap Elasticsearch auto-sizes inside a 24 GB container; OpenSearch has no auto-sizing (image default 1 GB), so it is set explicitly to match

os_stop() { if d inspect "$OS_NAME" >/dev/null 2>&1; then d rm -f "$OS_NAME" >/dev/null; fi; }

os_up() {
  es_stop; os_stop
  sudo rm -rf -- "${OS_DATA:?}"
  sudo install -d -o 1000 -g 0 -m 775 "$OS_DATA"   # uid 1000 = the image's opensearch user
  sudo sysctl -qw vm.max_map_count=262144
  # single node, HTTP on 127.0.0.1 only; security plugin and demo config off; performance analyzer off
  d run -d --name "$OS_NAME" --memory "$OS_MEM" --memory-swap "$OS_MEM" --ulimit nofile=65535:65535 \
    -p 127.0.0.1:9200:9200 -v "$OS_DATA:/usr/share/opensearch/data" \
    -e discovery.type=single-node -e DISABLE_SECURITY_PLUGIN=true -e DISABLE_INSTALL_DEMO_CONFIG=true \
    -e DISABLE_PERFORMANCE_ANALYZER_AGENT_CLI=true -e "OPENSEARCH_JAVA_OPTS=-Xms$OS_HEAP -Xmx$OS_HEAP" \
    "$OS_IMAGE" >/dev/null
  local _
  for _ in $(seq 120); do curl -fsS "$ES_URL/_cluster/health?wait_for_status=yellow&timeout=1s" >/dev/null 2>&1 && break; sleep 2; done
  curl -fsS "$ES_URL/_cluster/health?wait_for_status=yellow&timeout=1s" >/dev/null 2>&1 || { d logs --tail 40 "$OS_NAME" >&2; die "OpenSearch did not come up within 240 s"; }
  [[ $(es GET / | jq -r .version.number) == "$OS_VERSION" ]] || die "node reports a version other than $OS_VERSION"
}

# os_settled_store INDEX: pri.store.size once two consecutive reads, 10 s apart, agree (stale pre-merge files are deleted asynchronously; cap 120 s)
os_settled_store() {
  local prev cur t=$SECONDS
  prev=$(es_store_bytes "$1")
  while :; do
    sleep 10; cur=$(es_store_bytes "$1")
    [[ $cur != "$prev" ]] || { echo "$cur"; return 0; }
    (( SECONDS - t < 120 )) || die "pri.store.size of $1 still changing after 120 s ($prev -> $cur)"
    prev=$cur
  done
}

# os_measure INDEX EXPECTED_DOCS: force-merge to one segment, refresh, flush, wait for the store size to settle, print the bytes.
os_measure() {
  local idx=$1 docs=$2 segs store segments_bytes
  es POST "/$idx/_forcemerge?max_num_segments=1" >/dev/null
  es POST "/$idx/_refresh" >/dev/null   # a search-idle shard skips scheduled refreshes; without this _cat/segments lists the pre-merge segments
  segs=$(es GET "/_cat/segments/$idx?format=json&h=index,shard" | jq 'group_by([.index, .shard]) | map(length) | max // 0')
  (( segs == 1 )) || die "$idx has $segs segments after the force-merge"
  [[ $(es_count "$idx") == "$docs" ]] || die "$idx count changed across the force-merge"
  es POST "/$idx/_flush?force=true" >/dev/null
  store=$(os_settled_store "$idx")
  segments_bytes=$(es GET "/_cat/segments/$idx?format=json&bytes=b&h=size" | jq -er 'map(.size | tonumber) | add')   # live segment data only
  awk -v a="$store" -v b="$segments_bytes" 'BEGIN{exit !(a <= 1.10 * b)}' || die "$idx store_bytes=$store exceeds 1.10 x segments_bytes=$segments_bytes after flush and settle"
  echo "$store"
}
