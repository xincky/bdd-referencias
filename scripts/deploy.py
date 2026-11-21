#!/usr/bin/env python3
"""Despliega el esquema, la distribución y los datos en los cuatro servidores.

Diseño de la distribución (BDD homogénea, 3 nodos):
  * establecimiento      -> replicada completa; copia maestra en Cusco y
                            réplicas en Apurímac y Madre de Dios (replicación lógica).
  * referencia           -> fragmentación horizontal por región de origen
                            (apu.referencia, cus.referencia, mdd.referencia).
  * contrarreferencia    -> fragmentación horizontal derivada de referencia
                            (vive en el mismo nodo que su referencia).
  * cupo, reserva_cupo   -> en el nodo del hospital dueño de las camas.
  * Cusco guarda además una réplica de solo lectura de las referencias que
    Apurímac y Madre de Dios le envían (replicación lógica con filtro de filas).
  * En cada nodo, public.referencia y public.contrarreferencia son tablas
    particionadas por región: la partición local es el fragmento propio y las
    otras dos son tablas foráneas (postgres_fdw). Así el usuario escribe SQL
    sobre una sola tabla (transparencia de ubicación y de fragmentación).

Línea base: el servidor "central" guarda todas las tablas sin distribuir.
Requiere que latency_proxy.py esté en ejecución (los enlaces entre nodos pasan por él).
"""
import csv
import json
import os
import re
import time
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "datos" / "csv"

NODOS = {"CUS": 5431, "APU": 5432, "MDD": 5433}
CENTRAL = 5440
# Puerto del proxy que usa el nodo <desde> para llegar al nodo <hacia>
ENLACE = {
    ("APU", "CUS"): 6132, ("CUS", "APU"): 6231,
    ("MDD", "CUS"): 6133, ("CUS", "MDD"): 6331,
    ("MDD", "APU"): 6233, ("APU", "MDD"): 6332,
}
# ------------------------------------------------------------------ topología
# Laboratorio (por defecto): 4 servidores en esta máquina y enlaces por el proxy.
# AWS u otra red: BDD_CONFIG=aws/nodos.json  (IP pública de cada nodo y contraseña);
# la base central se crea como la base "central" dentro del servidor de Cusco.
BDD_CONFIG = os.environ.get("BDD_CONFIG")
if BDD_CONFIG:
    _cfg = json.load(open(BDD_CONFIG))
    IP = _cfg["ip"]
    PUERTO = {r: int(_cfg.get("puerto", {}).get(r, 5432)) for r in IP}
    PASSWORD = _cfg["password"]
    if not re.fullmatch(r"[A-Za-z0-9]{8,}", PASSWORD):
        raise SystemExit("La contraseña de nodos.json debe tener al menos 8 letras o números")
    DESDE = _cfg.get("ejecutar_desde", "CUS")
    # El script se conecta a su propio nodo por 127.0.0.1 y a los demás por su IP pública
    SERVIDOR = {r: ("127.0.0.1" if r == DESDE else IP[r], PUERTO[r]) for r in NODOS}
    SERVIDOR["CENTRAL"] = SERVIDOR["CUS"]
    BD_CENTRAL = _cfg.get("central_db", "central")

    def enlace(desde, hacia):
        return IP[hacia], PUERTO[hacia]
else:
    PASSWORD = None
    SERVIDOR = {r: ("127.0.0.1", p) for r, p in NODOS.items()}
    SERVIDOR["CENTRAL"] = ("127.0.0.1", CENTRAL)
    BD_CENTRAL = "referencias"

    def enlace(desde, hacia):
        return "127.0.0.1", ENLACE[(desde, hacia)]


def conninfo(desde, hacia):
    h, p = enlace(desde, hacia)
    extra = f" password={PASSWORD}" if PASSWORD else ""
    return f"host={h} port={p} user=postgres dbname=referencias{extra}"


