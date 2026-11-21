# Resultados (mediana p50 y percentil 95, en ms)

| Operación | Diseño | RTT 20 ms | RTT 50 ms | RTT 100 ms |
| --- | --- | --- | --- | --- |
| Registrar referencia nivel I→II (Abancay) | BDD | 0.32 (0.45) | 0.33 (0.69) | 0.42 (0.58) |
| Registrar referencia nivel I→II (Abancay) | Centralizada | 22.0 (23.3) | 52.7 (54.4) | 103.5 (105.4) |
| Bandeja del hospital de Abancay | BDD | 0.46 (0.69) | 0.69 (0.95) | 0.64 (0.80) |
| Bandeja del hospital de Abancay | Centralizada | 21.8 (23.0) | 52.5 (54.0) | 103.2 (105.0) |
| Aceptar referencia nivel I→II (Abancay) | BDD | 0.33 (0.62) | 0.46 (1.00) | 0.40 (0.74) |
| Aceptar referencia nivel I→II (Abancay) | Centralizada | 22.0 (23.2) | 52.6 (54.4) | 103.4 (105.2) |
| Aceptar referencia Apurímac→Cusco | BDD | 67.9 (71.0) | 160.3 (163.7) | 310.6 (313.4) |
| Aceptar referencia Apurímac→Cusco | Centralizada | 0.29 (0.43) | 0.35 (0.56) | 0.36 (0.71) |
| Bandeja de Cusco (réplica local) | BDD | 1.19 (1.72) | 1.43 (1.82) | 1.64 (1.87) |
| Bandeja de Cusco (réplica local) | Centralizada | 0.98 (1.52) | 1.19 (1.50) | 1.36 (1.50) |
| Bandeja de Cusco (lectura remota FDW) | BDD | 192.6 (198.8) | 467.0 (472.0) | 922.5 (927.9) |
| Bandeja de Cusco (lectura remota FDW) | Centralizada | 0.98 (1.52) | 1.19 (1.50) | 1.36 (1.50) |
| Contrarreferencia Cusco→Apurímac | BDD | 130.1 (134.2) | 313.0 (317.4) | 615.4 (619.2) |
| Contrarreferencia Cusco→Apurímac | Centralizada | 0.46 (0.72) | 0.28 (0.83) | 0.33 (0.76) |

## RTT medido a través del proxy (SELECT 1)

| RTT de diseño | p50 medido |
| --- | --- |
| 20 ms | 21.2 ms |
| 50 ms | 51.9 ms |
| 100 ms | 102.7 ms |

## Idas y vueltas equivalentes (p50 / RTT medido)

- RTT 20: E2_aceptar_bdd_2pc=3.21, E2_bandeja_global_bdd_fdw=9.10, E2_contrarreferir_bdd=6.15, E1_registrar_central=1.04
- RTT 50: E2_aceptar_bdd_2pc=3.09, E2_bandeja_global_bdd_fdw=8.99, E2_contrarreferir_bdd=6.03, E1_registrar_central=1.02
- RTT 100: E2_aceptar_bdd_2pc=3.03, E2_bandeja_global_bdd_fdw=8.99, E2_contrarreferir_bdd=5.99, E1_registrar_central=1.01

## Retardo de la replicación asíncrona (p50 / p95, ms)

| RTT | Catálogo Cusco→Apurímac | Referencia Apurímac→Cusco |
| --- | --- | --- |
| 20 ms | 12.9 / 14.4 | 13.1 / 15.8 |
| 50 ms | 28.6 / 29.5 | 28.5 / 31.0 |
| 100 ms | 53.4 / 56.4 | 54.1 / 55.9 |

## E0

```json
{
  "fragmento_cus": 20100,
  "fragmento_apu": 6900,
  "fragmento_mdd": 3000,
  "total_global": 30000,
  "filas_duplicadas": 0,
  "total_central": 30000,
  "reconstruccion_identica": true,
  "contrarreferencias_fuera_de_su_nodo": 0
}
```

## E3

```json
{
  "bdd_apu_registrar": "30/30",
  "bdd_apu_bandeja": "30/30",
  "bdd_apu_aceptar_local": "30/30",
  "bdd_apu_leer_catalogo": "30/30",
  "bdd_cus_aceptar_2pc": "0/30",
  "bdd_cus_bandeja_replica": "30/30",
  "bdd_cus_bandeja_fdw": "0/5",
  "central_apu_registrar": "0/10",
  "central_apu_consultar": "0/10",
  "central_cus_operar": "30/30",
  "reservas_sin_referencia_aceptada": 0,
  "segundos_para_ver_referencias_del_corte": 2.7
}
```

## E4

```json
{
  "resultado_coordinador": "DUDOSA",
  "preparadas_en_apurimac": 1,
  "update_local_bloqueado": true,
  "espera_hasta_timeout_s": 2.0,
  "otras_operaciones_locales": "10/10",
  "resueltas_por_recuperacion": 1,
  "estado_final_en_apurimac": "ACEPTADA",
  "reserva_en_cusco": 1
}
```

## E5

```json
{
  "2pc": {
    "ensayos": 20,
    "cama_asignada_dos_veces": 0,
    "aceptada_sin_cama": 0,
    "exactamente_un_ganador": 20
  },
  "sin_coordinacion": {
    "ensayos": 20,
    "cama_asignada_dos_veces": 0,
    "aceptada_sin_cama": 20,
    "exactamente_un_ganador": 0
  }
}
```
