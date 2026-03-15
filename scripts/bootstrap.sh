#!/usr/bin/env bash
# bootstrap.sh — one-shot initialisation for the log analytics pipeline.
# Run ONCE after `docker compose up -d` to apply templates and ILM policies.
set -euo pipefail

ES_HOST="${ES_HOST:-http://localhost:9200}"
RETRY_MAX=30
RETRY_WAIT=5

echo "==> Waiting for Elasticsearch to be available..."
for i in $(seq 1 $RETRY_MAX); do
  STATUS=$(curl -sf "$ES_HOST/_cluster/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['status'])" 2>/dev/null || echo "unreachable")
  if [[ "$STATUS" == "green" || "$STATUS" == "yellow" ]]; then
    echo "    Cluster status: $STATUS — proceeding."
    break
  fi
  echo "    Attempt $i/$RETRY_MAX: cluster not ready yet (status=$STATUS). Retrying in ${RETRY_WAIT}s..."
  sleep $RETRY_WAIT
done

echo "==> Applying ILM policy (hot → delete after 30 days)..."
curl -sf -XPUT "$ES_HOST/_ilm/policy/logs-ilm-policy" \
  -H "Content-Type: application/json" \
  -d '{
    "policy": {
      "phases": {
        "hot": {
          "min_age": "0ms",
          "actions": {
            "rollover": { "max_age": "1d", "max_size": "5gb" },
            "set_priority": { "priority": 100 }
          }
        },
        "warm": {
          "min_age": "7d",
          "actions": {
            "readonly": {},
            "set_priority": { "priority": 50 }
          }
        },
        "delete": {
          "min_age": "30d",
          "actions": { "delete": {} }
        }
      }
    }
  }'
echo ""
echo "    ILM policy applied."

echo "==> Applying index template (logs-*)..."
curl -sf -XPUT "$ES_HOST/_index_template/logs-template" \
  -H "Content-Type: application/json" \
  -d @"$(dirname "$0")/../elasticsearch/index-templates/logs-template.json"
echo ""
echo "    Index template applied."

echo "==> Verifying cluster nodes..."
curl -sf "$ES_HOST/_cat/nodes?v&h=name,heap.percent,ram.percent,cpu,role"

echo ""
echo "Bootstrap complete. Open Kibana at http://localhost:5601"
echo "  1. Stack Management → Index Patterns → Create pattern: logs-*"
echo "  2. Set time field: @timestamp"
echo "  3. Go to Discover and start exploring logs."
