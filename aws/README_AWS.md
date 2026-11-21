# Despliegue en AWS: un nodo por región

| Instancia | Región AWS | Representa a | Qué se ejecuta allí |
| --- | --- | --- | --- |
| `n_cus` | sa-east-1 (São Paulo) | Cusco, nodo central y base central | instalar, cargar datos, desplegar, medir |
| `n_apu` | us-east-1 (Virginia del Norte) | Apurímac | instalar, medir la bandeja de Abancay |
| `n_mdd` | us-east-2 (Ohio) | Madre de Dios | instalar |

En las tres instancias solo se instala **PostgreSQL 16** (ya trae `postgres_fdw`) y
**python3-psycopg2**, el conector de Python para PostgreSQL. Ubuntu 24.04 ya trae Python 3.

## Paso 1. Anota las IP públicas

En la consola de EC2 de cada región, copia la «Public IPv4 address» de cada instancia.
Cambian si detienes la instancia (ver paso 8); un reinicio normal las conserva.

## Paso 2. Grupos de seguridad (uno en cada región)

Reglas de entrada de cada instancia:

| Tipo | Puerto | Origen |
| --- | --- | --- |
| SSH | 22 | Mi IP |
| PostgreSQL | 5432 | IP del primer nodo vecino, con /32 |
| PostgreSQL | 5432 | IP del segundo nodo vecino, con /32 |

Por ejemplo, en `n_cus` se abre 5432 para `IP_APU/32` e `IP_MDD/32`. No abras 5432 a `0.0.0.0/0`.

## Paso 3. Copia el proyecto a las tres instancias (desde tu computadora)

```bash
scp -i llave-sao-paulo.pem proyecto_bdd_aws.zip ubuntu@IP_CUS:~
scp -i llave-virginia.pem  proyecto_bdd_aws.zip ubuntu@IP_APU:~
scp -i llave-ohio.pem      proyecto_bdd_aws.zip ubuntu@IP_MDD:~
```

El usuario de las imágenes Ubuntu es `ubuntu`. En Windows funciona igual en PowerShell.

## Paso 4. Instala el nodo (en cada una de las tres instancias)

```bash
ssh -i llave.pem ubuntu@IP_DE_ESTA_INSTANCIA
sudo apt-get update && sudo apt-get install -y unzip
unzip proyecto_bdd_aws.zip
sudo bash proyecto_bdd/aws/instalar_nodo.sh MiClave2026
```

Usa la **misma contraseña** en los tres nodos (8 o más letras o números). Al final debe
aparecer: `PostgreSQL 16... | wal_level=logical | max_prepared_transactions=50 | listen_addresses=*`.

## Paso 5. Configura y prueba la conexión (en `n_cus`)

```bash
cd ~/proyecto_bdd
cp aws/nodos.json.ejemplo aws/nodos.json
nano aws/nodos.json          # escribe las tres IP públicas y la contraseña
python3 aws/probar_conexion.py --desde CUS
```

Deben salir tres líneas `OK`, cada una con su RTT real. Si sale `FALLA` en un nodo, revisa
su grupo de seguridad (paso 2) y que el paso 4 haya terminado en ese nodo.

## Paso 6. Genera los datos y despliega la BDD (solo en `n_cus`)

```bash
python3 datos/generar_datos.py
BDD_CONFIG=aws/nodos.json python3 scripts/deploy.py
```

Crea en los tres nodos los fragmentos, las tablas foráneas y las réplicas, y la base
`central` dentro de `n_cus` para comparar. Debe terminar con `despliegue completo`.

## Paso 7. Mide las primeras consultas

```bash
# en n_cus
python3 aws/medir_aws.py --desde CUS
```

En `n_apu`, crea el mismo `aws/nodos.json` (paso 5) y ejecuta:

```bash
cd ~/proyecto_bdd
python3 aws/medir_aws.py --desde APU
```

Los resultados quedan en `resultados/aws/CUS.md` y `resultados/aws/APU.md`. Para la
demostración en vivo, desde cualquier nodo:

```bash
sudo -u postgres psql -d referencias -c "SELECT region_origen, count(*) FROM referencia GROUP BY 1"
```

## Paso 8. Al apagar y volver a encender

Detén las instancias cuando no las uses: la IP pública automática se libera y deja de cobrarse.
Al encenderlas:

1. Anota las IP nuevas y corrige las reglas 5432 de los tres grupos de seguridad.
2. Escribe las IP nuevas en `aws/nodos.json` (en `n_cus` y en `n_apu`).
3. En `n_cus`: `python3 aws/actualizar_ips.py`.