SERVICIOS = ["MEDICINA", "CIRUGIA", "GINECO-OBSTETRICIA", "PEDIATRIA", "UCI"]
CAMAS_INICIALES = 100_000  # holgura para que los experimentos no agoten camas

COLS_REF = """
    id_ref          uuid        NOT NULL,
    paciente_pseudo uuid        NOT NULL,
    edad            smallint    CHECK (edad BETWEEN 0 AND 120),
    sexo            char(1)     CHECK (sexo IN ('F','M')),
    eess_origen     int         NOT NULL,
    eess_destino    int         NOT NULL,
    region_origen   char(3)     NOT NULL,
    region_destino  char(3)     NOT NULL,
    nivel_destino   smallint    NOT NULL,
    cie10           varchar(6)  NOT NULL,
    prioridad       text        NOT NULL,
    estado          text        NOT NULL CHECK (estado IN
                    ('ENVIADA','ACEPTADA','RECHAZADA','CONTRARREFERIDA')),
    fecha_envio     timestamptz NOT NULL DEFAULT now(),
    fecha_respuesta timestamptz
"""
COLS_CREF = """
    id_cref       uuid        NOT NULL,
    id_ref        uuid        NOT NULL,
    region_origen char(3)     NOT NULL,
    fecha         timestamptz NOT NULL DEFAULT now(),
    indicaciones  text
"""

TABLAS_COMUNES = """
CREATE TABLE establecimiento (
    id_eess int PRIMARY KEY,
    nombre  text NOT NULL,
    nivel   smallint NOT NULL CHECK (nivel IN (1,2,3)),
    region  char(3) NOT NULL
);
CREATE TABLE cupo (
    id_eess      int  NOT NULL,
    servicio     text NOT NULL,
    camas_libres int  NOT NULL CHECK (camas_libres >= 0),
    PRIMARY KEY (id_eess, servicio)
);
CREATE TABLE reserva_cupo (
    id_ref   uuid PRIMARY KEY,
    id_eess  int  NOT NULL,
    servicio text NOT NULL,
    fecha    timestamptz NOT NULL DEFAULT now()
);
-- Bitácora del coordinador 2PC (decisiones tomadas), para recuperar transacciones dudosas
CREATE TABLE log_2pc (
    gid      text PRIMARY KEY,
    decision text NOT NULL CHECK (decision IN ('COMMIT','ABORT')),
    fecha    timestamptz NOT NULL DEFAULT now()
);
-- Reserva de cama sin confirmar: la usa el participante de destino dentro de una 2PC
CREATE FUNCTION reservar_cama(p_ref uuid, p_eess int, p_serv text) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  UPDATE cupo SET camas_libres = camas_libres - 1
   WHERE id_eess = p_eess AND servicio = p_serv AND camas_libres > 0;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n = 0 THEN RETURN false; END IF;
  INSERT INTO reserva_cupo(id_ref, id_eess, servicio) VALUES (p_ref, p_eess, p_serv);
  RETURN true;
END $$;
"""

# Aceptación cuando la referencia y la cama están en el mismo servidor (1 ida y vuelta)
FUNC_ACEPTAR_LOCAL = """
CREATE FUNCTION aceptar_local(p_ref uuid, p_eess int, p_serv text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  IF NOT reservar_cama(p_ref, p_eess, p_serv) THEN RETURN 'SIN_CAMA'; END IF;
  UPDATE {tabla} SET estado = 'ACEPTADA', fecha_respuesta = now()
   WHERE id_ref = p_ref AND estado = 'ENVIADA';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n = 0 THEN RAISE EXCEPTION 'REFERENCIA_NO_PENDIENTE'; END IF;
  RETURN 'ACEPTADA';
END $$;
"""

