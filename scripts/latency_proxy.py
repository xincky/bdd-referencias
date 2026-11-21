#!/usr/bin/env python3
"""Proxy TCP que simula los enlaces de red entre regiones (WAN).

Cada enlace escucha en un puerto y reenvía al puerto de un nodo PostgreSQL,
agregando un retardo fijo en cada sentido (RTT/2 de ida y RTT/2 de vuelta).
Así, cada ida y vuelta de red a través del enlace suma el RTT configurado.

Uso:
    python3 latency_proxy.py --rtt 50                 # todos los enlaces con RTT 50 ms
    python3 latency_proxy.py --rtt 50 --down APU-CUS  # el enlace APU-CUS cortado

Para "cortar" un enlace en caliente se crea el archivo /tmp/link_<NOMBRE>.down
(por ejemplo /tmp/link_APU-CUS.down): las conexiones nuevas se rechazan y las
abiertas se cierran. Al borrar el archivo el enlace vuelve.
"""
import argparse
import asyncio
import os
import time

# (puerto de escucha, puerto destino, nombre del enlace)
LINKS = [
    # Base de datos distribuida: nodo -> nodo
    (6132, 5431, "APU-CUS"),  # desde Apurímac hacia el nodo Cusco
    (6231, 5432, "APU-CUS"),  # desde Cusco hacia el nodo Apurímac
    (6133, 5431, "MDD-CUS"),  # desde Madre de Dios hacia el nodo Cusco
    (6331, 5433, "MDD-CUS"),  # desde Cusco hacia el nodo Madre de Dios
    (6233, 5432, "APU-MDD"),  # desde Madre de Dios hacia el nodo Apurímac
    (6332, 5433, "APU-MDD"),  # desde Apurímac hacia el nodo Madre de Dios
    # Línea base centralizada: clientes regionales -> servidor central (Cusco)
    (6240, 5440, "APU-CUS"),  # clientes de Apurímac hacia el servidor central
    (6340, 5440, "MDD-CUS"),  # clientes de Madre de Dios hacia el servidor central
]


def link_down(name: str) -> bool:
    return os.path.exists(f"/tmp/link_{name}.down")


async def pipe(reader, writer, delay_s, name):
    """Copia bytes de reader a writer, entregando cada bloque delay_s después."""
    queue: asyncio.Queue = asyncio.Queue()

    async def producer():
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await queue.put((time.monotonic() + delay_s, data))
        finally:
            await queue.put((None, None))

    async def consumer():
        while True:
            due, data = await queue.get()
            if data is None:
                break
            wait = due - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            if link_down(name):
                break
            writer.write(data)
            await writer.drain()

    try:
        await asyncio.gather(producer(), consumer())
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def watchdog(writers, name):
    """Cierra las conexiones abiertas si el enlace se corta."""
    while True:
        await asyncio.sleep(0.1)
        if link_down(name):
            for w in writers:
                try:
                    w.close()
                except Exception:
                    pass
            return
        if all(w.is_closing() for w in writers):
            return


def make_handler(target_port, delay_s, name):
    async def handle(client_reader, client_writer):
        if link_down(name):
            client_writer.close()
            return
        try:
            server_reader, server_writer = await asyncio.open_connection("127.0.0.1", target_port)
        except OSError:
            client_writer.close()
            return
        await asyncio.gather(
            pipe(client_reader, server_writer, delay_s, name),
            pipe(server_reader, client_writer, delay_s, name),
            watchdog([client_writer, server_writer], name),
            return_exceptions=True,
        )
    return handle


async def main(rtt_ms: float):
    delay_s = rtt_ms / 2000.0  # mitad del RTT en cada sentido
    servers = []
    for listen, target, name in LINKS:
        srv = await asyncio.start_server(make_handler(target, delay_s, name), "127.0.0.1", listen)
        servers.append(srv)
    print(f"proxy listo: {len(servers)} enlaces con RTT={rtt_ms} ms", flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rtt", type=float, required=True, help="RTT simulado en milisegundos")
    ap.add_argument("--down", action="append", default=[], help="enlace cortado desde el inicio")
    args = ap.parse_args()
    for n in args.down:
        open(f"/tmp/link_{n}.down", "w").close()
    asyncio.run(main(args.rtt))
