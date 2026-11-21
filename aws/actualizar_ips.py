#!/usr/bin/env python3
"""Después de detener y volver a encender las instancias, las IP públicas cambian.

1. En la consola de EC2, anota las IP nuevas y cambia las reglas 5432 de los tres
   grupos de seguridad (las IP /32 de los otros dos nodos).
2. Escribe las IP nuevas en aws/nodos.json (en n_cus y, si mides desde allí, en n_apu).
3. En n_cus:  python3 aws/actualizar_ips.py
Actualiza en cada nodo los servidores remotos (postgres_fdw) y las suscripciones de réplica.
"""
from config import CFG, REGIONES, conectar

DESDE = CFG.get("ejecutar_desde", "CUS")


def conninfo(hacia):
    return (f"host={CFG['ip'][hacia]} port={CFG['puerto'][hacia]} user=postgres "
            f"dbname=referencias password={CFG['password']}")


for reg in REGIONES:
    c = conectar(reg, DESDE)
    cur = c.cursor()
    for otro in REGIONES:
        if otro != reg:
            cur.execute(f"ALTER SERVER srv_{otro.lower()} OPTIONS (SET host %s, SET port %s)",
                        (CFG["ip"][otro], str(CFG["puerto"][otro])))
    if reg == "CUS":
        subs = {"sub_desde_apu": "APU", "sub_desde_mdd": "MDD"}
    else:
        subs = {f"sub_catalogo_{reg.lower()}": "CUS"}
    for sub, hacia in subs.items():
        cur.execute(f"ALTER SUBSCRIPTION {sub} CONNECTION %s", (conninfo(hacia),))
    print(f"{reg}: servidores remotos y suscripciones apuntan a las IP nuevas")
    c.close()
