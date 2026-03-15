# Distributed Log Analytics Pipeline — EFK Stack

> A **Docker Compose–based** observability system that centralises log aggregation from multiple services using Elasticsearch, Fluentd, and Kibana — engineered with a focus on **High Availability**, **resource governance**, and **operational simplicity** to reduce Mean Time to Recovery (MTTR) during incidents.

---

## Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Why This Architecture?](#why-this-architecture)
- [Stack Components](#stack-components)
- [Project Structure](#project-structure)
- [Quickstart](#quickstart)
- [Configuration Reference](#configuration-reference)
- [Resource Governance](#resource-governance)
- [Index Strategy](#index-strategy)
- [Operational Runbook](#operational-runbook)
- [Roadmap](#roadmap)

---

## Overview

When a production incident occurs, the first question is always: *what do the logs say?* In a distributed system where each service manages its own logs separately, answering that question costs precious minutes. This project builds a **centralised EFK pipeline** that aggregates logs from all services into a single, searchable system — so that correlating events across services during an outage is a KQL query, not a manual file hunt.

**What this project prioritises (and why it's different):**
- **High Availability at the storage layer** — two Elasticsearch nodes with replica shards, so a single node failure doesn't take down the entire observability stack
- **Resource-bound deployment** — every container runs with explicit memory and CPU limits, a critical but often-overlooked requirement in real shared-infrastructure environments
- **Persistent Fluentd buffering** — logs are not lost if Elasticsearch is temporarily unavailable; Fluentd buffers to disk and retries
- **Docker Compose over Kubernetes** — runs on *any* Linux/Mac host without a cluster, making local development and CI testing straightforward

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DOCKER HOST                              │
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │  Service A  │  │  Service B  │  │      Service C      │   │
│  │  (any app)  │  │  (any app)  │  │      (any app)      │   │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘   │
│         │                │                     │               │
│         └────────────────┴─────────────────────┘               │
│                          │ Docker logging driver                │
│                          │ (fluentd driver — port 24224)        │
│          ┌───────────────▼───────────────┐                     │
│          │           FLUENTD             │  256 MB / 0.5 CPU   │
│          │  central log aggregator       │                     │
│          │  • filter / parse / tag       │                     │
│          │  • route by log level/service │                     │
│          │  • persistent disk buffer     │                     │
│          └───────────┬───────────────────┘                     │
│                      │ HTTP bulk to both ES nodes               │
│          ┌───────────┴──────────┬────────────────┐             │
│          │                      │                │             │
│  ┌───────▼──────┐    ┌──────────▼──────┐        │             │
│  │ ELASTIC      │◄──►│  ELASTIC        │  2-node cluster       │
│  │ SEARCH 01    │    │  SEARCH 02      │  replica shards       │
│  │ 1GB / 1CPU   │    │  1GB / 1CPU     │  HA-aware             │
│  └───────┬──────┘    └─────────────────┘        │             │
│          │                                       │             │
│  ┌───────▼───────────────────────────────────┐  │             │
│  │                  KIBANA                   │ 768MB / 0.5CPU  │
│  │   Discover · Dashboards · Alerts          │                 │
│  │   http://localhost:5601                   │                 │
│  └───────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Why This Architecture?

### Core Design Goal: Decouple Log Generation from Log Storage

Applications should write to `stdout` (or the Docker logging driver) and have zero knowledge of what happens to those logs afterwards. This project enforces that contract — Fluentd is the only component that knows about Elasticsearch. If the storage layer changes, no application code changes.

### Why Two Elasticsearch Nodes?

A single-node Elasticsearch instance **cannot hold replica shards**. If that node fails, the entire log history is gone. With two nodes:

| Scenario | Single Node | Two Nodes |
|---|---|---|
| Node hardware failure | ❌ Total data loss | ✅ Replica on second node, zero loss |
| Node restart / upgrade | ❌ Queries fail | ✅ Cluster serves queries from surviving node |
| Write throughput | Limited to one node | Distributed across both |

### Why Persistent Fluentd Buffering?
Fluentd is configured with a file-based buffer (mounted as a Docker volume). If Elasticsearch nodes are temporarily unavailable (e.g., during a rolling restart), Fluentd queues events to disk and retries with exponential backoff. **No logs are lost during planned maintenance.**

### Why Docker Compose and Not Kubernetes?
The Fluentd configurations in this repo (`fluentd-solution/`) are already designed for **cluster-wide log collection** with per-namespace routing and centralized alert indices. Running this on Docker Compose separates the *pipeline logic* from the *infrastructure orchestration* — making it faster to iterate on Fluentd filter rules, index routing strategies, and Kibana dashboards without managing a Kubernetes cluster.

---

## Stack Components

| Component | Version | Role |
|---|---|---|
| Elasticsearch | 8.13.4 | Distributed search & analytics — primary log data store |
| Fluentd | 1.16.x | Log aggregation, filtering, routing, and enrichment |
| Kibana | 8.13.4 | Visualisation, KQL search, dashboard, and alerting UI |

> All Elastic components use the same version — cross-version compatibility in the Elastic stack is strictly controlled and mixing versions causes silent API failures.

---

## Project Structure

```
distributed-log-analytics/
│
├── docker-compose.yml                    # EFK stack with HA ES cluster + resource limits
│
├── fluentd-solution/
│   ├── Dockerfile                        # Fluentd image + fluent-plugin-elasticsearch
│   └── configs/
│       ├── fluentd-single-namespace.yaml         # Single-namespace log collection
│       ├── fluentd-multi-namespace-per-ns-*.yaml # Per-namespace index routing
│       ├── fluentd-all-except-system-config.yaml # Cluster-wide (excludes kube-system)
│       ├── fluentd-daemonset.yaml                # K8s DaemonSet manifest (optional)
│       └── fluentd-multi-namespace-centralized-alerts-config.yaml
│
├── efk-helm-chart/                       # Helm chart for Kubernetes deployment
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│
└── docs/
    └── architecture-diagram.md           # Extended architecture notes
```

---

## Quickstart

### Prerequisites
- Docker Engine ≥ 24.x and Docker Compose Plugin ≥ 2.x
- At least **4 GB RAM** available (Elasticsearch heap + OS = significant memory requirement)

### Step 1 — Kernel parameter (Linux/WSL)

```bash
sudo sysctl -w vm.max_map_count=262144
# Persist:
echo "vm.max_map_count=262144" | sudo tee -a /etc/sysctl.conf
```

### Step 2 — Start the stack

```bash
git clone https://github.com/siddharthkhedkar223/distributed-log-analytics.git
cd distributed-log-analytics
docker compose up -d
```

Startup order (enforced by `depends_on` + healthchecks):
1. `elasticsearch-01` and `elasticsearch-02` start in parallel
2. `fluentd` waits for both ES nodes to pass healthcheck
3. `kibana` waits for `elasticsearch-01` to be healthy

### Step 3 — Verify cluster health

```bash
# Both nodes should appear
curl -s http://localhost:9200/_cat/nodes?v

# Cluster status: green (both nodes) or yellow (degraded but alive)
curl -s http://localhost:9200/_cluster/health?pretty
```

### Step 4 — Open Kibana

Navigate to [http://localhost:5601](http://localhost:5601)

1. **Stack Management → Index Patterns** → Create: `fluentd-*` (time field: `@timestamp`)
2. **Discover** → search logs in real-time with KQL
3. Build dashboards with **log volume by namespace**, **error rate over time**

### Step 5 — Tear down

```bash
docker compose down          # stop, keep volumes (data persists)
docker compose down -v       # stop + delete all stored log data
```

---

## Configuration Reference

### Fluentd Routing Configurations (`fluentd-solution/configs/`)

| Config File | Use Case |
|---|---|
| `fluentd-single-namespace.yaml` | Collect logs from one specific namespace |
| `fluentd-multi-namespace-per-ns-alert-config.yaml` | Per-namespace indices + custom alert pattern detection |
| `fluentd-all-except-system-config.yaml` | Cluster-wide collection, excludes system namespaces |
| `fluentd-multi-namespace-centralized-alerts-config.yaml` | Centralized index for all alerts regardless of source |

### Index Routing Strategy

Fluentd routes logs to distinct Elasticsearch indices based on source namespace and log content:

```
logs.namespace-A.YYYYMMDD   → namespace-scoped index
logs.namespace-B.YYYYMMDD   → namespace-scoped index
alerts.centralized.YYYYMMDD → aggregated alert index across all namespaces
```

This eliminates cross-namespace query overhead — searching for errors in one service doesn't require scanning the entire cluster.

---

## Resource Governance

Every container in this stack has explicit `deploy.resources` limits. This is essential in any shared environment: an unbounded Elasticsearch JVM heap will consume all available host memory and cause OOM-kills of co-located application containers.

| Service | Memory Limit | CPU Limit | Notes |
|---|---|---|---|
| elasticsearch-01 | **1 GB** | 1.0 core | JVM heap: 512 MB (50% of limit) |
| elasticsearch-02 | **1 GB** | 1.0 core | JVM heap: 512 MB (50% of limit) |
| fluentd | **256 MB** | 0.5 core | Buffer to disk, not RAM |
| kibana | **768 MB** | 0.5 core | Node.js process, UI only |

**Total upper bound: ~3 GB RAM, ~3 CPU cores.** Fits on a `t3.large` (8 GB, 2 vCPU) with system headroom.

> **JVM heap rule:** `ES_JAVA_OPTS=-Xms512m -Xmx512m` = exactly 50% of the 1 GB container limit. Beyond 50%, the heap competes with Lucene's native file system cache and degrades search performance.

---

## Index Strategy

Indices follow: `fluentd-{namespace/service}-{YYYYMMDD}`

| Benefit | Why It Matters |
|---|---|
| **Per-source isolation** | Query only the namespace you care about |
| **Daily rollover** | Drop old indices by date — O(1) operation vs. expensive document deletes |
| **ILM-compatible** | Date suffix enables automatic hot → warm → delete lifecycle transitions |
| **Alert isolation** | Centralized alert index (`alerts.*`) can be monitored independently |

---

## Operational Runbook

### Check shard distribution

```bash
curl -s "http://localhost:9200/_cat/shards?v&h=index,shard,prirep,state,node"
```

### Simulate node failure (chaos test)

```bash
docker stop elasticsearch-02
# Cluster should stay alive in yellow state:
curl -s "http://localhost:9200/_cluster/health?pretty"
# Restart and watch it recover to green:
docker start elasticsearch-02
```

### Check Fluentd buffer status

```bash
docker exec -it fluentd ls /fluentd/buffer/
```

### Force flush all pending buffered logs

```bash
docker exec -it fluentd kill -USR1 1
```

---

## Roadmap

- [ ] Enable TLS/mTLS between all EFK components
- [ ] Add third Elasticsearch node for proper odd-number quorum
- [ ] Configure ILM hot → warm → delete (30-day retention)
- [ ] Kibana alerting: Slack webhook on centralized alert index spike
- [ ] Helm chart deployment tested on a local kind/minikube cluster

---

## License

MIT