"""Tests unitaires des patterns (stdlib unittest). Lancer : python -m unittest discover tests"""
import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "api"))

from rate_limit import LoadShedder, TokenBucket          # noqa: E402
from resilience import (Bulkhead, BulkheadPlein, CacheResilient, CircuitBreaker,  # noqa: E402
                        CircuitOuvert, Dependance)
import metrics                                            # noqa: E402


class TestTokenBucket(unittest.TestCase):
    def test_rafale_puis_refus(self):
        seau = TokenBucket(capacite=10, debit=5)
        self.assertEqual(sum(seau.autoriser() for _ in range(20)), 10)
        self.assertGreater(seau.attente(), 0)


class TestLoadShedder(unittest.TestCase):
    def test_reserve_prioritaire(self):
        s = LoadShedder(8, 0.25)
        self.assertEqual(sum(s.entrer() for _ in range(8)), 6)   # 6 places normales
        self.assertTrue(s.entrer(prioritaire=True))
        self.assertTrue(s.entrer(prioritaire=True))
        self.assertFalse(s.entrer(prioritaire=True))


class TestCircuitBreaker(unittest.TestCase):
    def test_cycle_complet(self):
        cb = CircuitBreaker("t1", fenetre=10, seuil=0.5, volume_min=4, delai_ouverture=0.1)
        for _ in range(4):
            cb.avant_appel()
            cb.echec()
        self.assertEqual(cb.nom_etat, "ouvert")
        with self.assertRaises(CircuitOuvert):
            cb.avant_appel()
        time.sleep(0.12)
        cb.avant_appel()                       # semi-ouvert : un essai autorisé
        self.assertEqual(cb.nom_etat, "semi_ouvert")
        with self.assertRaises(CircuitOuvert):
            cb.avant_appel()                   # un seul essai à la fois
        cb.succes()
        self.assertEqual(cb.nom_etat, "ferme")

    def test_volume_minimal(self):
        cb = CircuitBreaker("t2", fenetre=10, seuil=0.5, volume_min=10)
        for _ in range(5):
            cb.echec()
        self.assertEqual(cb.nom_etat, "ferme")


class TestBulkhead(unittest.TestCase):
    def test_plein(self):
        b = Bulkhead("t3", places=1, attente=0.01)
        with b:
            with self.assertRaises(BulkheadPlein):
                with b:
                    pass


class TestCache(unittest.TestCase):
    def test_stale(self):
        c = CacheResilient(stale_max=0.05)
        c.mettre("A1", 7)
        self.assertEqual(c.perime("A1")[0], 7)
        time.sleep(0.06)
        self.assertIsNone(c.perime("A1")[0])


class TestDependance(unittest.TestCase):
    def test_deadline_borne_la_latence(self):
        # Port fermé : chaque tentative échoue ; le budget global borne la durée totale.
        d = Dependance("t4", "http://127.0.0.1:9", timeout=0.3, tentatives=5, backoff=0.2,
                       deadline=0.4, cb={"volume_min": 100})
        debut = time.monotonic()
        with self.assertRaises((ConnectionError, TimeoutError)):
            d.appeler("/stock/A1")
        self.assertLess(time.monotonic() - debut, 0.6)


class TestMetrics(unittest.TestCase):
    def test_exposition(self):
        metrics.REQUETES.inc(route="/products", code="200")
        metrics.LATENCE.observe(0.2, route="/products", classe="2xx")
        texte = metrics.exposer()
        self.assertIn('shopflow_http_requests_total{code="200",route="/products"}', texte)
        self.assertIn('le="1.0"', texte)


if __name__ == "__main__":
    unittest.main()
