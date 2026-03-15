# Distributed Log Analytics Pipeline

> **A production-inspired observability system** that aggregates, transforms, and visualises structured logs from multiple microservices using a containerised ELK stack — built to reduce Mean Time to Recovery (MTTR) through centralised, searchable, real-time log management.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Why This Architecture?](#why-this-architecture)
- [How This Differs from a Kubernetes-Based EFK Setup](#how-this-differs-from-a-kubernetes-based-efk-setup)
- [Stack Components](#stack-components)
- [Data Flow](#data-flow)
- [Project Structure](#project-structure)
- [Quickstart](#quickstart)
- [Configuration Reference](#configuration-reference)
  - [Logstash Pipeline](#logstash-pipeline-logstashpipelinelogstashconf)
  - [Filebeat Autodiscovery](#filebeat-autodiscovery-filebeatfilebeatyml)
- [Resource Governance](#resource-governance)
- [Index Strategy](#index-strategy)
- [Observability Dashboards](#observability-dashboards)
- [Operational Runbook](#operational-runbook)
- [Roadmap](#roadmap)

---

## Overview

Modern distributed systems generate logs across dozens of independent services. When an incident occurs, engineers must correlate events from multiple sources under time pressure — every second of downtime has a business cost. This project builds a **centralised log aggregation pipeline** that completely decouples log *generation* from log *processing*, enabling real-time full-text search, structured field queries (KQL), and dashboard-driven observability across an entire service mesh.

Three simulated microservices (`auth-service`, `order-service`, `inventory-service`) each emit structured JSON logs to `stdout`. From there, the pipeline takes full ownership:

```
Filebeat  →  Logstash  →  Elasticsearch (2-node cluster)  →  Kibana
(collect)    (transform)   (index + replicate)               (visualize)
```

**What makes this production-relevant:**
- Two-node Elasticsearch cluster with replica shards — single-node failure does not lose data
- All containers have explicit memory and CPU limits — prevents OOM cascades on shared hosts
- Logstash dead-letter queue — no log events are silently dropped on parse failure
- Per-service, time-based index routing — supports ILM rollover and targeted queries without full-scan overhead
- Filebeat write-position registry — guarantees at-least-once delivery across restarts

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          DOCKER HOST                                 │
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐    │
│  │ auth-service │   │order-service │   │  inventory-service   │    │
│  │  (Python)    │   │  (Python)    │   │      (Python)        │    │
│  │  stdout →    │   │  stdout →    │   │  stdout →            │    │
│  │  JSON logs   │   │  JSON logs   │   │  JSON logs           │    │
│  └──────┬───────┘   └──────┬───────┘   └──────────┬───────────┘    │
│         │                  │                       │                 │
│         └──────────────────┴───────────────────────┘                │
│                            │                                         │
│          /var/lib/docker/containers/*.log  (Docker log driver)       │
│                            │                                         │
│              ┌─────────────▼───────────────┐                        │
│              │           FILEBEAT           │  128 MB / 0.25 CPU    │
│              │  Docker autodiscovery        │  ← tails container    │
│              │  Adds: container_id,         │    logs, adds meta    │
│              │  service.name, host.name     │    ships via Beats    │
│              └─────────────┬───────────────┘    protocol            │
│                            │  port 5044 (Lumberjack)                │
│              ┌─────────────▼───────────────┐                        │
│              │           LOGSTASH           │  512 MB / 0.75 CPU    │
│              │  ① JSON parse               │  ← transformation     │
│              │  ② grok fallback            │    & enrichment        │
│              │  ③ timestamp normalise      │    layer               │
│              │  ④ severity tagging         │                        │
│              │  ⑤ index routing            │                        │
│              └────────┬────────────────────┘                        │
│                       │ HTTP bulk                                    │
│           ┌───────────┴────────┬───────────────┐                    │
│           │                    │               │                     │
│  ┌────────▼────────┐  ┌────────▼────────┐     │                    │
│  │ ELASTICSEARCH   │  │ ELASTICSEARCH   │     │  2-node cluster    │
│  │    Node 01      │◄─►│    Node 02      │     │  replica shards    │
│  │  (master+data)  │  │  (master+data)  │     │  split-brain safe  │
│  │   1 GB / 1 CPU  │  │   1 GB / 1 CPU  │     │                    │
│  └────────┬────────┘  └─────────────────┘     │                    │
│           │                                    │                    │
│  ┌────────▼────────────────────────────────┐   │                    │
│  │                KIBANA                   │  768 MB / 0.5 CPU    │
│  │  Discover · Dashboards · Alerting UI    │                        │
│  │  http://localhost:5601                  │                        │
│  └─────────────────────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Why This Architecture?

### The Root Problem: Coupled Logs Are Operationally Dangerous

In a naive setup, services write logs to local files or each own a separate logging stack. This creates three failure modes that directly hurt MTTR:

| Problem | Impact |
|---|---|
| Logs live inside ephemeral containers | On crash/restart, the evidence of **why** it crashed is gone |
| No cross-service correlation | A downstream failure caused by an upstream timeout requires manually opening two log files and mentally joining events |
| Synchronous, disk-bound logging inside the app | Adds latency to every request path; causes I/O contention under load |

### The Fix: Strict Separation of Concerns

Each component in this pipeline has exactly one job:

| Layer | Component | Responsibility |
|---|---|---|
| **Emit** | Application Services | Write structured JSON to `stdout` only — zero knowledge of log infrastructure |
| **Collect** | Filebeat | Tail Docker log files asynchronously; add container/host metadata; forward via Beats protocol |
| **Transform** | Logstash | Parse, normalise, enrich, tag, route — completely independent of application code |
| **Store** | Elasticsearch Cluster | Distributed indexing, sharding, replication, and full-text search at scale |
| **Visualise** | Kibana | Dashboards, KQL search, threshold-based alerting |

**Why Filebeat instead of writing directly from the app to Logstash?**
The application should never be coupled to the observability infrastructure. If Logstash goes down for a rolling update, Filebeat buffers events in its on-disk registry and replays from the last confirmed offset on reconnect. The application never blocks or errors on log delivery.

**Why Logstash instead of direct Filebeat → Elasticsearch?**
Logstash gives us a programmable transformation layer. Grok parsing, field renaming, severity tagging, dead-letter-queue routing, and conditional index selection happen here — none of it touches the application. This also means log format changes (e.g., switching from plaintext to JSON) require only a Logstash config update, not a deployment of every service.

**Why Two Elasticsearch Nodes?**
A single-node Elasticsearch instance cannot hold replica shards — any hardware failure means complete data loss. With two nodes:
- Primary shard on node 01, replica shard on node 02 (and vice versa)
- Cluster continues serving queries if one node goes down
- Write throughput is shared between nodes

---

## How This Differs from a Kubernetes-Based EFK Setup

Both setups use the EFK/ELK family of tools, but the design goals are fundamentally different:

| Dimension | Kubernetes EFK (e.g., DaemonSet-based) | This Project |
|---|---|---|
| **Deployment target** | Kubernetes cluster (cloud or on-prem) | Docker Compose (any Linux/Mac/Windows host) |
| **Log collection method** | Fluentd DaemonSet on every K8s node | Filebeat with Docker socket autodiscovery |
| **Scope of log routing** | Per-namespace, cluster-wide, RBAC-gated | Per-service-name, per-date index routing |
| **Transformation layer** | Fluentd filter plugins (Ruby DSL) | Logstash pipeline (grok, mutate, date filters) |
| **HA mechanism** | K8s node redundancy + pod rescheduling | 2-node Elasticsearch cluster with replica shards |
| **Resource governance** | K8s resource requests/limits in pod specs | Docker Compose `deploy.resources` limits |
| **Data persistence** | PersistentVolumeClaims (cloud storage) | Named Docker volumes (host-local) |
| **Focus** | Kubernetes-native RBAC, namespace isolation | Pipeline correctness, transformation depth, resource governance |

Neither is superior — they solve different operational contexts. The Docker Compose approach is intentionally simpler to reason about, iterate on, and demonstrate end-to-end pipeline behaviour without a live Kubernetes cluster.

---

## Stack Components

| Component | Version | Role |
|---|---|---|
| Elasticsearch | 8.13.4 | Distributed full-text search and analytics engine |
| Logstash | 8.13.4 | Log transformation pipeline (input → filter → output) |
| Kibana | 8.13.4 | Visualisation, dashboards, and threshold alerting |
| Filebeat | 8.13.4 | Lightweight log shipper with Docker autodiscovery |

All four use the **same version** because the Elastic stack components have strict version-compatibility requirements — mixing versions causes silent API breakage.

---

## Data Flow

```
1. [Microservice stdout]
      Python app emits structured JSON: {"level":"ERROR","service":"auth-service","message":"...","latency_ms":5000}

2. [Docker log driver]
      Writes to /var/lib/docker/containers/<container-id>/<container-id>-json.log

3. [Filebeat]
      Autodiscovers containers bearing label co.elastic.logs/enabled=true
      Adds: container.id, service.name, host.name
      Ships to Logstash:5044 via Lumberjack protocol

4. [Logstash filter chain]
      ① JSON parse  → extract all fields
      ② grok        → fallback for plaintext logs
      ③ date        → normalise @timestamp from payload
      ④ mutate      → uppercase log_level; drop noisy ECS fields
      ⑤ if ERROR/FATAL → add_tag["error_event"]; add_field["alert.severity"="high"]
      ⑥ mutate      → add environment=development, pipeline=filebeat-logstash-es

5. [Elasticsearch output]
      Index: logs-auth-service-2025.06.14
             logs-order-service-2025.06.14
             logs-inventory-service-2025.06.14
      (2 primary shards, 1 replica shard per index)

6. [Kibana]
      Index pattern: logs-*  (time field: @timestamp)
      Discover: KQL query   log_level:"ERROR" AND service_name:"order-service"
      Dashboard: error rate timeseries per service
      Alert:     if count(log_level:ERROR) > 10 in 5m → notify
```

---

## Project Structure

```
distributed-log-analytics/
│
├── docker-compose.yml                     # Full stack: ES×2, Logstash, Kibana, Filebeat, 3 services
│
├── logstash/
│   ├── config/logstash.yml                # Pipeline workers, batch size, DLQ config
│   └── pipeline/logstash.conf             # Input → filter → output pipeline definition
│
├── filebeat/
│   └── filebeat.yml                       # Docker autodiscovery, Logstash output, backpressure
│
├── elasticsearch/
│   └── index-templates/
│       └── logs-template.json             # Field mappings + ILM policy attachment
│
├── kibana/
│   └── dashboards/
│       └── log-analytics-dashboard.ndjson # Pre-built Kibana dashboard (importable)
│
├── services/
│   ├── auth-service/
│   │   ├── Dockerfile
│   │   └── app.py                         # Emits: login events, token validation, auth failures
│   ├── order-service/
│   │   ├── Dockerfile
│   │   └── app.py                         # Emits: order placement, payment events, SKU warnings
│   └── inventory-service/
│       ├── Dockerfile
│       └── app.py                         # Emits: stock thresholds, replenishment, DB timeouts
│
├── scripts/
│   ├── bootstrap.sh                       # Applies ILM policy + index template post-startup
│   └── verify-pipeline.sh                 # Smoke test: checks ES health, node count, log indices
│
└── docs/
    └── architecture-diagram.md            # Detailed ADR for each design decision
```

---

## Quickstart

### Prerequisites

- Docker Engine ≥ 24.x
- Docker Compose Plugin ≥ 2.x
- ≥ 4 GB RAM available (Elasticsearch is memory-intensive by design)

### Step 1 — Set the required kernel parameter (Linux / WSL)

```bash
# Elasticsearch requires this — default Linux value (65530) is too low
sudo sysctl -w vm.max_map_count=262144

# Persist across reboots:
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
```

### Step 2 — Start the stack

```bash
git clone https://github.com/<your-username>/distributed-log-analytics.git
cd distributed-log-analytics
docker compose up -d --build
```

Startup order (governed by `depends_on` + `healthcheck`):
1. `elasticsearch-01` and `elasticsearch-02` start in parallel
2. `logstash` waits for both ES nodes to be healthy
3. `kibana` waits for `elasticsearch-01` to be healthy
4. `filebeat` waits for `logstash` to be healthy
5. Microservices start alongside Filebeat

### Step 3 — Apply ILM policy and index template

```bash
bash scripts/bootstrap.sh
```

### Step 4 — Verify the pipeline

```bash
bash scripts/verify-pipeline.sh
```

Expected output:
```
[1/4] Checking Elasticsearch cluster health... OK — cluster status: green
[2/4] Checking Logstash pipeline status...     OK — Logstash status: green
[3/4] Checking Elasticsearch node count...     OK — 2 nodes in cluster
[4/4] Checking for any logs-* indices...       OK — Active log indices:
        logs-auth-service-2025.06.14      253 docs   1.2mb
        logs-order-service-2025.06.14     418 docs   2.1mb
        logs-inventory-service-2025.06.14  91 docs   0.5mb
```

### Step 5 — Open Kibana

Navigate to [http://localhost:5601](http://localhost:5601).

1. **Stack Management → Index Patterns** → Create: `logs-*` (time field: `@timestamp`)
2. **Discover** → filter by service: `service_name:"auth-service" AND log_level:"ERROR"`
3. **Dashboards → Import** → upload `kibana/dashboards/log-analytics-dashboard.ndjson`

### Step 6 — Tear down

```bash
# Stop, preserve data volumes:
docker compose down

# Full teardown including all stored log data:
docker compose down -v
```

---

## Configuration Reference

### Logstash Pipeline (`logstash/pipeline/logstash.conf`)

The pipeline has five filter stages:

| Stage | Filter | Purpose |
|---|---|---|
| 1 | `json` | Parse structured JSON logs; skip gracefully if not JSON |
| 2 | `grok` | Fallback parser for plaintext log lines |
| 3 | `date` | Normalise `@timestamp` from the log payload (not ingestion time) |
| 4 | `mutate` | Uppercase `log_level`, add `environment` and `pipeline` fields |
| 5 | `if ERROR` | Tag `error_event`, set `alert.severity = "high"` for alerting |

Failed events that cannot be parsed go to Logstash's **dead-letter queue** (`/usr/share/logstash/data/dead_letter_queue/`) rather than being silently dropped. You can inspect and replay them without re-ingesting raw logs.

### Filebeat Autodiscovery (`filebeat/filebeat.yml`)

Filebeat only ships logs from containers that have the Docker label:
```
co.elastic.logs/enabled: "true"
```
This is an opt-in model — new services must explicitly label themselves, preventing noisy internal infrastructure logs (e.g., from the Elasticsearch containers themselves) from flooding the analytics index.

---

## Resource Governance

All services in `docker-compose.yml` define explicit `deploy.resources` blocks. This is a deliberate infrastructure choice: in a shared host environment (e.g., a development server, a CI runner, or a single-node cloud VM), a memory-unbounded Elasticsearch process can exhaust available RAM and cause OOM-kills of unrelated containers.

| Service | Memory Limit | Memory Reserved | CPU Limit |
|---|---|---|---|
| elasticsearch-01 | **1 GB** | 512 MB | 1.0 core |
| elasticsearch-02 | **1 GB** | 512 MB | 1.0 core |
| logstash | **512 MB** | 256 MB | 0.75 core |
| kibana | **768 MB** | 384 MB | 0.5 core |
| filebeat | **128 MB** | — | 0.25 core |
| auth-service | **128 MB** | — | 0.25 core |
| order-service | **128 MB** | — | 0.25 core |
| inventory-service | **128 MB** | — | 0.25 core |

**Total upper bound: ~3.0 GB RAM, ~3.5 CPU cores.**

Fits comfortably on a `t3.large` (8 GB, 2 vCPU) while leaving OS and system headroom.

> **JVM heap sizing note:** `ES_JAVA_OPTS=-Xms512m -Xmx512m` sets heap to exactly 50% of the container memory limit. This follows the [official Elastic recommendation](https://www.elastic.co/guide/en/elasticsearch/reference/current/heap-size.html) — beyond 50%, the JVM heap competes with Lucene's native off-heap file system cache, degrading search performance.

---

## Index Strategy

Index naming pattern: `logs-{service_name}-{YYYY.MM.dd}`

**Why per-service, per-day indices?**

| Benefit | Detail |
|---|---|
| **Targeted queries** | `GET logs-auth-service-*/_search` — no full-cluster scan |
| **Clean retention** | Delete old data by dropping a daily index, not expensive document deletes |
| **ILM compatibility** | Date suffix enables automatic hot → warm → delete lifecycle transitions |
| **Blast radius isolation** | A high-volume service won't pollute or slow down queries for another service |

**Shard configuration** (set via index template):
```
2 primary shards × 1 replica = 4 total shard copies
Primary on Node 01 → replica on Node 02 (and vice versa)
```
Single-node failure: cluster continues, queries served by surviving node, zero data loss.

---

## Observability Dashboards

Pre-built Kibana dashboards (importable from `kibana/dashboards/`):

| Dashboard | Type | What it shows |
|---|---|---|
| **Log Volume by Service** | Bar chart | Events per service per hour — spot traffic anomalies |
| **Error Rate Timeline** | Time series | ERROR + CRITICAL events per 5-min bucket — maps directly to incident detection |
| **Top Error Messages** | Data table | Aggregated distinct error messages ranked by frequency — pinpoints repeat failures |
| **Log Level Distribution** | Pie chart | DEBUG / INFO / WARN / ERROR ratio — healthy services should be mostly INFO |
| **High-Latency Events** | Line chart | `latency_ms` field over time per service — identifies performance degradation before it becomes an outage |

---

## Operational Runbook

### Check cluster shard allocation

```bash
curl -s "http://localhost:9200/_cat/shards?v&h=index,shard,prirep,state,node"
```

### Simulate a node failure (chaos test)

```bash
docker stop elasticsearch-02
# Verify cluster stays operational (yellow = degraded but alive):
curl -s "http://localhost:9200/_cluster/health?pretty"
docker start elasticsearch-02
# Cluster should return to green within ~15s as shards re-replicate
```

### Force flush index for immediate search visibility

```bash
curl -XPOST "http://localhost:9200/logs-*/_flush"
```

### Inspect dead-letter queue

```bash
docker exec -it logstash ls /usr/share/logstash/data/dead_letter_queue/main/
```

### Reload Logstash pipeline without restart

```bash
# Enable auto-reload in logstash.yml first (config.reload.automatic: true)
curl -XPOST "http://localhost:9600/_node/pipelines/main/_reload"
```

### Check Filebeat shipping offset (confirm no lag)

```bash
docker exec -it filebeat filebeat export config | grep registry
docker exec -it filebeat ls /usr/share/filebeat/data/registry/
```

---

## Roadmap

- [ ] Enable TLS/mTLS between all Elastic stack components (currently disabled for local dev)
- [ ] Add a third Elasticsearch node for proper odd-number quorum (eliminates split-brain risk without `min_master_nodes` tuning)
- [ ] Configure ILM hot → warm → delete lifecycle via `bootstrap.sh` (30-day retention policy)
- [ ] Kibana alerting rules: Slack/PagerDuty webhook on `ERROR count > threshold` per 5-min window
- [ ] Introduce Kafka between Filebeat and Logstash for event buffering, log replay, and multi-consumer support
- [ ] Add Prometheus + Grafana for infrastructure metrics (CPU, memory, GC pauses) alongside log analytics
- [ ] Migrate to Kubernetes using ECK (Elastic Cloud on Kubernetes) Helm operator

---

## License

MIT — free to use, fork, and build upon.