#!/usr/bin/env python3
"""Comprueba que esta instancia llega por PostgreSQL a los tres nodos y mide el RTT.

Uso:  python3 aws/probar_conexion.py --desde CUS     (o APU, MDD: la instancia donde lo corres)
Si un nodo falla, revisa: grupo de seguridad (5432 desde esta IP), IP en nodos.json,
contraseña y que instalar_nodo.sh haya terminado en ese nodo.
"""
import argparse
import statistics
import time

import psycopg2

from config import CFG, REGIONES, conectar, destino

ap = argparse.ArgumentParser()
ap.add_argument("--desde", required=True, choices=REGIONES)
args = ap.parse_args()

for nodo in REGIONES:
    host, port = destino(nodo, args.desde)
    try:
        c = conectar(nodo, args.desde, "postgres")
        cur = c.cursor()
        cur.execute("SELECT current_setting('server_version'), current_setting('wal_level'), "
                    "current_setting('max_prepared_transactions'), "
                    "(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid())")
        ver, wal, mpt, ssl = cur.fetchone()
        ms = []
        for _ in range(20):
            t = time.perf_counter()
            cur.execute("SELECT 1")
            cur.fetchone()
            ms.append((time.perf_counter() - t) * 1000)
        print(f"OK   {nodo} ({host}:{port})  PostgreSQL {ver}  wal_level={wal}  "
              f"max_prepared_transactions={mpt}  ssl={ssl}  RTT p50={statistics.median(ms):.1f} ms")
        c.close()
    except psycopg2.Error as e:
        print(f"FALLA {nodo} ({host}:{port}): {str(e).strip().splitlines()[0]}")
