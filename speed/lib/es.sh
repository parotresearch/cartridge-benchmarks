# shellcheck shell=bash
# Elasticsearch helpers. Source env.sh first. Everything here runs on the benchmark machine.
# Elasticsearch runs in Docker, single node, security off, HTTP bound to 127.0.0.1, trial licence
# (searchable snapshots need the features the trial switches on).
# S3 access uses the machine's instance role; the metadata service must be reachable from containers
# (instance metadata hop limit 2).

ES_URL=http://127.0.0.1:9200
ES_IMAGE=docker.elastic.co/elasticsearch/elasticsearch:$ES_VERSION
ES_ROLES=master,data_content,data_hot,data_warm,data_cold,data_frozen,ingest

d() { sudo docker "$@"; }

# es METHOD PATH [JSON]: print the body, fail on any non-2xx.
es() {
  local out code
  out=$(mktemp)
  code=$(curl -sS -m "${ES_TIMEOUT:-600}" -o "$out" -w '%{http_code}' -X "$1" "$ES_URL$2" \
    -H 'Content-Type: application/json' ${3:+--data-binary "$3"}) || { rm -f "$out"; die "curl failed: $1 $2"; }
  if [[ $code != 2* ]]; then
    local b; b=$(head -c 2000 "$out"); rm -f "$out"; die "$1 $2 -> HTTP $code: $b"
  fi
  cat "$out"; rm -f "$out"
}
es_count() { es GET "/$1/_count" | jq -er .count; }

es_docker_ready() {
  need docker "install Docker"; need jq "install jq"; need aws "install the AWS CLI v2"
  sudo sysctl -qw vm.max_map_count=262144
  sudo install -d -o 1000 -g 0 -m 775 "$ES_DATA"   # uid 1000 is the image's elasticsearch user
}

es_stop() { if d inspect "$ES_NAME" >/dev/null 2>&1; then d rm -f "$ES_NAME" >/dev/null; fi; }

# es_start ingest|measure [SHARED_CACHE]
#   ingest   24 GB, no CPU cap: loading, merging and snapshotting (not timed against Cartridge)
#   measure  --cpus 4 --memory 16g, heap left to Elasticsearch (it sizes it to half the container): every timed search
es_start() {
  local shape=$1 cache=${2:-1gb} limits _
  es_docker_ready; es_stop
  case $shape in
    ingest) limits=(--memory "$ES_INGEST_MEM" --memory-swap "$ES_INGEST_MEM") ;;
    measure) limits=(--cpus "$CAP_CPUS" --memory "$CAP_MEM" --memory-swap "$CAP_MEM") ;;
    *) die "es_start: ingest or measure, got '$shape'" ;;
  esac
  d run -d --name "$ES_NAME" "${limits[@]}" --ulimit nofile=65535:65535 \
    -p 127.0.0.1:9200:9200 -e discovery.type=single-node -v "$ES_DATA:/usr/share/elasticsearch/data" \
    -e node.name=elasticsearch -e xpack.security.enabled=false -e "node.roles=$ES_ROLES" \
    -e "xpack.searchable.snapshot.shared_cache.size=$cache" -e "s3.client.default.region=$AWS_REGION" \
    "$ES_IMAGE" >/dev/null
  for _ in $(seq 120); do
    if curl -fsS "$ES_URL/_cluster/health?wait_for_status=yellow&timeout=1s" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  d logs --tail 40 "$ES_NAME" >&2
  die "Elasticsearch did not come up within 240 s"
}

es_trial() {
  if [[ $(es GET /_license | jq -r .license.type) != trial ]]; then es POST '/_license/start_trial?acknowledge=true' >/dev/null; fi
  [[ $(es GET /_license | jq -r .license.type) == trial ]] || die "no trial licence"
}

# The Rally track names its indices logs-history-<week>. This empty template stops Elasticsearch's built-in
# logs-*-* template from applying to them, so the indices get only the track's own index.json.
es_template() { es PUT /_index_template/logs-history "$(cat "$HTTP_LOGS/es-index-template.json")" >/dev/null; }

# es_repo ro|rw: the S3 snapshot repository. Every measuring step registers it read-only.
es_repo() {
  local ro=true; [[ $1 == rw ]] && ro=false
  es PUT "/_snapshot/$ES_REPO" "{\"type\":\"s3\",\"settings\":{\"bucket\":\"$BUCKET\",\"base_path\":\"$ES_SNAPSHOT_PATH\",\"max_snapshot_bytes_per_sec\":\"1gb\",\"readonly\":$ro}}" >/dev/null
}

