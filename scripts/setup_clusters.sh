#!/usr/bin/env bash
# Crea e inicia cuatro instancias PostgreSQL 16 en la misma máquina:
#   n_cus   (Cusco, nodo 1, hospitales nivel III)  puerto 5431
#   n_apu   (Apurímac, nodo 2, hospitales nivel II) puerto 5432
#   n_mdd   (Madre de Dios, nodo 3, nivel II)       puerto 5433
#   central (línea base: un solo servidor en Cusco)  puerto 5440
# Uso: sudo -u pg bash setup_clusters.sh   (no se puede ejecutar como root)
set -euo pipefail
PGBIN=${PGBIN:-/usr/lib/postgresql/16/bin}
BASE=${BASE:-/srv/pgdata}

declare -A PORTS=( [n_cus]=5431 [n_apu]=5432 [n_mdd]=5433 [central]=5440 )

for name in n_cus n_apu n_mdd central; do
  dir="$BASE/$name"
  port=${PORTS[$name]}
  if [ ! -d "$dir" ]; then
    "$PGBIN/initdb" -D "$dir" -U postgres --auth=trust -E UTF8 --locale=C.UTF-8 >/dev/null
    cat >> "$dir/postgresql.conf" <<EOF
port = $port
listen_addresses = '127.0.0.1'
unix_socket_directories = '/tmp'
max_connections = 60
shared_buffers = 128MB
max_prepared_transactions = 50      # necesario para 2PC (PREPARE TRANSACTION)
wal_level = logical                  # necesario para replicación lógica
max_replication_slots = 10
max_wal_senders = 10
synchronous_commit = on
fsync = on
EOF
  fi
  "$PGBIN/pg_ctl" -D "$dir" -l "$BASE/$name.log" -w start >/dev/null
  echo "$name iniciado en el puerto $port"
done
