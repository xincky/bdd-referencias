#!/usr/bin/env python3
"""Convierte resultados/resultados.json en tablas Markdown (resultados/tablas.md)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = json.loads((ROOT / "resultados" / "resultados.json").read_text())
RTTS = R["rtts_ms"]

OPS = [
    ("E1_registrar", "Registrar referencia nivel I→II (Abancay)"),
    ("E1_bandeja", "Bandeja del hospital de Abancay"),
    ("E1_aceptar", "Aceptar referencia nivel I→II (Abancay)"),
]
E2 = [
    ("E2_aceptar_bdd_2pc", "E2_aceptar_central", "Aceptar referencia Apurímac→Cusco"),
    ("E2_bandeja_global_bdd_replica", "E2_bandeja_global_central", "Bandeja de Cusco (réplica local)"),
    ("E2_bandeja_global_bdd_fdw", "E2_bandeja_global_central", "Bandeja de Cusco (lectura remota FDW)"),
    ("E2_contrarreferir_bdd", "E2_contrarreferir_central", "Contrarreferencia Cusco→Apurímac"),
]


def f(x):
    return f"{x:,.1f}".replace(",", " ") if x >= 10 else f"{x:.2f}"


lineas = ["# Resultados (mediana p50 y percentil 95, en ms)", ""]
cab = "| Operación | Diseño | " + " | ".join(f"RTT {r} ms" for r in RTTS) + " |"
lineas += [cab, "|" + " --- |" * (2 + len(RTTS))]
for k, nombre in OPS:
    for d, et in (("bdd", "BDD"), ("central", "Centralizada")):
        celdas = [f"{f(R[f'E1E2_rtt{r}'][f'{k}_{d}']['p50'])} ({f(R[f'E1E2_rtt{r}'][f'{k}_{d}']['p95'])})" for r in RTTS]
        lineas.append(f"| {nombre} | {et} | " + " | ".join(celdas) + " |")
for kb, kc, nombre in E2:
    for k, et in ((kb, "BDD"), (kc, "Centralizada")):
        celdas = [f"{f(R[f'E1E2_rtt{r}'][k]['p50'])} ({f(R[f'E1E2_rtt{r}'][k]['p95'])})" for r in RTTS]
        lineas.append(f"| {nombre} | {et} | " + " | ".join(celdas) + " |")

lineas += ["", "## RTT medido a través del proxy (SELECT 1)", ""]
lineas += ["| RTT de diseño | p50 medido |", "| --- | --- |"]
for r in RTTS:
    lineas.append(f"| {r} ms | {f(R[f'E1E2_rtt{r}']['ping_wan']['p50'])} ms |")

lineas += ["", "## Idas y vueltas equivalentes (p50 / RTT medido)", ""]
for r in RTTS:
    ping = R[f"E1E2_rtt{r}"]["ping_wan"]["p50"]
    partes = []
    for k in ("E2_aceptar_bdd_2pc", "E2_bandeja_global_bdd_fdw", "E2_contrarreferir_bdd", "E1_registrar_central"):
        partes.append(f"{k}={R[f'E1E2_rtt{r}'][k]['p50'] / ping:.2f}")
    lineas.append(f"- RTT {r}: " + ", ".join(partes))

lineas += ["", "## Retardo de la replicación asíncrona (p50 / p95, ms)", ""]
lineas += ["| RTT | Catálogo Cusco→Apurímac | Referencia Apurímac→Cusco |", "| --- | --- | --- |"]
for r in RTTS:
    e = R[f"E6_rtt{r}"]
    lineas.append(f"| {r} ms | {f(e['catalogo_cus_a_apu']['p50'])} / {f(e['catalogo_cus_a_apu']['p95'])} | "
                  f"{f(e['referencia_apu_a_cus']['p50'])} / {f(e['referencia_apu_a_cus']['p95'])} |")

for clave in ("E0", "E3", "E4", "E5"):
    lineas += ["", f"## {clave}", "", "```json", json.dumps(R.get(clave), indent=2, ensure_ascii=False), "```"]

(ROOT / "resultados" / "tablas.md").write_text("\n".join(lineas) + "\n")
print("\n".join(lineas))
