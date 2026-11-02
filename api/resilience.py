"""resilience.py — patterns côté appelant, réutilisables pour chaque dépendance.

Ordre d'imbrication (jour 2 / TP 9) :
    fallback( retry( circuit_breaker( bulkhead( appel_http(timeout) ) ) ) )
avec en plus un budget de temps global (deadline) partagé par toutes les tentatives.
"""
import random
import threading
import time
from collections import deque

import metrics as m
from client import appel_http, ErreurPermanente


class CircuitOuvert(Exception):
    pass


class BulkheadPlein(Exception):
    pass


class DeadlineDepassee(TimeoutError):
    pass


# --------------------------------------------------------------------------
# Circuit breaker : FERMÉ -> OUVERT (taux d'échec) -> SEMI-OUVERT (1 essai) -> FERMÉ
# --------------------------------------------------------------------------
class CircuitBreaker:
    FERME, OUVERT, SEMI_OUVERT = 0, 1, 2
    NOMS = {0: "ferme", 1: "ouvert", 2: "semi_ouvert"}

    def __init__(self, nom, fenetre=20, seuil=0.5, volume_min=10, delai_ouverture=5.0):
        self.nom, self.seuil, self.volume_min = nom, seuil, volume_min
        self.delai_ouverture = delai_ouverture
        self.resultats = deque(maxlen=fenetre)      # True = échec
        self.etat, self.ouvert_depuis = self.FERME, 0.0
        self.essai_en_cours = False
        self._lock = threading.Lock()
        m.CIRCUIT.set(0, dep=nom)

    def _passer(self, etat):
        if etat != self.etat:
            self.etat = etat
            m.CIRCUIT.set(etat, dep=self.nom)
            m.CIRCUIT_TRANSITIONS.inc(dep=self.nom, vers=self.NOMS[etat])

    def avant_appel(self):
        with self._lock:
            if self.etat == self.OUVERT:
                if time.monotonic() - self.ouvert_depuis < self.delai_ouverture:
                    raise CircuitOuvert(self.nom)
                self._passer(self.SEMI_OUVERT)
            if self.etat == self.SEMI_OUVERT:
                if self.essai_en_cours:
                    raise CircuitOuvert(self.nom)   # un seul essai à la fois
                self.essai_en_cours = True

    def succes(self):
        with self._lock:
            self.essai_en_cours = False
            self.resultats.append(False)
            if self.etat == self.SEMI_OUVERT:
                self.resultats.clear()
                self._passer(self.FERME)

    def echec(self):
        with self._lock:
            self.essai_en_cours = False
            self.resultats.append(True)
            if self.etat == self.SEMI_OUVERT:
                self._ouvrir()
                return
            n = len(self.resultats)
            if n >= self.volume_min and sum(self.resultats) / n >= self.seuil:
                self._ouvrir()

    def _ouvrir(self):
        self.ouvert_depuis = time.monotonic()
        self._passer(self.OUVERT)

    @property
    def nom_etat(self):
        return self.NOMS[self.etat]


# --------------------------------------------------------------------------
# Bulkhead : nombre maximal d'appels simultanés vers une dépendance
# --------------------------------------------------------------------------
class Bulkhead:
    def __init__(self, nom, places, attente=0.05):
        self.nom, self.attente = nom, attente
        self.sem = threading.BoundedSemaphore(places)

    def __enter__(self):
        if not self.sem.acquire(timeout=self.attente):
            m.BULKHEAD_REFUS.inc(dep=self.nom)
            raise BulkheadPlein(self.nom)
        m.BULKHEAD_UTILISE.inc(dep=self.nom)
        return self

    def __exit__(self, *exc):
        m.BULKHEAD_UTILISE.dec(dep=self.nom)
        self.sem.release()


