#!/bin/bash
set -e

# ── Fix volume permissions (runs as root) ─────────────────────────────────────
echo "==> Fixing data directory permissions"
# chown -R postgres:postgres /data /var/run/postgresql /var/run/pgbouncer
mkdir -p /var/log/pgbouncer /var/run/pgbouncer
chown -R postgres:postgres /data /var/run/postgresql /var/run/pgbouncer /var/log/pgbouncer
chmod 700 /data/patroni /data/etcd

# ── Drop to postgres for everything else ──────────────────────────────────────
if [ "$(id -u)" = "0" ]; then
  exec gosu postgres "$0" "$@"
fi

# ── From here we are running as postgres ──────────────────────────────────────
NODE_IP=$(hostname -i | awk '{print $1}')
export NODE_IP
export NODE_NAME=${NODE_NAME:-$(hostname)}

echo "==> Starting node: ${NODE_NAME} (${NODE_IP}) as $(whoami)"

# ── etcd ──────────────────────────────────────────────────────────────────────
INITIAL_CLUSTER="patroni1=http://patroni1:2380,patroni2=http://patroni2:2380,patroni3=http://patroni3:2380"

echo "==> Starting etcd member: ${NODE_NAME}"
etcd \
  --name="${NODE_NAME}" \
  --data-dir="/data/etcd" \
  --listen-client-urls="http://0.0.0.0:2379" \
  --advertise-client-urls="http://${NODE_NAME}:2379" \
  --listen-peer-urls="http://0.0.0.0:2380" \
  --initial-advertise-peer-urls="http://${NODE_NAME}:2380" \
  --initial-cluster="${INITIAL_CLUSTER}" \
  --initial-cluster-token="etcd-cluster-1" \
  --initial-cluster-state="new" \
  --log-level=warn \
  &

echo "==> Waiting for etcd..."
for i in $(seq 1 30); do
  if etcdctl --endpoints=http://127.0.0.1:2379 endpoint health >/dev/null 2>&1; then
    echo "==> etcd ready (attempt ${i})"
    break
  fi
  sleep 2
done

# ── Patroni ───────────────────────────────────────────────────────────────────
echo "==> Rendering Patroni config"
envsubst < /etc/patroni.yml > /tmp/patroni.yml

echo "==> Starting Patroni (background), waiting for PostgreSQL..."
patroni /tmp/patroni.yml &
PATRONI_PID=$!

# Wait until PostgreSQL is accepting connections on this node
for i in $(seq 1 60); do
  if pg_isready -h 127.0.0.1 -p 5432 -U postgres >/dev/null 2>&1; then
    echo "==> PostgreSQL ready (attempt ${i}), starting PgBouncer"
    break
  fi
  sleep 3
done

echo "==> Starting PgBouncer (localhost:6432 → localhost:5432)"
pgbouncer -d /etc/pgbouncer/pgbouncer.ini

wait $PATRONI_PID
