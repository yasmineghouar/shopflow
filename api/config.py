"""config.py — paramètres du service, surchargeables par variables d'environnement.

Chaque valeur est justifiée dans le dossier d'architecture (section « Choix des paramètres »).
PATTERNS=off désactive tous les patterns de résilience : c'est le mode « avant »
utilisé par les expériences de chaos pour comparer avant / après.
"""
import os


def _f(nom, defaut):
    return float(os.getenv(nom, defaut))


PORT = int(os.getenv("PORT", "8000"))
PATTERNS = os.getenv("PATTERNS", "on").lower() not in ("off", "0", "false")

STOCK_URL = os.getenv("STOCK_URL", "http://localhost:8081").rstrip("/")
RECO_URL = os.getenv("RECO_URL", "http://localhost:8082").rstrip("/")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://localhost:8083").rstrip("/")

# Timeouts (s). Sans patterns : timeout « par défaut » très long, comme une lib HTTP naïve.
TIMEOUT_NAIF = _f("TIMEOUT_NAIF", "10")
TIMEOUT_STOCK = _f("TIMEOUT_STOCK", "0.3")
TIMEOUT_RECO = _f("TIMEOUT_RECO", "0.25")
TIMEOUT_PAYMENT = _f("TIMEOUT_PAYMENT", "1.0")

# Retry : nombre total de tentatives et budget de temps global par appel (deadline).
TENTATIVES = int(os.getenv("TENTATIVES", "3"))
BACKOFF_BASE = _f("BACKOFF_BASE", "0.05")
DEADLINE_STOCK = _f("DEADLINE_STOCK", "0.8")
DEADLINE_PAYMENT = _f("DEADLINE_PAYMENT", "2.5")

# Circuit breaker : taux d'échec sur une fenêtre glissante + volume minimal.
CB_FENETRE = int(os.getenv("CB_FENETRE", "50"))
CB_SEUIL = _f("CB_SEUIL", "0.6")
CB_VOLUME_MIN = int(os.getenv("CB_VOLUME_MIN", "20"))
CB_DELAI_OUVERTURE = _f("CB_DELAI_OUVERTURE", "5")

# Bulkhead : places simultanées par dépendance.
BULKHEAD_STOCK = int(os.getenv("BULKHEAD_STOCK", "10"))
BULKHEAD_RECO = int(os.getenv("BULKHEAD_RECO", "4"))
BULKHEAD_PAYMENT = int(os.getenv("BULKHEAD_PAYMENT", "6"))

# Cache résilient (stale-if-error) : âge maximal d'une valeur servie en repli.
CACHE_STALE_MAX = _f("CACHE_STALE_MAX", "300")

# Rate limiting par client (token bucket) et load shedding par instance.
RL_CAPACITE = _f("RL_CAPACITE", "20")
RL_DEBIT = _f("RL_DEBIT", "10")
LS_MAX_EN_COURS = int(os.getenv("LS_MAX_EN_COURS", "40"))
LS_RESERVE_PRIORITAIRE = _f("LS_RESERVE_PRIORITAIRE", "0.25")

# Capacité de traitement simulée de l'instance (ex. pool de connexions base de données).
WORKERS = int(os.getenv("WORKERS", "8"))
TRAVAIL_S = _f("TRAVAIL_S", "0.02")

DELAI_DEMARRAGE = _f("DELAI_DEMARRAGE", "3")
DRAIN_S = _f("DRAIN_S", "5")