# es_wait_green PATTERN [SECONDS]
es_wait_green() {
  ES_TIMEOUT=$(( ${2:-600} + 100 )) es GET "/_cluster/health/$1?wait_for_status=green&timeout=${2:-600}s" \
    | jq -e '.status == "green"' >/dev/null || die "$1 is not green"
}

# Both systems answer every search with their answer caches off: request_cache=false on each search (run_searches.py),
# and the node query cache off on every index (a static index setting, set when the index is created from the snapshot).
ES_INDEX_SETTINGS='{"index.number_of_replicas":0,"index.queries.cache.enabled":false}'

es_weeks_csv() { printf 'logs-history-%s\n' "${WEEKS[@]}" | paste -sd, -; }

# Rally load of the corpus into one index per week (8 clients, 5,000-document bulks), then one segment per shard.
# Needs the parsed corpus in Rally's data dir (es_parsed_corpus) and esrally from uvx.
RALLY_DATA=$HOME/.rally/benchmarks/data/http_logs
es_parsed_corpus() {
  local w f
  need lbzip2 "apt install lbzip2"; mkdir -p "$RALLY_DATA"
  for w in "${WEEKS[@]}"; do
    f=$RALLY_DATA/documents-$w.json
    if [[ -s $f ]]; then continue; fi
    curl -fL --retry 5 --retry-delay 5 -sS -o "$f.bz2.part" "$RALLY_BASE/documents-$w.json.bz2"
    lbzip2 -dc "$f.bz2.part" > "$f.part"; mv "$f.part" "$f"; rm -f "$f.bz2.part"
  done
}
es_rally_load() {  # es_rally_load [extra --track-params, e.g. ,enable_logsdb:true]
  need uvx "install uv: https://docs.astral.sh/uv/"
  uvx --python 3.12 --from "esrally==$RALLY_VERSION" esrally race --track-path="$HTTP_LOGS/rally-track" \
    --challenge=append-no-conflicts-index-only --pipeline=benchmark-only --target-hosts=127.0.0.1:9200 \
    --client-options="use_ssl:false,timeout:240" --track-params="cluster_health:yellow${1:-}" --on-error=abort \
    --kill-running-processes
}
es_force_merge() {  # one segment per shard, one index at a time; prints "forcemerge index=… wall_s=…"
  local w t0 tid
  for w in "${WEEKS[@]}"; do
    t0=$SECONDS
    tid=$(es POST "/logs-history-$w/_forcemerge?max_num_segments=1&wait_for_completion=false" | jq -er .task)
    until [[ $(es GET "/_tasks/$tid" | jq -r .completed) == true ]]; do sleep 5; done
    echo "forcemerge index=logs-history-$w wall_s=$((SECONDS - t0))"
  done
  es GET "/_cat/segments/logs-history-*?format=json&h=index,shard" \
    | jq -e 'group_by([.index, .shard]) | map(length) | max == 1' >/dev/null || die "some shard still has more than one segment"
}
es_store_bytes() {  # primary store bytes of every index matching $1
  es GET "/_cat/indices/$1?bytes=b&format=json&h=pri.store.size" | jq 'map(."pri.store.size" | tonumber) | add'
}

# Snapshot of the merged indices to S3 (the one place a repository is registered read-write).
es_snapshot() {
  es_repo rw
  ES_TIMEOUT=7200 es PUT "/_snapshot/$ES_REPO/$ES_SNAPSHOT?wait_for_completion=true" '{"indices":"logs-history-*","include_global_state":false}' \
    | jq -e '.snapshot.state == "SUCCESS" and .snapshot.shards.failed == 0' >/dev/null || die "snapshot failed"
  es_repo ro
}

# ---- tiers -------------------------------------------------------------------------------------------------

# Hot: full local indices restored from the snapshot, one at a time, no replicas, then restart in the measure shape.
es_hot_restore() {
  local w
  es_start measure 1gb; es_trial; es_repo ro
  es PUT /_cluster/settings '{"persistent":{"indices.recovery.max_bytes_per_sec":"90mb"}}' >/dev/null
  for w in "${WEEKS[@]}"; do
    ES_TIMEOUT=3600 es POST "/_snapshot/$ES_REPO/$ES_SNAPSHOT/_restore?wait_for_completion=true" \
      "{\"indices\":\"logs-history-$w\",\"include_global_state\":false,\"index_settings\":$ES_INDEX_SETTINGS}" \
      | jq -e '.snapshot.shards.failed == 0' >/dev/null || die "restore of logs-history-$w failed"
  done
  es_wait_green 'logs-history-*' 3600
  [[ $(es_count 'logs-history-*') == "$DOCS" ]] || die "restored indices do not hold $DOCS documents"
  es_start measure 1gb; es_wait_green 'logs-history-*'
}

