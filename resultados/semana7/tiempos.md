# Primeras consultas: mediana p50 (p95), en ms

| Consulta | RTT 20 ms | RTT 50 ms | RTT 100 ms |
| --- | --- | --- | --- |
| Bandeja de Abancay · BDD (nodo propio) | 0.51 (0.64) | 0.26 (0.36) | 0.53 (0.89) |
| Bandeja de Abancay · central (remota) | 21.39 (21.96) | 51.97 (53.22) | 102.47 (103.6) |
| Bandeja de Cusco · BDD con réplica local | 0.81 (0.92) | 0.92 (1.38) | 1.66 (2.54) |
| Bandeja de Cusco · BDD leyendo por FDW | 191.23 (195.42) | 464.84 (469.35) | 918.72 (923.7) |
| Bandeja de Cusco · central (local) | 0.72 (1.16) | 0.78 (0.88) | 0.78 (1.15) |
| SELECT 1 por el enlace (RTT medido) | 21.09 (22.05) | 51.26 (52.09) | 101.67 (102.56) |

50 consultas por medición; RTT simulado por el proxy (valores de diseño).