# --------------------------------------------------------------------------
# Cache résilient : dernière valeur connue, servie si la dépendance est en panne
# --------------------------------------------------------------------------
class CacheResilient:
    """Stratégie stale-if-error : chaque succès met à jour le cache, qui n'est lu
    qu'en cas d'échec de la dépendance (la donnée nominale reste toujours fraîche)."""

    def __init__(self, stale_max):
        self.stale_max = stale_max
        self.donnees = {}
        self._lock = threading.Lock()

    def mettre(self, cle, valeur):
        with self._lock:
            self.donnees[cle] = (valeur, time.monotonic())

    def perime(self, cle):
        """Valeur même périmée (dans la limite stale_max) et son âge en secondes."""
        with self._lock:
            v = self.donnees.get(cle)
        if v is None:
            return None, None
        age = time.monotonic() - v[1]
        return (v[0], age) if age < self.stale_max else (None, None)


# --------------------------------------------------------------------------
# Client d'une dépendance : assemble timeout, bulkhead, breaker, retry
# --------------------------------------------------------------------------
class Dependance:
    def __init__(self, nom, base, actif=True, timeout=0.3, timeout_naif=10.0,
                 tentatives=3, backoff=0.05, deadline=0.0, places=10, cb=None):
        self.nom, self.base, self.actif = nom, base, actif
        self.timeout, self.timeout_naif = timeout, timeout_naif
        self.tentatives, self.backoff, self.deadline = tentatives, backoff, deadline
        self.bulkhead = Bulkhead(nom, places)
        self.breaker = CircuitBreaker(nom, **(cb or {}))

    def _appel_unique(self, chemin, timeout, **kw):
        debut = time.monotonic()
        issue = "succes"
        try:
            return appel_http(self.base, chemin, timeout=timeout, **kw)
        except TimeoutError:
            issue = "timeout"
            m.TIMEOUTS.inc(dep=self.nom)
            raise
        except ConnectionError:
            issue = "erreur"
            raise
        except ErreurPermanente:
            issue = "erreur_permanente"
            raise
        finally:
            m.APPELS_DEP.inc(dep=self.nom, issue=issue)
            m.LATENCE_DEP.observe(time.monotonic() - debut, dep=self.nom)

    def _appel_protege(self, chemin, timeout, **kw):
        self.breaker.avant_appel()
        try:
            with self.bulkhead:
                resultat = self._appel_unique(chemin, timeout, **kw)
        except BulkheadPlein:
            self.breaker.essai_en_cours = False
            raise
        except (ConnectionError, TimeoutError):
            self.breaker.echec()
            raise
        except ErreurPermanente:
            self.breaker.succes()     # 4xx : la dépendance fonctionne
            raise
        self.breaker.succes()
        return resultat

    def appeler(self, chemin, **kw):
        """Appel avec tous les patterns (ou appel naïf si PATTERNS=off)."""
        if not self.actif:
            return self._appel_unique(chemin, self.timeout_naif, **kw)

        debut = time.monotonic()
        for i in range(self.tentatives):
            timeout = self.timeout
            if self.deadline:
                restant = self.deadline - (time.monotonic() - debut)
                if restant <= 0.02:
                    raise DeadlineDepassee(f"budget {self.deadline}s épuisé")
                timeout = min(timeout, restant)
            try:
                return self._appel_protege(chemin, timeout, **kw)
            except CircuitOuvert:
                m.APPELS_DEP.inc(dep=self.nom, issue="refus_circuit")
                raise                               # inutile de réessayer
            except (ConnectionError, TimeoutError, BulkheadPlein) as e:
                if i == self.tentatives - 1:
                    raise
                # Backoff exponentiel avec full jitter, ou Retry-After s'il est fourni.
                pause = random.uniform(0, self.backoff * 2 ** i)
                retry_after = getattr(e, "retry_after", None)
                if retry_after is not None:
                    pause = max(pause, retry_after)
                if self.deadline and time.monotonic() - debut + pause >= self.deadline:
                    raise
                m.RETRIES.inc(dep=self.nom)
                time.sleep(pause)
