# BDD para referencias y contrarreferencias (Apurímac, Cusco y Madre de Dios)

Prototipo del proyecto final de **Tópicos Avanzados en Base de Datos**: una base de
datos distribuida homogénea (PostgreSQL 16, 3 nodos) comparada con una base
centralizada que resuelve la misma tarea.

## Qué hay en el repositorio

| Ruta | Contenido |
| --- | --- |
| `scripts/setup_clusters.sh` | Crea e inicia 4 instancias PostgreSQL: `n_cus` (5431), `n_apu` (5432), `n_mdd` (5433) y `central` (5440). |
| `scripts/latency_proxy.py` | Proxy TCP que simula los enlaces entre regiones con un RTT fijo y permite "cortar" un enlace. |
| `scripts/deploy.py` | Esquema, fragmentación, tablas foráneas (`postgres_fdw`), replicación lógica, funciones y carga de datos en los 4 servidores. |
| `datos/generar_datos.py` | Genera los datos sintéticos (semilla fija): 126 establecimientos, 30 000 referencias, 20 980 contrarreferencias. |
| `experimentos/run_experiments.py` | Experimentos E0–E6 y coordinador 2PC. Guarda `resultados/resultados.json`. |
| `experimentos/semana7_demo.py` | Semana 7: conteos por nodo, verificación E0, planes `EXPLAIN` de las dos bandejas y sus tiempos (solo lectura). Guarda `resultados/semana7/`. |
| `aws/` | Despliegue en tres instancias EC2 (una por región): `instalar_nodo.sh`, `nodos.json.ejemplo`, `probar_conexion.py`, `medir_aws.py` y `actualizar_ips.py`. Guía paso a paso en `aws/README_AWS.md`. |
| `resultados/` | Resultados de la corrida reportada en el informe y su registro. |

## Requisitos

- Linux con PostgreSQL 16 (binarios en `/usr/lib/postgresql/16/bin`, con la extensión `postgres_fdw`).
- Python 3.10 o superior y `pip install psycopg2-binary`.
- Un usuario del sistema distinto de root para los servidores (por ejemplo, `pg`).

## Reproducir la demostración

```bash
# 1) servidores (como usuario no root)
sudo -u pg bash scripts/setup_clusters.sh

# 2) datos sintéticos
python3 datos/generar_datos.py

# 3) proxy de latencia (en otra terminal) y despliegue
python3 scripts/latency_proxy.py --rtt 20 &
python3 scripts/deploy.py
kill %1                      # el script de experimentos levanta su propio proxy

# 4a) semana 7: datos cargados y primeras consultas (unos 2 minutos)
python3 experimentos/semana7_demo.py

# 4b) experimentos (unos 20 minutos con 150 operaciones por medición)
N_OPS=150 python3 experimentos/run_experiments.py
```

Variables útiles: `N_OPS` (operaciones por medición, 150 por defecto) y
`RTTS` (lista de RTT en ms, `20,50,100` por defecto).

## Diseño de la distribución

| Tabla | Estrategia | Dónde vive |
| --- | --- | --- |
| `establecimiento` | Replicada completa (catálogo) | Copia maestra en Cusco; réplicas en Apurímac y Madre de Dios por replicación lógica |
| `referencia` | Fragmentación horizontal por `region_origen` | `cus.referencia`, `apu.referencia`, `mdd.referencia`, cada una en su nodo |
| `contrarreferencia` | Horizontal derivada de `referencia` | En el nodo de su referencia |
| `cupo`, `reserva_cupo` | Por hospital dueño de las camas | Nodo de la región del hospital |
| `apu.referencia`, `mdd.referencia` en Cusco | Réplica de solo lectura con filtro `region_destino = 'CUS'` | Nodo Cusco (bandeja de entrada) |

En cada nodo, `public.referencia` es una tabla particionada por región: la
partición local es el fragmento propio y las otras dos son tablas foráneas. Así
cualquier nodo consulta "una sola tabla" (transparencia de ubicación).

La aceptación de una referencia que viene de otra región es una transacción
distribuida: el coordinador (en Cusco) reserva la cama en el nodo Cusco y cambia
el estado en el nodo de origen con compromiso en dos fases (`PREPARE TRANSACTION`
y `COMMIT PREPARED`), y anota su decisión en `log_2pc` para poder recuperar.

## Comandos útiles para la demostración en vivo

```sql
-- ¿qué nodos visita una consulta? (en el nodo Apurímac: solo el fragmento local)
EXPLAIN SELECT * FROM referencia
 WHERE region_origen = 'APU' AND eess_destino = 4 AND estado = 'ENVIADA';

-- transacciones preparadas y sin terminar (2PC dudosas)
SELECT gid, prepared FROM pg_prepared_xacts;

-- estado de la replicación lógica (en el suscriptor)
SELECT subname, received_lsn, latest_end_time FROM pg_stat_subscription;
```

Para simular el corte del enlace Apurímac–Cusco con el proxy en marcha:
`touch /tmp/link_APU-CUS.down` (cortar) y `rm /tmp/link_APU-CUS.down` (restaurar).

## Datos y privacidad

Todos los datos son sintéticos. Los pacientes se identifican con un seudónimo
(UUID) y solo se guardan edad y sexo, conforme a la Ley N.º 29733. Cuatro nombres de
hospitales provienen del ASISHO 2023 del Hospital Regional del Cusco, el Hospital
Antonio Lorena se toma del informe de avance y el sexto hospital es sintético; su
nivel sigue el modelo simplificado del caso. Los centros de salud de nivel I
son ficticios.

## Limitaciones del entorno

Los cuatro servidores corren en una sola máquina (2 vCPU). La latencia se simula
con un retardo fijo, sin variación, pérdida de paquetes ni límite de ancho de
banda. Los valores de RTT (20, 50 y 100 ms) son de diseño, no mediciones de la
red real entre los hospitales.
