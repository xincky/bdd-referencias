#!/usr/bin/env python3
"""Genera datos sintéticos y realistas para el prototipo (semilla fija = reproducible).

No contiene datos personales reales: cada paciente se identifica con un seudónimo
(UUID aleatorio) y solo se guardan edad y sexo, conforme a la Ley N.º 29733.

Supuestos de diseño (no son estadísticas oficiales):
  * Volumen proporcional a la población de cada región (INEI, Censos 2025):
    Cusco 1 379 mil, Apurímac 467 mil, Madre de Dios 209 mil  ->  67 % / 23 % / 10 %.
  * 85 % de las referencias son de nivel I a nivel II dentro de la misma región y
    15 % son de nivel II a nivel III (hospitales de Cusco).
  * Estados del histórico: 70 % contrarreferida, 20 % aceptada, 5 % rechazada,
    5 % enviada (pendiente).
Cuatro nombres de hospitales provienen del ASISHO 2023 del Hospital Regional del
Cusco; el Hospital Antonio Lorena se toma del informe de avance y el sexto hospital
es sintético. El nivel sigue el modelo simplificado del caso (nivel III en Cusco y
nivel II en las demás regiones). Los centros de salud de nivel I son ficticios.
"""
import csv
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

SEED = 2026
TOTAL_REFERENCIAS = 30_000
PROPORCION = {"CUS": 0.67, "APU": 0.23, "MDD": 0.10}
N_CS_NIVEL1 = {"CUS": 60, "APU": 40, "MDD": 20}

HOSPITALES = [
    # id, nombre, nivel, región
    (1, "Hospital Regional del Cusco", 3, "CUS"),
    (2, "Hospital Antonio Lorena", 3, "CUS"),
    (3, "Hospital nivel II Cusco (sintético)", 2, "CUS"),
    (4, "Hospital Guillermo Díaz de la Vega (Abancay)", 2, "APU"),
    (5, "Hospital de Andahuaylas", 2, "APU"),
    (6, "Hospital Santa Rosa (Puerto Maldonado)", 2, "MDD"),
]
SERVICIOS = ["MEDICINA", "CIRUGIA", "GINECO-OBSTETRICIA", "PEDIATRIA", "UCI"]
CIE10 = ["J18.9", "K35.8", "S06.9", "O14.1", "I21.9", "N39.0", "A09", "E11.9", "K80.2", "O80"]
PRIORIDAD = [("EMERGENCIA", 0.35), ("URGENCIA", 0.25), ("ELECTIVA", 0.40)]
ESTADOS = [("CONTRARREFERIDA", 0.70), ("ACEPTADA", 0.20), ("RECHAZADA", 0.05), ("ENVIADA", 0.05)]


def elegir(rng, pares):
    r, acum = rng.random(), 0.0
    for valor, p in pares:
        acum += p
        if r <= acum:
            return valor
    return pares[-1][0]


def establecimientos():
    filas = [list(h) for h in HOSPITALES]
    nid = 100
    for reg, n in N_CS_NIVEL1.items():
        for i in range(1, n + 1):
            filas.append([nid, f"C.S. {reg}-{i:03d} (sintético)", 1, reg])
            nid += 1
    return filas


def generar(salida: Path):
    rng = random.Random(SEED)
    uuid_rng = random.Random(SEED + 1)

    def nuevo_uuid():
        return str(uuid.UUID(int=uuid_rng.getrandbits(128), version=4))

    est = establecimientos()
    cs = {r: [e for e in est if e[2] == 1 and e[3] == r] for r in N_CS_NIVEL1}
    nivel2 = {r: [e for e in est if e[2] == 2 and e[3] == r] for r in N_CS_NIVEL1}
    nivel3 = [e for e in est if e[2] == 3]

    inicio = datetime(2025, 1, 1)
    referencias, contrarreferencias = [], []
    for reg, prop in PROPORCION.items():
        for _ in range(int(TOTAL_REFERENCIAS * prop)):
            if rng.random() < 0.85:      # nivel I -> nivel II (misma región)
                origen, destino = rng.choice(cs[reg]), rng.choice(nivel2[reg])
            else:                         # nivel II -> nivel III (Cusco)
                origen, destino = rng.choice(nivel2[reg]), rng.choice(nivel3)
            estado = elegir(rng, ESTADOS)
            envio = inicio + timedelta(minutes=rng.randint(0, 60 * 24 * 680))
            resp = envio + timedelta(hours=rng.randint(1, 72)) if estado != "ENVIADA" else None
            ref = [
                nuevo_uuid(), nuevo_uuid(),             # id_ref, paciente (seudónimo)
                rng.randint(0, 95), rng.choice("FM"),   # edad, sexo
                origen[0], destino[0], origen[3], destino[3], destino[2],
                rng.choice(CIE10), elegir(rng, PRIORIDAD), estado,
                envio.isoformat(), resp.isoformat() if resp else "",
            ]
            referencias.append(ref)
            if estado == "CONTRARREFERIDA":
                contrarreferencias.append([
                    nuevo_uuid(), ref[0], reg,
                    (resp + timedelta(days=rng.randint(1, 10))).isoformat(),
                    "Alta con indicaciones de control en el establecimiento de origen",
                ])

    salida.mkdir(parents=True, exist_ok=True)
    with open(salida / "establecimiento.csv", "w", newline="") as f:
        csv.writer(f).writerows(est)
    with open(salida / "referencia.csv", "w", newline="") as f:
        csv.writer(f).writerows(referencias)
    with open(salida / "contrarreferencia.csv", "w", newline="") as f:
        csv.writer(f).writerows(contrarreferencias)
    print(f"establecimientos={len(est)} referencias={len(referencias)} "
          f"contrarreferencias={len(contrarreferencias)}")


if __name__ == "__main__":
    generar(Path(__file__).resolve().parent / "csv")
