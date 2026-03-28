FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    curl \
    gnupg2 \
    lsb-release \
    python3 \
    python3-pip \
    python3-venv \
    wget \
    procps \
    net-tools \
    iputils-ping \
    jq \
    gettext-base \
    gosu \
    pgbouncer \
    && rm -rf /var/lib/apt/lists/*

# Install PostgreSQL 18
RUN curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y postgresql-18 postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

# Install etcd 3.5.12
ENV ETCD_VERSION=v3.5.12
RUN wget -q https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz \
    && tar xzf etcd-${ETCD_VERSION}-linux-amd64.tar.gz \
    && mv etcd-${ETCD_VERSION}-linux-amd64/etcd /usr/local/bin/ \
    && mv etcd-${ETCD_VERSION}-linux-amd64/etcdctl /usr/local/bin/ \
    && rm -rf etcd-${ETCD_VERSION}-linux-amd64*

# Install Patroni in a virtualenv
RUN python3 -m venv /opt/patroni \
    && /opt/patroni/bin/pip install --upgrade pip \
    && /opt/patroni/bin/pip install "patroni[etcd3]" psycopg2-binary

ENV PATH="/opt/patroni/bin:${PATH}"

# Directories
RUN mkdir -p /data/patroni /data/etcd /var/run/postgresql /var/run/pgbouncer \
    && chown -R postgres:postgres /data /var/run/postgresql /var/run/pgbouncer \
    && chmod 700 /data/patroni /data/etcd

COPY patroni.yml /etc/patroni.yml
# COPY post_init.sh /etc/patroni_post_init.sh
COPY entrypoint.sh /entrypoint.sh
# RUN chmod +x /entrypoint.sh /etc/patroni_post_init.sh


EXPOSE 5432 6432 8008 2379 2380

USER root
# PgBouncer config is bind-mounted at runtime from ./pgbouncer/
# (see docker-compose.yml volumes section)
ENTRYPOINT ["/entrypoint.sh"]
