# shellcheck shell=bash
# Elasticsearch helpers. Source after common.sh. Runs a single node in Docker, security off, free (basic) licence, HTTP on 127.0.0.1 only.

ES_NAME=es
ES_DATA=${ES_DATA:-$PWD/es-data}
ES_INGEST_MEM=24g

d() { sudo docker "$@"; }

es() {  # es METHOD PATH [JSON-BODY]: prints the response body; any non-2xx status is fatal
  local out code
  out=$(mktemp)
  code=$(curl -sS -m "${ES_TIMEOUT:-7200}" -o "$out" -w '%{http_code}' -X "$1" "$ES_URL$2" -H 'Content-Type: application/json' ${3:+--data-binary "$3"}) \
    || { rm -f "$out"; die "curl failed: $1 $2"; }
  [[ $code == 2* ]] || { local b; b=$(head -c 2000 "$out"); rm -f "$out"; die "$1 $2 -> HTTP $code: $b"; }
  cat "$out"; rm -f "$out"
}

es_stop() { if d inspect "$ES_NAME" >/dev/null 2>&1; then d rm -f "$ES_NAME" >/dev/null; fi; }

es_wait() {  # wait until the node answers with cluster status yellow or better
  local _
  for _ in $(seq 120); do
    curl -fsS "$ES_URL/_cluster/health?wait_for_status=yellow&timeout=1s" >/dev/null 2>&1 && return 0
    sleep 2
  done
  d logs --tail 40 "$ES_NAME" >&2
  die "Elasticsearch did not come up within 240 s"
}

es_check_node() {
  [[ $(es GET / | jq -r .version.number) == "$ES_VERSION" ]] || die "node reports a version other than $ES_VERSION"
  # A fresh node can report yellow health before its licence is installed; /_license is 404 until then.
  local _ lic=
  for _ in $(seq 60); do
    lic=$(curl -fsS "$ES_URL/_license" 2>/dev/null | jq -r '.license.type // empty') && [[ -n $lic ]] && break
    sleep 1
  done
  [[ -n $lic ]] || die "GET /_license returned no licence within 60 s"
  [[ $lic == basic ]] || die "expected the free basic licence, node reports '$lic'"
}

# es_up: a fresh node. 24 GB container (the JVM heap is auto-sized to half of it), all CPUs, one node, security off, empty data directory.
es_up() {
  es_stop
  sudo rm -rf -- "${ES_DATA:?}"
  sudo install -d -o 1000 -g 0 -m 775 "$ES_DATA"   # uid 1000 = the image's elasticsearch user
  sudo sysctl -qw vm.max_map_count=262144
  d run -d --name "$ES_NAME" --memory "$ES_INGEST_MEM" --memory-swap "$ES_INGEST_MEM" --ulimit nofile=65535:65535 \
    -p 127.0.0.1:9200:9200 -e discovery.type=single-node -v "$ES_DATA:/usr/share/elasticsearch/data" \
    -e node.name=elasticsearch -e xpack.security.enabled=false \
    "$ES_IMAGE" >/dev/null
  es_wait
  es_check_node
}

# es_up_8g_heap: the node used for the CloudTrail indices: host networking, 8 GB heap, GeoIP downloader and disk watermarks off.
es_up_8g_heap() {
  es_stop
  sudo rm -rf -- "${ES_DATA:?}"
  sudo install -d -o 1000 -g 0 -m 775 "$ES_DATA"
  sudo sysctl -qw vm.max_map_count=262144
  d run -d --name "$ES_NAME" --network host \
    -e discovery.type=single-node -e xpack.security.enabled=false \
    -e ingest.geoip.downloader.enabled=false -e ES_JAVA_OPTS="-Xms8g -Xmx8g" \
    -e cluster.routing.allocation.disk.threshold_enabled=false \
    -v "$ES_DATA:/usr/share/elasticsearch/data" \
    "$ES_IMAGE" >/dev/null
  es_wait
  es_check_node
}

es_refresh()    { es POST "/$1/_refresh" >/dev/null; }
es_forcemerge() { es POST "/$1/_forcemerge?max_num_segments=1" >/dev/null; }
es_count()      { es GET "/$1/_count" | jq -er .count; }

# es_store_bytes PATTERN: primary store bytes summed over every index the pattern matches
es_store_bytes() { es GET "/_cat/indices/$1?bytes=b&format=json&h=pri.store.size" | jq -er 'map(."pri.store.size" | tonumber) | add'; }
