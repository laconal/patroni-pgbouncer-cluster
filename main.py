"""
PostgreSQL HA Cluster Tester
Tests writes via HAProxy port 5000 (leader) and reads via port 5001 (round-robin replicas)

Requirements:
    pip install psycopg2-binary

Usage:
    python pg_cluster_test.py
"""

import psycopg2
import time
import random
from datetime import datetime
from collections import Counter

# ── Configuration ─────────────────────────────────────────────────────────────
HAPROXY_HOST = "localhost"   # vm1 — change if HAProxy is on a different VM

WRITE_PORT   = 5000               # HAProxy → leader only
READ_PORT    = 5001               # HAProxy → all nodes, round-robin

DB_NAME      = "postgres"
DB_USER      = "postgres"
DB_PASSWORD  = "postgres_password"   # ← change this

TEST_TABLE   = "pythonTable"
WRITE_ROUNDS = 10            # how many rows to insert
READ_ROUNDS  = 150              # how many read queries to fire (proves balancing)
# ──────────────────────────────────────────────────────────────────────────────


def connect(port, label):
    return psycopg2.connect(
        host=HAPROXY_HOST,
        port=port,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=5,
        application_name=label,
    )


def section(title):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def ok(msg):  print(f"  ✅  {msg}")
def err(msg): print(f"  ❌  {msg}")
def info(msg):print(f"  ℹ️   {msg}")


# ── 1. Setup ──────────────────────────────────────────────────────────────────
section("SETUP — Create test table via WRITE port (5000)")
try:
    conn = connect(WRITE_PORT, "writer-setup")
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TEST_TABLE} (
            id        SERIAL PRIMARY KEY,
            message   TEXT,
            node_addr INET,
            written_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    ok(f"Table '{TEST_TABLE}' is ready")

    cur.execute("SELECT inet_server_addr(), pg_is_in_recovery()")
    addr, is_replica = cur.fetchone()
    ok(f"Connected to node: {addr}  |  is_replica={is_replica}")
    if not is_replica:
        ok("Confirmed: write port (5000) reached the LEADER ✓")
    else:
        err("Write port reached a REPLICA — HAProxy health check may be misconfigured!")

    cur.close()
    conn.close()
except Exception as e:
    err(f"Setup failed: {e}")
    raise SystemExit(1)


# ── 2. Write test ─────────────────────────────────────────────────────────────
section(f"WRITE TEST — Inserting {WRITE_ROUNDS} rows via port 5000")
inserted_ids = []
try:
    conn = connect(WRITE_PORT, "writer")
    conn.autocommit = False
    cur = conn.cursor()

    for i in range(1, WRITE_ROUNDS + 1):
        msg = f"test-row-{i}-{random.randint(1000,9999)}"
        cur.execute(
            f"INSERT INTO {TEST_TABLE} (message, node_addr) VALUES (%s, inet_server_addr()) RETURNING id",
            (msg,)
        )
        row_id = cur.fetchone()[0]
        inserted_ids.append(row_id)
        print(f"  → Row {i:02d}: id={row_id}  message='{msg}'")
        time.sleep(0.1)

    conn.commit()
    ok(f"All {WRITE_ROUNDS} rows committed successfully")
    cur.close()
    conn.close()
except Exception as e:
    err(f"Write test failed: {e}")


# ── 3. Read + load balance test ───────────────────────────────────────────────
section(f"READ TEST — {READ_ROUNDS} queries via port 5001 (round-robin)")
node_hits = Counter()
read_errors = 0

for i in range(1, READ_ROUNDS + 1):
    try:
        conn = connect(READ_PORT, f"reader-{i}")
        cur = conn.cursor()

        cur.execute("SELECT inet_server_addr()::text, pg_is_in_recovery()")
        addr, is_replica = cur.fetchone()
        addr = addr or "unknown"
        node_hits[addr] += 1

        cur.execute(f"SELECT COUNT(*) FROM {TEST_TABLE}")
        row_count = cur.fetchone()[0]

        role = "replica" if is_replica else "LEADER"
        print(f"  → Query {i:02d}: node={addr:<15}  role={role:<8}  rows_visible={row_count}")

        cur.close()
        conn.close()
        time.sleep(0.05)
    except Exception as e:
        err(f"Read query {i} failed: {e}")
        read_errors += 1


# ── 4. Load balance summary ───────────────────────────────────────────────────
section("LOAD BALANCE SUMMARY")
if len(node_hits) > 1:
    ok(f"Traffic was distributed across {len(node_hits)} nodes ✓")
else:
    err(f"All reads hit only 1 node — round-robin may not be working!")

print()
for addr, hits in sorted(node_hits.items(), key=lambda x: -x[1]):
    bar = "█" * hits
    pct = hits / READ_ROUNDS * 100
    print(f"  {addr:<18} {bar:<20} {hits} hits ({pct:.0f}%)")

if read_errors:
    err(f"{read_errors} read queries failed")


# ── 5. Replication lag check ──────────────────────────────────────────────────
section("REPLICATION LAG — via WRITE port (leader view)")
try:
    conn = connect(WRITE_PORT, "lag-check")
    cur = conn.cursor()
    cur.execute("""
        SELECT application_name,
               client_addr,
               state,
               write_lag,
               flush_lag,
               replay_lag,
               sync_state
        FROM pg_stat_replication
        ORDER BY client_addr
    """)
    rows = cur.fetchall()
    if rows:
        print(f"\n  {'App':<20} {'Client':<18} {'State':<12} {'Write lag':<12} {'Replay lag':<12} {'Sync'}")
        print(f"  {'-'*20} {'-'*18} {'-'*12} {'-'*12} {'-'*12} {'-'*10}")
        for r in rows:
            app, client, state, w_lag, f_lag, r_lag, sync = r
            print(f"  {str(app):<20} {str(client):<18} {str(state):<12} {str(w_lag):<12} {str(r_lag):<12} {str(sync)}")
        ok("All replicas reported above")
    else:
        info("No replication connections visible (may be using pgbouncer — normal)")
    cur.close()
    conn.close()
except Exception as e:
    err(f"Lag check failed: {e}")


# ── 6. Cleanup ────────────────────────────────────────────────────────────────
section("CLEANUP")
try:
    conn = connect(WRITE_PORT, "cleanup")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {TEST_TABLE}")
    ok(f"Table '{TEST_TABLE}' dropped")
    cur.close()
    conn.close()
except Exception as e:
    err(f"Cleanup failed: {e}")

section("DONE")
print(f"  Finished at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")