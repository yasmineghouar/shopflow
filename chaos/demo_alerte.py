"""demo_alerte.py — prouve que les alertes se déclenchent : panne longue (150 s) du stock.
Phase 1 : patterns OFF -> le SLO s'effondre -> ShopFlowSLOBurnRateRapide doit passer en « firing ».
Phase 2 : patterns ON  -> SLI préservé, mais ShopFlowCircuitOuvert signale le mode dégradé.
Lancer : python chaos/demo_alerte.py   (Prometheus sur http://localhost:9090)
"""
import json
import time
import urllib.request

import chaos

PROM = "http://localhost:9090"


def alertes():
    with urllib.request.urlopen(f"{PROM}/api/v1/alerts", timeout=3) as r:
        return [(a["labels"]["alertname"], a["labels"].get("dep", ""), a["state"])
                for a in json.loads(r.read())["data"]["alerts"]]


def phase(patterns, duree=150):
    chaos.deployer_api(patterns)
    chaos.retablir()
    ch = chaos.Charge()
    ch.lancer("legit", 12, pause=0.1)
    time.sleep(10)
    chaos.admin("stock", down=1)
    chaos.log(f"stock DOWN (patterns {'ON' if patterns else 'OFF'}) pendant {duree} s")
    vues = set()
    debut = time.monotonic()
    while time.monotonic() - debut < duree:
        time.sleep(5)
        for a in alertes():
            if a not in vues:
                vues.add(a)
                chaos.log(f"  t+{time.monotonic() - debut:5.0f} s  alerte {a[0]} {a[1]} -> {a[2]}")
    chaos.retablir()
    ch.arreter()
    return vues


if __name__ == "__main__":
    try:
        phase(False)
        phase(True)
    finally:
        chaos.retablir()
        chaos.deployer_api(True)