# Contrarreferencia: se guarda junto a su referencia (fragmentación derivada)
FUNC_CONTRARREFERIR = """
CREATE FUNCTION contrarreferir(p_ref uuid, p_region char(3), p_texto text) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  INSERT INTO {tabla_cref}(id_cref, id_ref, region_origen, indicaciones)
  VALUES (gen_random_uuid(), p_ref, p_region, p_texto);
  UPDATE {tabla_ref} SET estado = 'CONTRARREFERIDA'
   WHERE id_ref = p_ref AND region_origen = p_region AND estado = 'ACEPTADA';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n = 0 THEN RAISE EXCEPTION 'REFERENCIA_NO_ACEPTADA'; END IF;
  RETURN 'CONTRARREFERIDA';
END $$;
"""


def conectar(nodo, dbname="postgres"):
    """nodo: 'CUS', 'APU', 'MDD' o 'CENTRAL'."""
    host, port = SERVIDOR[nodo]
    c = psycopg2.connect(host=host, port=port, user="postgres", dbname=dbname,
                         password=PASSWORD, connect_timeout=10)
    c.autocommit = True
    return c


def recrear_bd(nodo, dbname="referencias"):
    c = conectar(nodo)
    cur = c.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)")
    cur.execute(f"CREATE DATABASE {dbname}")
    c.close()
    return conectar(nodo, dbname)


def copiar(cur, tabla, filas, columnas):
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    for f in filas:
        w.writerow([None if v == "" else v for v in f])
    buf.seek(0)
    cur.copy_expert(f"COPY {tabla} ({columnas}) FROM STDIN WITH (FORMAT csv)", buf)


def leer(nombre):
    with open(CSV / nombre) as f:
        return list(csv.reader(f))


REF_COLS = ("id_ref,paciente_pseudo,edad,sexo,eess_origen,eess_destino,region_origen,"
            "region_destino,nivel_destino,cie10,prioridad,estado,fecha_envio,fecha_respuesta")
CREF_COLS = "id_cref,id_ref,region_origen,fecha,indicaciones"


def limpiar_replicacion():
    """Borra suscripciones y slots de despliegues anteriores."""
    for reg in NODOS:
        try:
            c = conectar(reg, "referencias")
            cur = c.cursor()
            cur.execute("SELECT subname FROM pg_subscription")
            for (s,) in cur.fetchall():
                cur.execute(f"ALTER SUBSCRIPTION {s} DISABLE")
                cur.execute(f"ALTER SUBSCRIPTION {s} SET (slot_name = NONE)")
                cur.execute(f"DROP SUBSCRIPTION {s}")
            c.close()
        except psycopg2.OperationalError:
            pass
    for reg in NODOS:
        c = conectar(reg)
        cur = c.cursor()
        cur.execute("SELECT slot_name, active_pid FROM pg_replication_slots")
        for s, pid in cur.fetchall():
            if pid:  # walsender aún conectado: terminarlo antes de borrar el slot
                cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
            for _ in range(20):
                try:
                    cur.execute("SELECT pg_drop_replication_slot(%s)", (s,))
                    break
                except psycopg2.errors.ObjectInUse:
                    time.sleep(0.5)
        c.close()


