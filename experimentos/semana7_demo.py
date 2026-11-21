#!/usr/bin/env python3
"""Semana 7: datos cargados y primeras consultas (solo lectura, se puede repetir).

1. Conteos por nodo y por fragmento, y verificación de la fragmentación (E0).
2. Planes de ejecución (EXPLAIN) de las dos bandejas: Abancay (local) y Cusco
   (réplica local o lectura remota por postgres_fdw).
3. Tiempos de las primeras consultas: BDD frente a la base central, con el
   enlace simulado a 20, 50 y 100 ms (N_OPS consultas por medición).

Uso: con los servidores iniciados y deploy.py ejecutado:
    python3 experimentos/semana7_demo.py
Escribe resultados/semana7/{carga.txt, explain_*.txt, tiempos.json, tiempos.md}.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import (HOSP_ABANCAY, conn, detener_proxy, iniciar_proxy,  # noqa: E402
                             medir, resumen)

OUT = Path(__file__).resolve().parents[1] / "resultados" / "semana7"
OUT.mkdir(parents=True, exist_ok=True)
N = int(os.environ.get("N_OPS", 50))
RTTS = [int(x) for x in os.environ.get("RTTS", "20,50,100").split(",")]

Q_ABANCAY = """SELECT id_ref, cie10, prioridad, edad, sexo, fecha_envio FROM referencia
 WHERE region_origen = 'APU' AND eess_destino = {h} AND estado = 'ENVIADA'
 ORDER BY fecha_envio LIMIT 50""".format(h=HOSP_ABANCAY)
Q_CUSCO = """SELECT id_ref, region_origen, cie10, prioridad, fecha_envio FROM {t}
 WHERE {w}estado = 'ENVIADA' ORDER BY fecha_envio LIMIT 100"""
Q_CUSCO_FDW = Q_CUSCO.format(t="referencia", w="region_destino = 'CUS' AND ")
Q_CUSCO_REP = Q_CUSCO.format(t="bandeja_cus", w="")


def uno(c, sql):
    cur = c.cursor()
    cur.execute(sql)
    return cur.fetchone()


def todas(c, sql):
    cur = c.cursor()
    cur.execute(sql)
    return cur.fetchall()


def carga():
    cus, apu, mdd, cen = conn(5431), conn(5432), conn(5433), conn(5440)
    nodos = {"Cusco": (cus, "cus"), "Apurímac": (apu, "apu"), "Madre de Dios": (mdd, "mdd")}
    lineas = ["Datos cargados (conteo por nodo)", ""]
    lineas.append(f"{'Nodo':<15}{'establecimiento':>17}{'referencia (fragmento)':>24}"
                  f"{'contrarreferencia':>19}{'cupo':>7}")
    filas = {}
    for nombre, (c, r) in nodos.items():
        est = uno(c, "SELECT count(*) FROM establecimiento")[0]
        ref = uno(c, f"SELECT count(*) FROM {r}.referencia")[0]
        cre = uno(c, f"SELECT count(*) FROM {r}.contrarreferencia")[0]
        cup = uno(c, "SELECT count(*) FROM cupo")[0]
        filas[nombre] = dict(establecimiento=est, referencia=ref, contrarreferencia=cre, cupo=cup)
        lineas.append(f"{nombre:<15}{est:>17}{ref:>24}{cre:>19}{cup:>7}")
    est = uno(cen, "SELECT count(*) FROM establecimiento")[0]
    ref = uno(cen, "SELECT count(*) FROM referencia")[0]
    cre = uno(cen, "SELECT count(*) FROM contrarreferencia")[0]
    cup = uno(cen, "SELECT count(*) FROM cupo")[0]
    filas["Central"] = dict(establecimiento=est, referencia=ref, contrarreferencia=cre, cupo=cup)
    lineas.append(f"{'Central':<15}{est:>17}{ref:>24}{cre:>19}{cup:>7}")

    # Transparencia: desde el nodo Apurímac, una sola tabla con las tres regiones
    por_region = todas(apu, "SELECT region_origen, count(*) FROM referencia GROUP BY 1 ORDER BY 1")
    lineas += ["", "Desde el nodo Apurímac: SELECT region_origen, count(*) FROM referencia GROUP BY 1"]
    lineas += [f"  {r}: {n}" for r, n in por_region]

    # E0: reglas de la fragmentación
    total, dup = uno(cus, "SELECT count(*), count(*) - count(DISTINCT id_ref) FROM referencia")
    firma = ("SELECT md5(string_agg(id_ref::text || estado || eess_destino, ',' "
             "ORDER BY id_ref)) FROM referencia")
    iguales = uno(cus, firma)[0] == uno(cen, firma)[0]
    huerfanas = sum(uno(c, f"""SELECT count(*) FROM {r}.contrarreferencia cr
                               LEFT JOIN {r}.referencia rf USING (id_ref)
                               WHERE rf.id_ref IS NULL""")[0] for c, r in nodos.values())
    suma = sum(f["referencia"] for k, f in filas.items() if k != "Central")
    e0 = dict(suma_fragmentos=suma, total_global=total, total_central=filas["Central"]["referencia"],
              filas_duplicadas=dup, reconstruccion_identica=iguales,
              contrarreferencias_fuera_de_su_nodo=huerfanas, por_region=dict(por_region))
    lineas += ["", "Verificación de la fragmentación (E0)",
               f"  Completitud: suma de fragmentos = {suma}; central = {e0['total_central']}",
               f"  Disyunción: filas duplicadas = {dup}",
               f"  Reconstrucción: firma md5 de la unión = firma de la central -> {iguales}",
               f"  Fragmentación derivada: contrarreferencias fuera de su nodo = {huerfanas}"]
    (OUT / "carga.txt").write_text("\n".join(lineas) + "\n")
    for c in (cus, apu, mdd, cen):
        c.close()
    return {"conteos": filas, "E0": e0}


def planes():
    cus, apu = conn(5431), conn(5432)
    out = {}
    for nombre, c, sql, opciones in (
            ("abancay_bdd", apu, Q_ABANCAY, "COSTS OFF"),
            ("cusco_fdw", cus, Q_CUSCO_FDW, "VERBOSE, COSTS OFF"),
            ("cusco_replica", cus, Q_CUSCO_REP, "COSTS OFF")):
        plan = "\n".join(r[0] for r in todas(c, f"EXPLAIN ({opciones}) {sql}"))
        (OUT / f"explain_{nombre}.txt").write_text(sql + "\n\n" + plan + "\n")
        out[nombre] = plan
    for c in (cus, apu):
        c.close()
    return out


def tiempos():
    res = {}
    for rtt in RTTS:
        iniciar_proxy(rtt)
        apu, cen_desde_apu, cus, cen = conn(5432), conn(6240), conn(5431), conn(5440)
        r = {"ping_wan": resumen(medir(lambda: uno(cen_desde_apu, "SELECT 1"), n=N))}
        r["abancay_bdd"] = resumen(medir(lambda: todas(apu, Q_ABANCAY), n=N))
        r["abancay_central"] = resumen(medir(lambda: todas(cen_desde_apu, Q_ABANCAY), n=N))
        r["cusco_replica"] = resumen(medir(lambda: todas(cus, Q_CUSCO_REP), n=N))
        r["cusco_fdw"] = resumen(medir(lambda: todas(cus, Q_CUSCO_FDW), n=N))
        r["cusco_central"] = resumen(medir(lambda: todas(cen, Q_CUSCO_FDW), n=N))
        res[f"rtt{rtt}"] = r
        print(f"RTT {rtt} ms:", json.dumps(r), flush=True)
        for c in (apu, cen_desde_apu, cus, cen):
            c.close()
    detener_proxy()
    nombres = {"abancay_bdd": "Bandeja de Abancay · BDD (nodo propio)",
               "abancay_central": "Bandeja de Abancay · central (remota)",
               "cusco_replica": "Bandeja de Cusco · BDD con réplica local",
               "cusco_fdw": "Bandeja de Cusco · BDD leyendo por FDW",
               "cusco_central": "Bandeja de Cusco · central (local)",
               "ping_wan": "SELECT 1 por el enlace (RTT medido)"}
    md = ["# Primeras consultas: mediana p50 (p95), en ms", "",
          "| Consulta | " + " | ".join(f"RTT {r} ms" for r in RTTS) + " |",
          "| --- | " + " | ".join("---" for _ in RTTS) + " |"]
    for k, etiqueta in nombres.items():
        celdas = [f"{res[f'rtt{r}'][k]['p50']} ({res[f'rtt{r}'][k]['p95']})" for r in RTTS]
        md.append(f"| {etiqueta} | " + " | ".join(celdas) + " |")
    md += ["", f"{N} consultas por medición; RTT simulado por el proxy (valores de diseño)."]
    (OUT / "tiempos.md").write_text("\n".join(md) + "\n")
    return res


if __name__ == "__main__":
    iniciar_proxy(20)  # los nodos se consultan entre sí a través del proxy
    resultado = {"N_ops": N, "rtts_ms": RTTS}
    resultado.update(carga())
    print((OUT / "carga.txt").read_text())
    resultado["planes"] = planes()
    resultado["tiempos"] = tiempos()
    with open(OUT / "tiempos.json", "w") as f:
        json.dump(resultado, f, indent=2, ensure_ascii=False)
    print((OUT / "tiempos.md").read_text())
