#!/bin/bash
# Generates per-boot secrets, initialises Postgres on first boot, then hands over to supervisord.
set -euo pipefail
R=/home/user/runtime; PGBIN=$(ls -d /usr/lib/postgresql/*/bin | head -1)
mkdir -p "$R" /home/user/pg /home/user/redis /tmp/prometheus_multiproc
if [ ! -f "$R/env" ]; then
  PGPW=$(openssl rand -hex 24); RPW=$(openssl rand -hex 24)
  cat > "$R/env" <<EOF
export SECRET_KEY=$(openssl rand -hex 32)
export METRICS_TOKEN=$(openssl rand -hex 24)
export DATABASE_URL=postgresql+asyncpg://copilot:${PGPW}@127.0.0.1:5432/industrial_copilot
export REDIS_URL=redis://:${RPW}@127.0.0.1:6379/0
export REDIS_PASSWORD=${RPW}
export PGPASSWORD=${PGPW}
EOF
  echo "$PGPW" > "$R/pgpw"; chmod 600 "$R/env" "$R/pgpw"
fi
. "$R/env"
if [ ! -s /home/user/pg/PG_VERSION ]; then
  "$PGBIN/initdb" -D /home/user/pg -U copilot --pwfile="$R/pgpw" --auth=scram-sha-256 -E UTF8 > /dev/null
  "$PGBIN/pg_ctl" -D /home/user/pg -o "-c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp" -w start > /dev/null
  createdb -h 127.0.0.1 -U copilot industrial_copilot
  "$PGBIN/pg_ctl" -D /home/user/pg -m fast -w stop > /dev/null
fi
exec supervisord -n -c /home/user/supervisord.conf
