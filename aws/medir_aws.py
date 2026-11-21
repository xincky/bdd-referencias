#!/usr/bin/env python3
"""Semana 7 en AWS: datos cargados y primeras consultas con la latencia real.

Cada consulta se mide desde la región del usuario que la hace:
  en n_cus:  python3 aws/medir_aws.py --desde CUS
      conteos por nodo, verificación E0, bandeja de Cusco (réplica local, FDW y central)
  en n_apu:  python3 aws/medir_aws.py --desde APU
      bandeja del hospital de Abancay (nodo propio y central en Cusco)
Ambos miden también el RTT real hacia los otros nodos (SELECT 1).
Escribe resultados/aws/<desde>.json y <desde>.md.
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

from config import CFG, REGIONES, conectar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experimentos"))
from semana7_demo import Q_ABANCAY, Q_CUSCO_FDW, Q_CUSCO_REP  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "resultados" / "aws"
OUT.mkdir(parents=True, exist_ok=True)
N = int(os.environ.get("N_OPS", 50))


def resumen(ms):
    ms = sorted(ms)
    p = lambda q: ms[min(len(ms) - 1, int(round(q * (len(ms) - 1))))]
    return {"n": len(ms), "p50": round(p(0.50), 2), "p95": round(p(0.95), 2),
            "media": round(statistics.mean(ms), 2)}


def medir(c, sql, n=N, warmup=5):
    cur = c.cursor()
    for _ in range(warmup):
        cur.execute(sql)
        cur.fetchall()
    out = []
    for _ in range(n):
        t = time.perf_counter()
        cur.execute(sql)
        cur.fetchall()
        out.append((time.perf_counter() - t) * 1000)
    return resumen(out)


def uno(c, sql):
    cur = c.cursor()
    cur.execute(sql)
    return cur.fetchone()


def plan(c, sql, opciones="COSTS OFF"):
    cur = c.cursor()
    cur.execute(f"EXPLAIN ({opciones}) {sql}")
    return "\n".join(r[0] for r in cur.fetchall())


def carga(desde):
    nodos = {r: conectar(r, desde) for r in REGIONES}
    cen = conectar("CENTRAL", desde)
    conteos = {}
    for r, c in nodos.items():
        e = r.lower()
        conteos[r] = dict(zip(("establecimiento", "referencia", "contrarreferencia", "cupo"), uno(
            c, f"""SELECT (SELECT count(*) FROM establecimiento), (SELECT count(*) FROM {e}.referencia),
                          (SELECT count(*) FROM {e}.contrarreferencia), (SELECT count(*) FROM cupo)""")))
    conteos["CENTRAL"] = dict(zip(("establecimiento", "referencia", "contrarreferencia", "cupo"), uno(
        cen, """SELECT (SELECT count(*) FROM establecimiento), (SELECT count(*) FROM referencia),
                       (SELECT count(*) FROM contrarreferencia), (SELECT count(*) FROM cupo)""")))
    firma = ("SELECT md5(string_agg(id_ref::text || estado || eess_destino, ',' "
             "ORDER BY id_ref)) FROM referencia")
    total, dup = uno(nodos["CUS"], "SELECT count(*), count(*) - count(DISTINCT id_ref) FROM referencia")
    huerfanas = sum(uno(c, f"""SELECT count(*) FROM {r.lower()}.contrarreferencia cr
                               LEFT JOIN {r.lower()}.referencia rf USING (id_ref)
                               WHERE rf.id_ref IS NULL""")[0] for r, c in nodos.items())
    e0 = {"suma_fragmentos": sum(conteos[r]["referencia"] for r in REGIONES),
          "total_global": total, "total_central": conteos["CENTRAL"]["referencia"],
          "filas_duplicadas": dup,
          "reconstruccion_identica": uno(nodos["CUS"], firma)[0] == uno(cen, firma)[0],
          "contrarreferencias_fuera_de_su_nodo": huerfanas}
    for c in list(nodos.values()) + [cen]:
        c.close()
    return conteos, e0


def rtt(desde):
    out = {}
    for r in REGIONES:
        if r != desde:
            c = conectar(r, desde, "postgres")
            out[f"rtt_{desde}_{r}"] = medir(c, "SELECT 1")
            c.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", required=True, choices=("CUS", "APU"))
    desde = ap.parse_args().desde
    res = {"desde": desde, "N_ops": N, "ip": CFG["ip"], "fecha": time.strftime("%Y-%m-%d %H:%M")}
    res["rtt"] = rtt(desde)
    if desde == "CUS":
        res["conteos"], res["E0"] = carga(desde)
        cus, cen = conectar("CUS", desde), conectar("CENTRAL", desde)
        res["planes"] = {"cusco_fdw": plan(cus, Q_CUSCO_FDW, "VERBOSE, COSTS OFF"),
                         "cusco_replica": plan(cus, Q_CUSCO_REP)}
        res["tiempos"] = {"cusco_replica": medir(cus, Q_CUSCO_REP),
                          "cusco_fdw": medir(cus, Q_CUSCO_FDW),
                          "cusco_central": medir(cen, Q_CUSCO_FDW)}
    else:
        apu, cen = conectar("APU", desde), conectar("CENTRAL", desde)
        res["planes"] = {"abancay_bdd": plan(apu, Q_ABANCAY, "VERBOSE, COSTS OFF")}
        res["tiempos"] = {"abancay_bdd": medir(apu, Q_ABANCAY),
                          "abancay_central": medir(cen, Q_ABANCAY)}

    (OUT / f"{desde}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    md = [f"# Semana 7 en AWS, medido desde {desde} ({res['fecha']})", "",
          "| Medición | p50 ms | p95 ms |", "| --- | --- | --- |"]
    for k, v in {**res["rtt"], **res["tiempos"]}.items():
        md.append(f"| {k} | {v['p50']} | {v['p95']} |")
    if "E0" in res:
        md += ["", "Conteos: " + json.dumps(res["conteos"], ensure_ascii=False),
               "E0: " + json.dumps(res["E0"], ensure_ascii=False)]
    (OUT / f"{desde}.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
