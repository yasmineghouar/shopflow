"""health.py — sondes de santé et arrêt propre (suite du TP 8). Point d'entrée du conteneur.

Choix du projet final (réponse à la question 2 du TP 8) : la readiness ne dépend PLUS des
dépendances partagées (stock, reco, payment). Si elles tombaient, toutes les instances
sortiraient du pool en même temps : panne totale au lieu d'un service dégradé. Les pannes de
dépendances sont gérées par timeout + circuit breaker + fallback ; leur état est seulement
rapporté (à titre d'information) dans le corps de /health/ready.
"""
import signal
import threading
import time

import config as cfg
import metrics as m
import shopflow_api as api

DEMARRE_A = time.monotonic()
ETAT = {"arret": False}


def live(h):
    # Liveness : uniquement le processus (jamais les dépendances, sinon redémarrages en cascade).
    h.repondre(200, {"status": "ok", "probe": "live"})


def startup(h):
    ecoule = time.monotonic() - DEMARRE_A
    if ecoule < cfg.DELAI_DEMARRAGE:
        return h.repondre(503, {"status": "starting", "probe": "startup",
                                "secondes_restantes": round(cfg.DELAI_DEMARRAGE - ecoule, 2)})
    h.repondre(200, {"status": "ok", "probe": "startup"})


def ready(h):
    causes = []
    if time.monotonic() - DEMARRE_A < cfg.DELAI_DEMARRAGE:
        causes.append("demarrage_en_cours")
    if ETAT["arret"]:
        causes.append("arret_en_cours")
    info = {d.nom: d.breaker.nom_etat for d in api.DEPENDANCES}
    m.PRET.set(0 if causes else 1)
    if causes:
        return h.repondre(503, {"status": "not_ready", "probe": "ready", "causes": causes,
                                "circuits": info})
    h.repondre(200, {"status": "ready", "probe": "ready", "circuits": info})


api.ROUTES.update({"/health/live": live, "/health/ready": ready, "/health/startup": startup})


def arret_propre(srv, drain=cfg.DRAIN_S):
    """SIGTERM (docker stop, kubectl delete pod) ou SIGINT : readiness en échec,
    drain pendant `drain` secondes (le load balancer retire l'instance), puis arrêt."""
    verrou = threading.Lock()

    def terminer():
        print(f"Arrêt demandé : readiness en échec, drain de {drain} s...", flush=True)
        time.sleep(drain)
        srv.shutdown()

    def gestionnaire(signum, frame):
        with verrou:
            if ETAT["arret"]:
                return
            ETAT["arret"] = True
        m.PRET.set(0)
        threading.Thread(target=terminer, daemon=True).start()

    for nom in ("SIGINT", "SIGTERM"):
        if hasattr(signal, nom):
            try:
                signal.signal(getattr(signal, nom), gestionnaire)
            except (ValueError, OSError):
                pass


if __name__ == "__main__":
    srv = api.demarrer()
    arret_propre(srv)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        print("Serveur arrêté.", flush=True)