# Warm: a fresh full local copy for each chain. restore = a snapshot restore (searches start when it is done);
# fullcopy = a fully mounted searchable snapshot (searches start as soon as the shards are allocated, the copy continues).
# The recovery throttle is raised above the volume's speed so it is not the bottleneck.
es_warm_settings() {
  es PUT /_cluster/settings '{"persistent":{"indices.recovery.max_bytes_per_sec":"1gb","cluster.routing.allocation.node_concurrent_recoveries":2}}' >/dev/null
}
es_warm_clean() {
  local idx; idx=$(es GET '/_cat/indices/warm-history-*?format=json&h=index' | jq -r '.[].index' | paste -sd, -)
  if [[ -n $idx ]]; then es DELETE "/$idx" >/dev/null; fi
}
es_warm_open() {  # es_warm_open restore|fullcopy
  local w
  case $1 in
    restore)
      # shellcheck disable=SC2016  # $1 is Elasticsearch's rename back-reference
      ES_TIMEOUT=1800 es POST "/_snapshot/$ES_REPO/$ES_SNAPSHOT/_restore?wait_for_completion=true" \
        "{\"indices\":\"$(es_weeks_csv)\",\"include_global_state\":false,\"rename_pattern\":\"logs-history-(.+)\",\"rename_replacement\":\"warm-history-\$1\",\"index_settings\":$ES_INDEX_SETTINGS}" \
        | jq -e '.snapshot.shards.failed == 0' >/dev/null || die "warm restore failed"
      es_wait_green 'warm-history-*' ;;
    fullcopy)
      for w in "${WEEKS[@]}"; do
        es POST "/_snapshot/$ES_REPO/$ES_SNAPSHOT/_mount?wait_for_completion=false&storage=full_copy" \
          "{\"index\":\"logs-history-$w\",\"renamed_index\":\"warm-history-$w\",\"index_settings\":$ES_INDEX_SETTINGS}" >/dev/null
      done
      es_wait_green 'warm-history-*' 1800 ;;
    *) die "es_warm_open: restore or fullcopy" ;;
  esac
}
# The copy counts as local only when the bytes on disk and the reported store size both cover the snapshot's size.
es_warm_local_ok() {
  local snap du store
  snap=$(ES_TIMEOUT=900 es GET "/_snapshot/$ES_REPO/$ES_SNAPSHOT/_status" | jq '[.snapshots[0].indices[].stats.total.size_in_bytes] | add')
  du=$(sudo du -s --block-size=1 "$ES_DATA/indices" | cut -f1)
  store=$(es GET '/_cat/indices/warm-history-*?bytes=b&format=json&h=store.size' | jq 'map(."store.size" | tonumber) | add')
  (( du >= snap && store >= snap ))
}

# Cold: partially mounted searchable snapshots (frozen tier) with a shared cache of 1/20 of the mounted size,
# rounded down to whole 16 MiB regions.
es_cold_mount() {
  local w mounted target
  es_start measure 1gb; es_trial; es_repo ro
  es PUT /_cluster/settings '{"persistent":{"indices.recovery.max_bytes_per_sec":"90mb"}}' >/dev/null
  for w in "${WEEKS[@]}"; do
    ES_TIMEOUT=1800 es POST "/_snapshot/$ES_REPO/$ES_SNAPSHOT/_mount?wait_for_completion=true&storage=shared_cache" \
      "{\"index\":\"logs-history-$w\",\"renamed_index\":\"frozen1-history-$w\",\"index_settings\":$ES_INDEX_SETTINGS}" \
      | jq -e '.snapshot.shards.failed == 0' >/dev/null || die "mount of frozen1-history-$w failed"
  done
  es_wait_green 'frozen1-history-*'
  mounted=$(es GET '/_cat/indices/frozen1-history-*?bytes=b&format=json&h=dataset.size' | jq 'map(."dataset.size" | tonumber) | add')
  target=$(( mounted / 20 / 16777216 * 16777216 ))
  echo "$((target / 1048576))mb" > "$WORK/cold-cache-size"
  es_cold_restart
}
# A restart empties the shared cache: every cold chain starts from it.
es_cold_restart() { es_start measure "$(cat "$WORK/cold-cache-size")"; es_wait_green 'frozen1-history-*'; }
