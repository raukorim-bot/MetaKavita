"""Reproduit le blocage d'une couverture sous eventlet, sans réseau externe.

Pourquoi ce script existe. Une passe par tome est restée figée sur sa première
unité — « 0 / 11 », aucune ligne de journal, pendant treize minutes — alors que
cette unité n'avait plus qu'une couverture à écrire. Deux explications se
disputaient le cas et se traitent différemment :

1. un hébergeur lent : le corps arrive au compte-gouttes, une borne de durée
   suffit ;
2. `curl_cffi` en mode flux sous eventlet : son chemin **non-flux** honore
   `thread="eventlet"` et passe `c.perform()` par `eventlet.tpool`, donc par un
   vrai thread système ; son chemin **flux** ignore ce réglage et soumet
   `c.perform()` à un `ThreadPoolExecutor` — sous eventlet, un greenthread qui
   entre dans du C bloquant et ne rend plus la main au hub. Là, aucune borne
   vérifiée entre deux morceaux ne peut se déclencher, puisque le premier morceau
   n'arrive jamais.

Le battement de cœur tranche entre les deux : s'il s'arrête, le hub est bloqué et
c'est le cas 2 ; s'il continue pendant que la lecture attend, c'est le cas 1.

Usage : python debug/repro_cover_eventlet.py
Aucun appel sortant : le serveur est local et volontairement muet après ses
en-têtes.
"""
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import socket  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

HEADERS = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: image/jpeg\r\n"
    b"Transfer-Encoding: chunked\r\n"
    b"Connection: keep-alive\r\n"
    b"\r\n"
)


def _stalling_server(ready: threading.Event) -> int:
    """Sert les en-têtes d'une image puis se tait — connexion laissée ouverte.

    C'est le comportement d'un CDN saturé : la connexion est acceptée, la réponse
    commence, et rien ne suit. Le `timeout` d'une requête HTTP ne couvre pas ce
    silence-là quand le corps est lu après le retour de la requête.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]

    def _serve():
        ready.set()
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            # Chaque connexion est traitée à part : un client qui raccroche ne doit
            # pas emporter le serveur, sans quoi l'essai suivant échouerait sur un
            # « couldn't connect » qui ne prouve rien.
            eventlet.spawn_n(_handle, conn)

    def _handle(conn):
        try:
            conn.sendall(HEADERS)
            # Un premier morceau, puis le silence : de quoi laisser croire que la
            # lecture progresse avant de s'arrêter pour de bon.
            conn.sendall(b"10\r\n" + b"\xff" * 16 + b"\r\n")
            eventlet.sleep(3600)
        except OSError:
            return

    eventlet.spawn_n(_serve)
    return port


def _heartbeat(stop: threading.Event, beats: list) -> None:
    """Compte les tours du hub : c'est lui qui dit si l'application respire."""
    while not stop.is_set():
        beats.append(time.monotonic())
        eventlet.sleep(0.2)


def main() -> int:
    ready = threading.Event()
    port = _stalling_server(ready)
    ready.wait(5)
    url = f"http://127.0.0.1:{port}/cover.jpg"

    beats: list = []
    stop = threading.Event()
    eventlet.spawn_n(_heartbeat, stop, beats)
    eventlet.sleep(0.4)
    before = len(beats)

    from curl_cffi import requests as cffi_requests

    print(f"Lecture en mode FLUX (ce que fait MetaKavita aujourd'hui) sur {url}")
    started = time.monotonic()
    outcome = "terminée"
    session = cffi_requests.Session()
    try:
        with eventlet.Timeout(8, False):
            res = session.get(url, impersonate="chrome110", stream=True, timeout=5)
            total = 0
            for chunk in res.iter_content():
                total += len(chunk or b"")
            print(f"   corps lu : {total} octets")
    except Exception as exc:  # pragma: no cover - diagnostic
        outcome = f"exception {type(exc).__name__}: {exc}"
    finally:
        elapsed = time.monotonic() - started
        try:
            session.close()
        except Exception:
            pass

    eventlet.sleep(0.3)
    during = len(beats) - before

    print(f"   issue : {outcome} après {elapsed:.1f} s")
    print(f"   battements du hub pendant la lecture : {during}")
    if elapsed >= 7.5:
        print("   -> la lecture n'a jamais rendu la main : le timeout de curl ne")
        print("      couvre pas l'attente du corps, et une borne verifiee entre")
        print("      deux morceaux n'est jamais atteinte.")

    # Correctif retenu : pas de mode flux, et libcurl passé par le pool de
    # threads d'eventlet — ce que le chemin non-flux de curl_cffi sait faire.
    print()
    print("Lecture SANS mode flux, session thread=eventlet (correctif retenu)")
    before2 = len(beats)
    started2 = time.monotonic()
    outcome2 = "terminée"
    session2 = cffi_requests.Session(thread="eventlet")
    try:
        with eventlet.Timeout(20, False):
            res2 = session2.get(url, impersonate="chrome110", timeout=5)
            print(f"   corps lu : {len(res2.content)} octets")
    except Exception as exc:
        outcome2 = f"{type(exc).__name__}: {exc}"
    finally:
        elapsed2 = time.monotonic() - started2
        try:
            session2.close()
        except Exception:
            pass

    eventlet.sleep(0.3)
    stop.set()
    during2 = len(beats) - before2

    print(f"   issue : {outcome2} après {elapsed2:.1f} s")
    print(f"   battements du hub pendant la lecture : {during2}")
    print()
    if elapsed2 < 7 and during2 > 1:
        print("VERDICT : sans mode flux, le timeout de curl s'applique vraiment et")
        print("          le hub continue de tourner. C'est le correctif.")
    else:
        print("VERDICT : la variante ne borne pas davantage — chercher ailleurs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
