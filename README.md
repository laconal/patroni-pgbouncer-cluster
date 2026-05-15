need to change host in subnet to your host's machine ip

# PostgreSQL HA Cluster — Patroni + etcd + HAProxy + PgBouncer (sidecar)

## Architecture

```
  Your App / psql
       │
       ▼
 ┌─────────────────────────────────────────────┐
 │           haproxy  (container)              │
 │  port 5000 → primary   (read/write)         │
 │  port 5001 → replicas  (read-only LB)       │
 │  port 7000 → stats UI                       │
 └────────┬──────────────┬──────────────┬──────┘
          │              │              │
          │  health-check via Patroni REST (:8008)
          ▼              ▼              ▼
   ┌────────────┐ ┌────────────┐ ┌────────────┐
   │  patroni1  │ │  patroni2  │ │  patroni3  │
   │            │ │            │ │            │
   │ PgBouncer  │ │ PgBouncer  │ │ PgBouncer  │  :6432
   │     ↓      │ │     ↓      │ │     ↓      │
   │ PostgreSQL │ │ PostgreSQL │ │ PostgreSQL │  :5432
   │   etcd     │ │   etcd     │ │   etcd     │  :2379/:2380
   │   Patroni  │ │   Patroni  │ │   Patroni  │  :8008
   └────────────┘ └────────────┘ └────────────┘
```

**How routing works:**

1. HAProxy checks `GET /primary` or `GET /replica` on each node's Patroni REST API (`:8008`).
2. It forwards the connection to PgBouncer (`:6432`) on the correct node(s).
3. PgBouncer pools the connection and talks to the **local** PostgreSQL (`:5432`).

PgBouncer never needs to know about primary/replica roles — HAProxy handles all
that routing before the connection even reaches PgBouncer.

---

## Prerequisites (WSL2)

- Docker Desktop with WSL2 backend enabled
- At least **4 GB free RAM** recommended
- Or run containers in

---

## Quick Start

```bash
# 1. Clone / copy this folder somewhere in WSL2
cd patroni-cluster

# 2. Build all images (first time takes ~3–5 min)
docker compose build

# 3. Start the cluster
docker compose up -d

# 4. Watch the logs until the cluster elects a leader (30–60 s)
docker compose logs -f

# 5. Check cluster status
docker exec -it patroni1 patronictl -c /tmp/patroni.yml list
```

---

## Connecting

| Endpoint         | Use                                          |
| ---------------- | -------------------------------------------- |
| `localhost:5000` | Primary — always writable (via PgBouncer)    |
| `localhost:5001` | Replicas — round-robin reads (via PgBouncer) |
| `localhost:7000` | HAProxy stats dashboard                      |
| `localhost:6432` | PgBouncer on patroni1 direct (debug)         |
| `localhost:6433` | PgBouncer on patroni2 direct (debug)         |
| `localhost:6434` | PgBouncer on patroni3 direct (debug)         |
| `localhost:5432` | PostgreSQL on patroni1 direct (debug)        |
| `localhost:5433` | PostgreSQL on patroni2 direct (debug)        |
| `localhost:5434` | PostgreSQL on patroni3 direct (debug)        |

### psql examples

```bash
# Connect via HAProxy → PgBouncer → primary
psql -h localhost -p 5000 -U postgres -d postgres
# password: postgres_password

# Connect via HAProxy → PgBouncer → a replica
psql -h localhost -p 5001 -U postgres -d postgres

# Check which node is the leader
psql -h localhost -p 5000 -U postgres -c "SELECT pg_is_in_recovery();"
# f = false → you're on the primary ✓
```

---

## Credentials

| Role        | Username        | Password                 |
| ----------- | --------------- | ------------------------ |
| Superuser   | postgres        | postgres_password        |
| Admin app   | admin           | admin_password           |
| Replication | replicator      | rep_password             |
| PgBouncer   | pgbouncer_admin | pgbouncer_admin_password |

> ⚠️ Change these in `patroni/patroni.yml` and `pgbouncer/userlist.txt` before any real use.

---

## Testing Failover

```bash
# 1. See who is primary
docker exec -it patroni1 patronictl -c /tmp/patroni.yml list

# 2. Kill the primary (e.g. patroni1)
docker compose stop patroni1

# 3. Watch HAProxy redirect to the new primary within ~10 s
#    (stats page: http://localhost:7000)

# 4. Reconnect — port 5000 now points to the new leader's PgBouncer
psql -h localhost -p 5000 -U postgres -c "SELECT pg_is_in_recovery();"

# 5. Bring patroni1 back — it rejoins as a replica
docker compose start patroni1
docker exec -it patroni2 patronictl -c /tmp/patroni.yml list
```

---

## Useful Commands

```bash
# Full cluster status
docker exec -it patroni1 patronictl -c /tmp/patroni.yml list

# Trigger a manual switchover
docker exec -it patroni1 patronictl -c /tmp/patroni.yml switchover --master <current-leader> --candidate <target>

# PgBouncer stats on a node
psql -h localhost -p 6432 -U pgbouncer_admin -d pgbouncer -c "SHOW POOLS;"
psql -h localhost -p 6432 -U pgbouncer_admin -d pgbouncer -c "SHOW CLIENTS;"

# etcd cluster health
docker exec -it patroni1 etcdctl \
  --endpoints=http://patroni1:2379,http://patroni2:2379,http://patroni3:2379 \
  endpoint health

# Tail logs for one node
docker compose logs -f patroni1

# Stop everything
docker compose down

# Full reset (deletes all data)
docker compose down -v
```

---

## Ports Used on WSL2 Host

| Host port | Container | Purpose                         |
| --------- | --------- | ------------------------------- |
| 5000      | haproxy   | PG primary R/W (via PgBouncer)  |
| 5001      | haproxy   | PG replicas R/O (via PgBouncer) |
| 7000      | haproxy   | Stats UI                        |
| 5432      | patroni1  | PG direct (debug)               |
| 5433      | patroni2  | PG direct (debug)               |
| 5434      | patroni3  | PG direct (debug)               |
| 6432      | patroni1  | PgBouncer direct (debug)        |
| 6433      | patroni2  | PgBouncer direct (debug)        |
| 6434      | patroni3  | PgBouncer direct (debug)        |
| 8008      | patroni1  | Patroni REST                    |
| 8009      | patroni2  | Patroni REST                    |
| 8010      | patroni3  | Patroni REST                    |
| 2379      | patroni1  | etcd client                     |
| 2380      | patroni2  | etcd client                     |
| 2381      | patroni3  | etcd client                     |

---

## Troubleshooting

**Cluster stuck / no leader elected**

```bash
docker compose logs patroni1 | grep -E "ERROR|leader|primary"
# Common cause: etcd peers not yet reachable — wait ~30 s and retry
```

**PgBouncer not accepting connections**

```bash
docker exec -it patroni1 cat /var/log/pgbouncer.log
# Check that /etc/pgbouncer/pgbouncer.ini is mounted correctly
```

**"could not connect to server"**

```bash
# Check HAProxy health
curl http://localhost:7000
# Check Patroni is up
curl http://localhost:8008/health
# Check PgBouncer is up on the node
pg_isready -h localhost -p 6432
```

**WSL2 port conflicts**
If a port is already in use, edit the `ports:` section of `docker-compose.yml` to remap (e.g. `"16432:6432"`).
