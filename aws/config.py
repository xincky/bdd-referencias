"""Lectura de aws/nodos.json y conexiones a los nodos desde cualquier instancia."""
import json
import os
from pathlib import Path

import psycopg2

RUTA = Path(os.environ.get("BDD_CONFIG", Path(__file__).resolve().parent / "nodos.json"))
REGIONES = ("CUS", "APU", "MDD")


def cargar():
    if not RUTA.exists():
        raise SystemExit(f"No encuentro {RUTA}. Copia aws/nodos.json.ejemplo como aws/nodos.json "
                         "y escribe las IP públicas y la contraseña.")
    cfg = json.load(open(RUTA))
    cfg.setdefault("puerto", {})
    cfg["puerto"] = {r: int(cfg["puerto"].get(r, 5432)) for r in REGIONES}
    cfg.setdefault("central_db", "central")
    return cfg


CFG = cargar()


def destino(nodo, desde):
    """(host, puerto) para llegar a 'nodo' desde la instancia 'desde'."""
    host = "127.0.0.1" if nodo == desde else CFG["ip"][nodo]
    return host, CFG["puerto"][nodo]


def conectar(nodo, desde, dbname="referencias"):
    """nodo: CUS, APU, MDD o CENTRAL (base 'central' dentro del servidor de Cusco)."""
    if nodo == "CENTRAL":
        nodo, dbname = "CUS", CFG["central_db"]
    host, port = destino(nodo, desde)
    c = psycopg2.connect(host=host, port=port, user="postgres", password=CFG["password"],
                         dbname=dbname, connect_timeout=10)
    c.autocommit = True
    return c
