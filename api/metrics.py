"""metrics.py — métriques au format texte Prometheus (bibliothèque standard uniquement).

Trois types suffisent pour le projet : Counter, Gauge et Histogram, avec labels.
Le registre est exposé par GET /metrics (voir shopflow_api.py).
"""
import threading

_REGISTRE = []
_LOCK = threading.Lock()


def _cle(labels):
    return tuple(sorted(labels.items()))


def _format_labels(cle, extra=None):
    paires = list(cle) + list((extra or {}).items())
    if not paires:
        return ""
    contenu = ",".join(f'{k}="{v}"' for k, v in paires)
    return "{" + contenu + "}"


class _Metrique:
    type_ = ""

    def __init__(self, nom, aide):
        self.nom, self.aide = nom, aide
        self.valeurs = {}
        with _LOCK:
            _REGISTRE.append(self)

    def entete(self):
        return [f"# HELP {self.nom} {self.aide}", f"# TYPE {self.nom} {self.type_}"]


class Counter(_Metrique):
    type_ = "counter"

    def inc(self, n=1.0, **labels):
        cle = _cle(labels)
        with _LOCK:
            self.valeurs[cle] = self.valeurs.get(cle, 0.0) + n

    def valeur(self, **labels):
        return self.valeurs.get(_cle(labels), 0.0)

    def exposer(self):
        return [f"{self.nom}{_format_labels(c)} {v}" for c, v in self.valeurs.items()]


class Gauge(Counter):
    type_ = "gauge"

    def set(self, v, **labels):
        with _LOCK:
            self.valeurs[_cle(labels)] = float(v)

    def dec(self, n=1.0, **labels):
        self.inc(-n, **labels)


class Histogram(_Metrique):
    type_ = "histogram"
    SEUILS = (0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0)

    def observe(self, v, **labels):
        cle = _cle(labels)
        with _LOCK:
            seaux, somme, nb = self.valeurs.get(cle, ([0] * len(self.SEUILS), 0.0, 0))
            seaux = [n + (1 if v <= s else 0) for n, s in zip(seaux, self.SEUILS)]
            self.valeurs[cle] = (seaux, somme + v, nb + 1)

    def exposer(self):
        lignes = []
        for cle, (seaux, somme, nb) in self.valeurs.items():
            for s, n in zip(self.SEUILS, seaux):
                lignes.append(f"{self.nom}_bucket{_format_labels(cle, {'le': s})} {n}")
            lignes.append(f"{self.nom}_bucket{_format_labels(cle, {'le': '+Inf'})} {nb}")
            lignes.append(f"{self.nom}_sum{_format_labels(cle)} {somme}")
            lignes.append(f"{self.nom}_count{_format_labels(cle)} {nb}")
        return lignes


def exposer():
    """Texte complet de toutes les métriques, prêt pour Prometheus."""
    lignes = []
    with _LOCK:
        metriques = list(_REGISTRE)
    for m in metriques:
        with _LOCK:
            corps = m.exposer()
        lignes += m.entete() + corps
    return "\n".join(lignes) + "\n"


# --------------------------------------------------------------------------
# Métriques du projet : au moins une par pattern
# --------------------------------------------------------------------------
REQUETES = Counter("shopflow_http_requests_total", "Requetes HTTP servies par route et code")
LATENCE = Histogram("shopflow_http_request_duration_seconds", "Latence des requetes HTTP")
EN_COURS = Gauge("shopflow_inflight_requests", "Requetes metier en cours (load shedder)")

RATE_LIMITED = Counter("shopflow_rate_limited_total", "Requetes refusees par le rate limiter (429)")
SHED = Counter("shopflow_load_shed_total", "Requetes rejetees par le load shedder (503)")

APPELS_DEP = Counter("shopflow_dependency_calls_total", "Appels aux dependances par issue")
LATENCE_DEP = Histogram("shopflow_dependency_duration_seconds", "Latence des appels aux dependances")
RETRIES = Counter("shopflow_retries_total", "Nouvelles tentatives envoyees")
TIMEOUTS = Counter("shopflow_timeouts_total", "Appels interrompus par un timeout")
CIRCUIT = Gauge("shopflow_circuit_state", "Etat du circuit breaker (0 ferme, 1 ouvert, 2 semi-ouvert)")
CIRCUIT_TRANSITIONS = Counter("shopflow_circuit_transitions_total", "Changements d'etat du breaker")
BULKHEAD_UTILISE = Gauge("shopflow_bulkhead_in_use", "Places occupees dans le bulkhead")
BULKHEAD_REFUS = Counter("shopflow_bulkhead_rejected_total", "Appels refuses car bulkhead plein")
FALLBACK = Counter("shopflow_fallback_total", "Reponses de repli par dependance et type")
CACHE = Counter("shopflow_cache_events_total", "Evenements du cache resilient (hit, stale, miss)")
DEGRADE = Counter("shopflow_degraded_responses_total", "Reponses servies en mode degrade")
PRET = Gauge("shopflow_ready", "1 si l'instance est prete (readiness)")
PATTERNS = Gauge("shopflow_patterns_enabled", "1 si les patterns de resilience sont actifs")
