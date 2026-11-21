#!/usr/bin/env bash
# Prepara una instancia Ubuntu 24.04 como nodo de la BDD (PostgreSQL 16).
# Ejecutar en CADA una de las tres instancias, con la MISMA contraseña:
#     sudo bash instalar_nodo.sh MiClave2026
# Instala: postgresql (trae postgres_fdw) y python3-psycopg2 (para los scripts).
set -euo pipefail
cd /tmp

if [ "$(id -u)" -ne 0 ]; then
  echo "Ejecútalo con sudo: sudo bash instalar_nodo.sh CONTRASEÑA"; exit 1
fi
PASS="${1:-}"
if ! [[ "$PASS" =~ ^[A-Za-z0-9]{8,}$ ]]; then
  echo "La contraseña debe tener al menos 8 letras o números (sin símbolos) y ser la misma en los tres nodos."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y postgresql python3-psycopg2

VER=$(ls /etc/postgresql | sort -n | tail -1)
ETC=/etc/postgresql/$VER/main

# Parámetros del proyecto: escuchar en la red, 2PC y replicación lógica
cat > "$ETC/conf.d/bdd.conf" <<'EOF'
listen_addresses = '*'
max_connections = 60
max_prepared_transactions = 50
wal_level = logical
max_replication_slots = 10
max_wal_senders = 10
EOF

# Acceso remoto solo con SSL y contraseña; el grupo de seguridad decide qué IP llegan
if ! grep -q "proyecto-bdd" "$ETC/pg_hba.conf"; then
  echo "hostssl all postgres 0.0.0.0/0 scram-sha-256   # proyecto-bdd" >> "$ETC/pg_hba.conf"
fi

systemctl restart postgresql
echo "ALTER USER postgres PASSWORD :'clave';" | sudo -u postgres psql -q -v clave="$PASS"

sudo -u postgres psql -Atc "SELECT 'PostgreSQL ' || current_setting('server_version')
  || ' | wal_level=' || current_setting('wal_level')
  || ' | max_prepared_transactions=' || current_setting('max_prepared_transactions')
  || ' | listen_addresses=' || current_setting('listen_addresses')"
echo "Nodo listo."
