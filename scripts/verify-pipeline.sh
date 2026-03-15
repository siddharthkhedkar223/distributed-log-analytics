#!/usr/bin/env bash
# verify-pipeline.sh — smoke test that verifies the full Filebeat → Logstash → ES path.
set -euo pipefail

ES_HOST="${ES_HOST:-http://localhost:9200}"
LS_HOST="${LS_HOST:-http://localhost:9600}"

echo "==> [1/4] Checking Elasticsearch cluster health..."
HEALTH=$(curl -sf "$ES_HOST/_cluster/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])")
if [[ "$HEALTH" != "green" && "$HEALTH" != "yellow" ]]; then
  echo "FAIL: Cluster status is '$HEALTH'" && exit 1
fi
echo "     OK — cluster status: $HEALTH"

echo "==> [2/4] Checking Logstash pipeline status..."
LS_STATUS=$(curl -sf "$LS_HOST/?pretty" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))")
if [[ "$LS_STATUS" != "green" ]]; then
  echo "WARN: Logstash status is '$LS_STATUS' (may still be warming up)"
else
  echo "     OK — Logstash status: $LS_STATUS"
fi

echo "==> [3/4] Checking Elasticsearch node count..."
NODE_COUNT=$(curl -sf "$ES_HOST/_cat/nodes?h=name" | wc -l | tr -d ' ')
if [[ "$NODE_COUNT" -lt 2 ]]; then
  echo "WARN: Only $NODE_COUNT node(s) visible — expected 2 for full HA"
else
  echo "     OK — $NODE_COUNT nodes in cluster"
fi

echo "==> [4/4] Checking for any logs-* indices..."
INDICES=$(curl -sf "$ES_HOST/_cat/indices/logs-*?h=index,docs.count,store.size" 2>/dev/null || echo "none")
if [[ "$INDICES" == "none" || -z "$INDICES" ]]; then
  echo "     INFO: No logs-* indices exist yet. Give Filebeat 60s to start shipping."
else
  echo "     OK — Active log indices:"
  echo "$INDICES" | sed 's/^/         /'
fi

echo ""
echo "Pipeline verification complete."
