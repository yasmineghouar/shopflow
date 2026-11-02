"""shopflow_api.py — API ShopFlow du projet final (suite des TP 7 à 10).

Routes métier :
    GET  /products/<sku>   page produit = stock (critique) + recommandations (optionnelles)
    POST /checkout         paiement idempotent (prioritaire pour le load shedder)
Routes techniques (enregistrées dans ROUTES) : /health/*, /metrics
"""
import json
import math
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config as cfg
import metrics as m
from client import ErreurPermanente
from rate_limit import TokenBucket, LoadShedder
from resilience import (BulkheadPlein, CacheResilient, CircuitOuvert, Dependance)

ROUTES = {}   # routes GET exactes supplémentaires (health checks, métriques)

ACTIF = cfg.PATTERNS
m.PATTERNS.set(1 if ACTIF else 0)

_CB = {"fenetre": cfg.CB_FENETRE, "seuil": cfg.CB_SEUIL,
       "volume_min": cfg.CB_VOLUME_MIN, "delai_ouverture": cfg.CB_DELAI_OUVERTURE}

STOCK = Dependance("stock", cfg.STOCK_URL, ACTIF, timeout=cfg.TIMEOUT_STOCK,
                   timeout_naif=cfg.TIMEOUT_NAIF, tentatives=cfg.TENTATIVES,
                   backoff=cfg.BACKOFF_BASE, deadline=cfg.DEADLINE_STOCK,
                   places=cfg.BULKHEAD_STOCK, cb=_CB)
# Dépendance optionnelle : une seule tentative, timeout court, on dégrade plutôt qu'attendre.
RECO = Dependance("reco", cfg.RECO_URL, ACTIF, timeout=cfg.TIMEOUT_RECO,
                  timeout_naif=cfg.TIMEOUT_NAIF, tentatives=1,
                  places=cfg.BULKHEAD_RECO, cb=_CB)
PAYMENT = Dependance("payment", cfg.PAYMENT_URL, ACTIF, timeout=cfg.TIMEOUT_PAYMENT,
                     timeout_naif=cfg.TIMEOUT_NAIF, tentatives=cfg.TENTATIVES,
                     backoff=cfg.BACKOFF_BASE, deadline=cfg.DEADLINE_PAYMENT,
                     places=cfg.BULKHEAD_PAYMENT, cb=_CB)
DEPENDANCES = (STOCK, RECO, PAYMENT)

CACHE_STOCK = CacheResilient(cfg.CACHE_STALE_MAX)

BUCKETS = {}
BUCKETS_LOCK = threading.Lock()
SHEDDER = LoadShedder(cfg.LS_MAX_EN_COURS, cfg.LS_RESERVE_PRIORITAIRE)

# Capacité de traitement limitée de l'instance (simule un pool de connexions/threads).
WORKERS = threading.BoundedSemaphore(cfg.WORKERS)

ERREURS_DEP = (CircuitOuvert, BulkheadPlein, ConnectionError, TimeoutError, ErreurPermanente)


def bucket_du_client(client_id):
    with BUCKETS_LOCK:
        if client_id not in BUCKETS:
            BUCKETS[client_id] = TokenBucket(capacite=cfg.RL_CAPACITE, debit=cfg.RL_DEBIT)
        return BUCKETS[client_id]


def entetes_circuits():
    return {f"X-Circuit-{d.nom.capitalize()}": d.breaker.nom_etat for d in DEPENDANCES}


# --------------------------------------------------------------------------
# Logique métier
# --------------------------------------------------------------------------
def page_produit(sku):
    degrade = []

    # 1) Stock : dépendance critique, repli sur la dernière valeur connue (cache résilient).
    try:
        stock = STOCK.appeler(f"/stock/{sku}")["stock"]
        CACHE_STOCK.mettre(sku, stock)
        source, age = "direct", 0
    except ERREURS_DEP as e:
        if not ACTIF:
            return 502, {"error": f"stock indisponible ({type(e).__name__})"}, {}
        stock, age = CACHE_STOCK.perime(sku)
        if stock is not None:
            source = "cache"
            m.CACHE.inc(evenement="stale_hit")
            m.FALLBACK.inc(dep="stock", type="cache")
        else:
            source = "inconnu"
            m.CACHE.inc(evenement="miss")
            m.FALLBACK.inc(dep="stock", type="valeur_par_defaut")
        degrade.append(f"stock_{source}")

    # 2) Recommandations : optionnelles -> dégradation gracieuse (liste vide).
    try:
        reco = RECO.appeler(f"/reco/{sku}")["items"]
    except ERREURS_DEP as e:
        if not ACTIF:
            return 502, {"error": f"reco indisponible ({type(e).__name__})"}, {}
        reco = []
        m.FALLBACK.inc(dep="reco", type="liste_vide")
        degrade.append("reco")

    corps = {"sku": sku, "stock": stock, "source_stock": source,
             "age_cache_s": round(age or 0, 1), "recommandations": reco, "degrade": degrade}
    entetes = {"X-Degraded": ",".join(degrade) or "non"}
    if degrade:
        m.DEGRADE.inc(route="/products", raison="+".join(degrade))
    return 200, corps, entetes