def desplegar_nodos(est, refs, crefs):
    conns = {}
    for reg in NODOS:
        conns[reg] = recrear_bd(reg)

    for reg, c in conns.items():
        cur = c.cursor()
        r = reg.lower()
        cur.execute("CREATE EXTENSION postgres_fdw")
        cur.execute(TABLAS_COMUNES)
        # Fragmentos propios: un esquema por región
        cur.execute(f"CREATE SCHEMA {r}")
        cur.execute(f"""CREATE TABLE {r}.referencia ({COLS_REF},
                        PRIMARY KEY (id_ref), CHECK (region_origen = '{reg}'))""")
        cur.execute(f"""CREATE TABLE {r}.contrarreferencia ({COLS_CREF},
                        PRIMARY KEY (id_cref),
                        FOREIGN KEY (id_ref) REFERENCES {r}.referencia(id_ref),
                        CHECK (region_origen = '{reg}'))""")
        cur.execute(f"CREATE INDEX ON {r}.referencia (eess_destino, estado)")
        cur.execute(f"CREATE INDEX ON {r}.referencia (region_destino, estado)")
        cur.execute(f"CREATE INDEX ON {r}.contrarreferencia (id_ref)")
        # La replicación con filtro de filas necesita identidad de réplica completa
        cur.execute(f"ALTER TABLE {r}.referencia REPLICA IDENTITY FULL")
        # Datos de la región
        copiar(cur, f"{r}.referencia", [x for x in refs if x[6] == reg], REF_COLS)
        copiar(cur, f"{r}.contrarreferencia", [x for x in crefs if x[2] == reg], CREF_COLS)
        # Camas: solo de los hospitales (nivel II y III) de la región
        for e in est:
            if e[3] == reg and int(e[2]) >= 2:
                for s in SERVICIOS:
                    cur.execute("INSERT INTO cupo VALUES (%s,%s,%s)", (int(e[0]), s, CAMAS_INICIALES))
        cur.execute(FUNC_ACEPTAR_LOCAL.format(tabla=f"{r}.referencia"))
        cur.execute(f"ANALYZE")

    # Catálogo: copia maestra en Cusco
    cur = conns["CUS"].cursor()
    copiar(cur, "establecimiento", est, "id_eess,nombre,nivel,region")
    cur.execute("CREATE PUBLICATION pub_catalogo FOR TABLE establecimiento")
    # Apurímac y Madre de Dios publican lo que envían a Cusco (filtro de filas)
    for reg in ("APU", "MDD"):
        r = reg.lower()
        conns[reg].cursor().execute(
            f"CREATE PUBLICATION pub_hacia_cus FOR TABLE {r}.referencia "
            f"WHERE (region_destino = 'CUS')")

    # Servidores remotos (postgres_fdw), tablas foráneas y tablas particionadas globales
    for reg, c in conns.items():
        cur = c.cursor()
        for otro in NODOS:
            if otro == reg:
                continue
            o = otro.lower()
            # async_capable: las particiones remotas se leen en paralelo
            h, p = enlace(reg, otro)
            cur.execute(f"""CREATE SERVER srv_{o} FOREIGN DATA WRAPPER postgres_fdw
                            OPTIONS (host '{h}', port '{p}',
                                     dbname 'referencias', fetch_size '500',
                                     async_capable 'true')""")
            if PASSWORD:
                cur.execute(f"CREATE USER MAPPING FOR postgres SERVER srv_{o} "
                            "OPTIONS (user 'postgres', password %s)", (PASSWORD,))
            else:
                cur.execute(f"CREATE USER MAPPING FOR postgres SERVER srv_{o} OPTIONS (user 'postgres')")
            cur.execute(f"CREATE SCHEMA fdw_{o}")
        cur.execute(f"CREATE TABLE public.referencia ({COLS_REF}) PARTITION BY LIST (region_origen)")
        cur.execute(f"CREATE TABLE public.contrarreferencia ({COLS_CREF}) PARTITION BY LIST (region_origen)")
        for otro in NODOS:
            o = otro.lower()
            if otro == reg:
                cur.execute(f"ALTER TABLE public.referencia ATTACH PARTITION {o}.referencia FOR VALUES IN ('{otro}')")
                cur.execute(f"ALTER TABLE public.contrarreferencia ATTACH PARTITION {o}.contrarreferencia FOR VALUES IN ('{otro}')")
            else:
                cur.execute(f"""CREATE FOREIGN TABLE fdw_{o}.referencia
                                PARTITION OF public.referencia FOR VALUES IN ('{otro}')
                                SERVER srv_{o} OPTIONS (schema_name '{o}', table_name 'referencia')""")
                cur.execute(f"""CREATE FOREIGN TABLE fdw_{o}.contrarreferencia
                                PARTITION OF public.contrarreferencia FOR VALUES IN ('{otro}')
                                SERVER srv_{o} OPTIONS (schema_name '{o}', table_name 'contrarreferencia')""")
        cur.execute(FUNC_CONTRARREFERIR.format(tabla_cref="public.contrarreferencia",
                                               tabla_ref="public.referencia"))

    # Suscripciones al catálogo (Apurímac y Madre de Dios leen la copia maestra de Cusco)
    for reg in ("APU", "MDD"):
        conns[reg].cursor().execute(
            f"CREATE SUBSCRIPTION sub_catalogo_{reg.lower()} CONNECTION %s "
            "PUBLICATION pub_catalogo", (conninfo(reg, "CUS"),))

    # Réplica en Cusco de las referencias que le llegan (solo lectura)
    cur = conns["CUS"].cursor()
    for reg in ("APU", "MDD"):
        r = reg.lower()
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {r}")
        cur.execute(f"CREATE TABLE {r}.referencia ({COLS_REF}, PRIMARY KEY (id_ref))")
        cur.execute(f"ALTER TABLE {r}.referencia REPLICA IDENTITY FULL")
        cur.execute(f"CREATE INDEX ON {r}.referencia (estado)")
        cur.execute(f"CREATE SUBSCRIPTION sub_desde_{r} CONNECTION %s "
                    "PUBLICATION pub_hacia_cus", (conninfo("CUS", reg),))
    # Bandeja de entrada de Cusco: todo lo pendiente dirigido a sus hospitales, leído localmente
    cur.execute("""CREATE VIEW bandeja_cus AS
                     SELECT * FROM cus.referencia WHERE region_destino = 'CUS'
                     UNION ALL SELECT * FROM apu.referencia
                     UNION ALL SELECT * FROM mdd.referencia""")
    return conns