def checkout(corps, cle_client):
    # Clé d'idempotence de bout en bout : celle du client si fournie, sinon générée.
    # Les nouvelles tentatives (internes ou du client) réutilisent la même clé : aucun double débit.
    entetes = {}
    if ACTIF:
        cle = cle_client or str(uuid.uuid4())
        entetes = {"Idempotency-Key": cle}
    else:
        cle = None
    try:
        paiement = PAYMENT.appeler("/payments", methode="POST",
                                   corps={"montant": corps.get("montant", 0)}, entetes=entetes)
    except CircuitOuvert:
        reste = PAYMENT.breaker.delai_ouverture - (time.monotonic() - PAYMENT.breaker.ouvert_depuis)
        return 503, {"error": "paiement temporairement indisponible", "commande": cle}, \
            {"Retry-After": max(1, math.ceil(reste))}
    except ERREURS_DEP as e:
        code = 503 if ACTIF else 502
        return code, {"error": f"paiement en échec ({type(e).__name__})", "commande": cle}, \
            {"Retry-After": 1} if ACTIF else {}
    return 201, {"commande": cle, "paiement": paiement}, {}


# --------------------------------------------------------------------------
# Serveur HTTP
# --------------------------------------------------------------------------
class Api(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def repondre(self, code, corps, entetes=None, type_contenu="application/json"):
        data = corps.encode() if isinstance(corps, str) else json.dumps(corps).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", type_contenu)
        self.send_header("Content-Length", str(len(data)))
        for nom, valeur in {**entetes_circuits(), **(entetes or {})}.items():
            self.send_header(nom, str(valeur))
        self.end_headers()
        self.wfile.write(data)
        self.code_envoye = code

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if chemin in ROUTES:
            return ROUTES[chemin](self)
        if chemin.startswith("/products/"):
            sku = chemin.rsplit("/", 1)[-1]
            return self._metier("/products", lambda: page_produit(sku))
        self.repondre(404, {"error": "not found"})

    def do_POST(self):
        chemin = self.path.split("?")[0]
        if chemin != "/checkout":
            return self.repondre(404, {"error": "not found"})
        try:
            corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.repondre(400, {"error": "JSON invalide"})
        cle = self.headers.get("Idempotency-Key")
        self._metier("/checkout", lambda: checkout(corps, cle))

    def _metier(self, route, traitement):
        """Chaîne commune : rate limiting -> load shedding -> capacité -> traitement + métriques."""
        debut = time.monotonic()
        self.code_envoye = 500
        try:
            self._proteger_et_traiter(route, traitement)
        finally:
            duree = time.monotonic() - debut
            code = self.code_envoye
            classe = "429" if code == 429 else f"{code // 100}xx"
            m.REQUETES.inc(route=route, code=str(code))
            m.LATENCE.observe(duree, route=route, classe=classe)

    def _proteger_et_traiter(self, route, traitement):
        if ACTIF:
            client_id = self.headers.get("X-Client-Id") or self.client_address[0]
            bucket = bucket_du_client(client_id)
            if not bucket.autoriser():
                m.RATE_LIMITED.inc(route=route)
                return self.repondre(429, {"error": "Trop de requêtes"},
                                     {"Retry-After": max(1, math.ceil(bucket.attente()))})
            prioritaire = route == "/checkout"
            if not SHEDDER.entrer(prioritaire):
                m.SHED.inc(route=route, priorite="haute" if prioritaire else "normale")
                return self.repondre(503, {"error": "Service saturé"}, {"Retry-After": 1})
        m.EN_COURS.inc()
        try:
            with WORKERS:
                time.sleep(cfg.TRAVAIL_S)           # travail propre à l'instance
                try:
                    code, corps, entetes = traitement()
                except Exception as e:              # filet de sécurité : jamais de connexion coupée
                    code, corps, entetes = 500, {"error": type(e).__name__}, {}
            self.repondre(code, corps, entetes)
        finally:
            m.EN_COURS.dec()
            if ACTIF:
                SHEDDER.sortir()


def metriques(h):
    h.repondre(200, m.exposer(), type_contenu="text/plain; version=0.0.4")


ROUTES["/metrics"] = metriques


def demarrer(port=cfg.PORT):
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.request_queue_size = 256
    serveur = ThreadingHTTPServer(("", port), Api)
    print(f"ShopFlow API sur le port {port} — patterns {'ACTIFS' if ACTIF else 'DÉSACTIVÉS'}",
          flush=True)
    return serveur