def desplegar_central(est, refs, crefs):
    c = recrear_bd("CENTRAL", BD_CENTRAL)
    cur = c.cursor()
    cur.execute(TABLAS_COMUNES)
    cur.execute(f"CREATE TABLE referencia ({COLS_REF}, PRIMARY KEY (id_ref))")
    cur.execute(f"""CREATE TABLE contrarreferencia ({COLS_CREF}, PRIMARY KEY (id_cref),
                    FOREIGN KEY (id_ref) REFERENCES referencia(id_ref))""")
    cur.execute("CREATE INDEX ON referencia (eess_destino, estado)")
    cur.execute("CREATE INDEX ON referencia (region_destino, estado)")
    cur.execute("CREATE INDEX ON contrarreferencia (id_ref)")
    copiar(cur, "establecimiento", est, "id_eess,nombre,nivel,region")
    copiar(cur, "referencia", refs, REF_COLS)
    copiar(cur, "contrarreferencia", crefs, CREF_COLS)
    for e in est:
        if int(e[2]) >= 2:
            for s in SERVICIOS:
                cur.execute("INSERT INTO cupo VALUES (%s,%s,%s)", (int(e[0]), s, CAMAS_INICIALES))
    cur.execute(FUNC_ACEPTAR_LOCAL.format(tabla="referencia"))
    cur.execute(FUNC_CONTRARREFERIR.format(tabla_cref="contrarreferencia", tabla_ref="referencia"))
    cur.execute("ANALYZE")
    return c


def esperar_sincronizacion(conns, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        pend = 0
        for reg, c in conns.items():
            cur = c.cursor()
            cur.execute("SELECT count(*) FROM pg_subscription_rel WHERE srsubstate <> 'r'")
            pend += cur.fetchone()[0]
        if pend == 0:
            return time.time() - t0
        time.sleep(1)
    raise RuntimeError("la sincronización inicial no terminó")


if __name__ == "__main__":
    est, refs, crefs = leer("establecimiento.csv"), leer("referencia.csv"), leer("contrarreferencia.csv")
    limpiar_replicacion()
    conns = desplegar_nodos(est, refs, crefs)
    desplegar_central(est, refs, crefs)
    seg = esperar_sincronizacion(conns)
    print(f"despliegue completo; sincronización inicial de réplicas en {seg:.1f} s")
