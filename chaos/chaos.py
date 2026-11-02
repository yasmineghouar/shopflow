"""chaos.py — expériences de chaos engineering automatisées (suite d'experience.py du TP 9).

Chaque expérience : mesure de référence -> injection de la panne -> mesure pendant la panne
(avec critère d'arrêt automatique) -> retour à la normale -> mesure de la récupération.
Elle est jouée deux fois : patterns désactivés (« avant ») puis activés (« après »).

Utilisation :
    python chaos/chaos.py E1 E2 ...        expériences choisies (défaut : toutes)
    python chaos/chaos.py --modes apres E3  un seul mode
    python chaos/chaos.py --tag v1 E3       suffixe des fichiers de résultats (comparaison de versions)
Variables : GATEWAY_URL (défaut http://localhost:8000), GATEWAY_PORT (transmis à docker compose).
"""
import argparse
import json
import math
import os
import pathlib
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

RACINE = pathlib.Path(__file__).resolve().parents[1]
RESULTATS = RACINE / "chaos" / "results"
GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:8000")
ADMIN = {"stock": "http://localhost:8081", "reco": "http://localhost:8082",
         "payment": "http://localhost:8083"}
NORMAL = {"fail_rate": 0, "fail_after": 0, "latency": 0.05, "latency_reco": 0.05, "down": 0}

SEUIL_LATENCE = 1.0          # SLI : réponse 2xx en moins de 1 s
CRITERE_ARRET = 0.80         # arrêt si SLI < 80 % sur 10 s (comme au TP 9)
FENETRE_ARRET = 10.0
NB_SKU = 100


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# --------------------------------------------------------------------------
# Pilotage de l'infrastructure
# --------------------------------------------------------------------------
def admin(dep, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    with urllib.request.urlopen(f"{ADMIN[dep]}/admin?{q}", timeout=3) as r:
        return json.loads(r.read())


def retablir():
    for dep in ADMIN:
        admin(dep, **NORMAL)


def compose(*args, env=None):
    e = {**os.environ, **(env or {})}
    r = subprocess.run(["docker", "compose", *args], cwd=RACINE, env=e,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(r.stderr[-800:])
    return r.stdout


def deployer_api(patterns, replicas=2, extra=None):
    env = {"PATTERNS": "on" if patterns else "off", "API_REPLICAS": str(replicas), **(extra or {})}
    log(f"Déploiement API : patterns={'on' if patterns else 'off'}, réplicas={replicas}, {extra or ''}")
    compose("up", "-d", "--wait", "--force-recreate", "--scale", f"api={replicas}", "api", env=env)
    time.sleep(6)                                   # résolution DNS du gateway (valid=5s)


def conteneurs_api():
    return [c for c in compose("ps", "-q", "api").split() if c]


def tuer_processus_api(conteneur):
    """kill -9 du processus Python (tini relaie la sortie -> le conteneur meurt -> restart)."""
    subprocess.run(["docker", "exec", conteneur, "sh", "-c", "kill -9 $(cat /proc/1/task/1/children)"],
                   capture_output=True)


def sante(conteneur):
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", conteneur],
                       capture_output=True, text=True)
    return r.stdout.strip()


# --------------------------------------------------------------------------
# Générateur de charge
# --------------------------------------------------------------------------
class Charge:
    """Clients concurrents ; chaque requête est journalisée (instant, type, code, latence, ...)."""

    def __init__(self):
        self.evenements = []
        self.paniers = {}                 # clé d'idempotence -> succès final (vue client)
        self._lock = threading.Lock()
        self.stop = threading.Event()
        self.t0 = time.monotonic()
        self.threads = []

    def _requete(self, methode, chemin, client, corps=None, entetes=None):
        h = {"X-Client-Id": client, "Content-Type": "application/json", **(entetes or {})}
        data = json.dumps(corps).encode() if corps is not None else None
        req = urllib.request.Request(GATEWAY + chemin, data=data, headers=h, method=methode)
        debut = time.monotonic()
        code, entetes_rep, corps_rep = 0, {}, {}
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                code, entetes_rep, corps_rep = r.status, r.headers, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            code, entetes_rep = e.code, e.headers
            e.read()
        except Exception:
            code = 0                                     # erreur réseau / connexion coupée
        return code, time.monotonic() - debut, entetes_rep, corps_rep

    def _noter(self, groupe, route, code, latence, entetes, corps):
        ev = {"t": round(time.monotonic() - self.t0, 3), "g": groupe, "r": route, "c": code,
              "l": round(latence, 4),
              "deg": (entetes.get("X-Degraded", "non") if entetes else "non") != "non",
              "cb": entetes.get("X-Circuit-Stock", "") if entetes else "",
              "cbr": entetes.get("X-Circuit-Reco", "") if entetes else "",
              "cbp": entetes.get("X-Circuit-Payment", "") if entetes else "",
              "utile": route != "/products" or (code == 200 and corps.get("stock") is not None)}
        with self._lock:
            self.evenements.append(ev)

    def _client(self, groupe, client, pause, part_checkout):
        while not self.stop.is_set():
            if random.random() < part_checkout:
                self._checkout(groupe, client)
            else:
                sku = f"SKU{random.randint(1, NB_SKU)}"
                code, lat, h, c = self._requete("GET", f"/products/{sku}", client)
                self._noter(groupe, "/products", code, lat, h, c)
            if pause:
                time.sleep(pause * random.uniform(0.5, 1.5))

    def _checkout(self, groupe, client):
        # Un « panier » : l'utilisateur réessaie jusqu'à 3 fois en cas d'échec, avec la même clé.
        cle = str(uuid.uuid4())
        ok = False
        for _ in range(3):
            code, lat, h, c = self._requete("POST", "/checkout", client, {"montant": 42},
                                            {"Idempotency-Key": cle})
            self._noter(groupe, "/checkout", code, lat, h, c)
            if code == 201:
                ok = True
                break
            if self.stop.is_set():
                break
            try:
                attente = float(h.get("Retry-After", 0.3)) if h else 0.3
            except ValueError:
                attente = 0.3
            time.sleep(min(attente, 1.0))
        with self._lock:
            self.paniers[cle] = ok

    def lancer(self, groupe, nb, pause=0.1, part_checkout=0.15, meme_id=None):
        for i in range(nb):
            client = meme_id or f"{groupe}-{i}"
            t = threading.Thread(target=self._client, args=(groupe, client, pause, part_checkout),
                                 daemon=True)
            t.start()
            self.threads.append(t)

    def arreter(self):
        self.stop.set()
        for t in self.threads:
            t.join(timeout=12)

    def instant(self):
        return time.monotonic() - self.t0

    def sli_fenetre(self, depuis, groupe="legit"):
        with self._lock:
            evs = [e for e in self.evenements if e["t"] >= depuis and e["g"] == groupe and e["c"] != 429]
        if len(evs) < 10:
            return None
        return sum(bon(e) for e in evs) / len(evs)


def bon(e):
    return 200 <= e["c"] < 300 and e["l"] < SEUIL_LATENCE


# --------------------------------------------------------------------------
# Analyse
# --------------------------------------------------------------------------
def p95(valeurs):
    if not valeurs:
        return None
    v = sorted(valeurs)
    return v[max(0, math.ceil(0.95 * len(v)) - 1)]


def bilan(evs):
    evs = [e for e in evs if e["c"] != 429]
    n = len(evs)
    if not n:
        return {"n": 0}
    ok = [e for e in evs if 200 <= e["c"] < 300]
    return {"n": n, "sli": round(100 * sum(bon(e) for e in evs) / n, 2),
            "succes_2xx": round(100 * len(ok) / n, 2),
            "degrade": round(100 * sum(e["deg"] for e in ok) / max(1, len(ok)), 1),
            "utile": round(100 * sum(e["utile"] and bon(e) for e in evs) / n, 2),
            "erreurs_5xx": sum(500 <= e["c"] < 600 for e in evs),
            "erreurs_reseau": sum(e["c"] == 0 for e in evs),
            "p50": round(sorted(e["l"] for e in ok)[len(ok) // 2], 3) if ok else None,
            "p95": round(p95([e["l"] for e in ok]), 3) if ok else None,
            "debit_bon_par_s": None}


def serie(evs, fin):
    """SLI, débit et part dégradée seconde par seconde (pour les graphiques)."""
    pts = []
    for s in range(int(fin) + 1):
        b = [e for e in evs if s <= e["t"] < s + 1 and e["c"] != 429]
        if b:
            pts.append({"s": s, "n": len(b), "sli": round(sum(bon(e) for e in b) / len(b), 3),
                        "deg": round(sum(e["deg"] for e in b) / len(b), 3),
                        "p95": round(p95([e["l"] for e in b]), 3)})
    return pts


def detection(evs, depuis, champ="cb"):
    """Délai entre l'injection et la première réponse signalant un circuit ouvert."""
    for e in sorted(evs, key=lambda x: x["t"]):
        if e["t"] >= depuis and e[champ] == "ouvert":
            return round(e["t"] - depuis, 2)
    return None


def recuperation(evs, depuis, besoin=10):
    """Délai après le retour à la normale jusqu'à `besoin` réponses nominales consécutives
    (2xx, < 1 s, non dégradées)."""
    suite = 0
    for e in sorted((e for e in evs if e["t"] >= depuis and e["g"] == "legit"), key=lambda x: x["t"]):
        if bon(e) and not e["deg"]:
            suite += 1
            if suite >= besoin:
                return round(e["t"] - depuis, 2)
        else:
            suite = 0
    return None


# --------------------------------------------------------------------------
# Expériences
# --------------------------------------------------------------------------
EXPERIENCES = {
    "E1": {"titre": "30 % d'erreurs sur le service stock", "dep": "stock",
           "panne": lambda: admin("stock", fail_rate=0.3), "cb": "cb",
           "hypothese": "Le retry absorbe les erreurs transitoires : SLI > 99 %, aucune erreur visible."},
    "E2": {"titre": "Service stock totalement indisponible (20 s)", "dep": "stock",
           "panne": lambda: admin("stock", down=1), "cb": "cb",
           "hypothese": "Le circuit s'ouvre en < 2 s ; le cache sert la dernière valeur : SLI > 95 %."},
    "E3": {"titre": "Latence de 2 s sur le service stock", "dep": "stock",
           "panne": lambda: admin("stock", latency=2.0), "cb": "cb",
           "hypothese": "Timeout + breaker coupent la latence : p95 < 1 s et SLI > 95 %."},
    "E4": {"titre": "Recommandations lentes (3 s)", "dep": "reco",
           "panne": lambda: admin("reco", latency_reco=3.0), "cb": "cbr",
           "hypothese": "La page produit est servie sans recommandations : SLI > 99 %."},
    "E5": {"titre": "Paiement : 30 % de réponses perdues après débit", "dep": "payment",
           "panne": lambda: admin("payment", fail_after=0.3), "cb": "cbp", "paiement": True,
           "hypothese": "Retry + clé d'idempotence : aucun double débit, > 99 % des paniers payés."},
    "E6": {"titre": "Pic de trafic : client abusif + afflux soudain", "surge": True,
           "hypothese": "Rate limiting + load shedding : les clients habituels gardent un SLI > 95 % et p95 < 1 s."},
    "E7": {"titre": "Arrêt brutal (kill -9) d'une réplica de l'API", "kill": True,
           "hypothese": "Le gateway bascule sur l'autre réplica ; < 1 % d'échecs ; redémarrage auto < 15 s."},
}


def jouer(code, patterns, args):
    exp = EXPERIENCES[code]
    mode = "apres" if patterns else "avant"
    replicas = 1 if (exp.get("kill") and not patterns) else 2   # E7 « avant » : sans redondance
    # Réglages antérieurs, rejoués pour mesurer chaque correctif (section 9 du dossier).
    extra = {"v1": {"DEADLINE_STOCK": "0", "TIMEOUT_STOCK": "0.5", "LS_MAX_EN_COURS": "12"},  # client TP 9, shedder 12
             "cb1": {"CB_FENETRE": "20", "CB_SEUIL": "0.5", "CB_VOLUME_MIN": "10"}}.get(args.tag, {})              # breaker trop sensible
    deployer_api(patterns, replicas, extra)
    retablir()
    admin("payment", reset=1)

    ch = Charge()
    ch.lancer("legit", 12, pause=0.1)
    log(f"{code} [{mode}] référence {args.ref} s")
    time.sleep(args.ref)

    t_panne = ch.instant()
    arret, surge, info = False, None, {}
    log(f"{code} [{mode}] injection : {exp['titre']}")
    if exp.get("surge"):
        surge = Charge()
        surge.t0 = ch.t0
        surge.evenements = ch.evenements
        surge._lock = ch._lock
        surge.lancer("abusif", 25, pause=0, part_checkout=0, meme_id="client-abusif")
        surge.lancer("afflux", 60, pause=0.02, part_checkout=0.1)
    elif exp.get("kill"):
        cible = conteneurs_api()[0]
        tuer_processus_api(cible)
        info["conteneur"] = cible[:12]
    else:
        exp["panne"]()

    fin_panne = t_panne + args.panne
    while ch.instant() < fin_panne:
        time.sleep(0.5)
        if exp.get("kill"):
            continue                                   # rien à annuler : on observe
        if ch.instant() - t_panne >= FENETRE_ARRET:
            sli = ch.sli_fenetre(ch.instant() - FENETRE_ARRET)
            if sli is not None and sli < CRITERE_ARRET:
                log(f"{code} [{mode}] CRITÈRE D'ARRÊT : SLI {sli:.1%} < 80 % sur 10 s -> annulation")
                arret = True
                break
    t_retour = ch.instant()
    if surge:
        surge.arreter()
    retablir()
    log(f"{code} [{mode}] retour à la normale, mesure de la récupération {args.recup} s")

    if exp.get("kill"):
        # Temps de redémarrage : jusqu'à ce que le conteneur tué soit de nouveau « healthy ».
        debut = time.monotonic()
        while time.monotonic() - debut < 60 and sante(info["conteneur"]) != "healthy":
            time.sleep(0.5)
        info["redemarrage_s"] = round(time.monotonic() - debut + (t_retour - t_panne), 1)

    time.sleep(args.recup)
    t_fin = ch.instant()
    ch.arreter()

    evs = list(ch.evenements)
    legit = [e for e in evs if e["g"] == "legit"]
    phases = {"reference": [e for e in legit if e["t"] < t_panne],
              "panne": [e for e in legit if t_panne <= e["t"] < t_retour],
              "recuperation": [e for e in legit if e["t"] >= t_retour]}
    resultat = {"experience": code, "titre": exp["titre"], "hypothese": exp["hypothese"],
                "mode": mode, "tag": args.tag, "replicas": replicas,
                "t_panne": round(t_panne, 2), "t_retour": round(t_retour, 2), "t_fin": round(t_fin, 2),
                "arret_securite": arret,
                "bilans": {k: bilan(v) for k, v in phases.items()},
                "detection_s": detection(legit, t_panne, exp["cb"]) if exp.get("cb") else None,
                "recuperation_s": recuperation(evs, t_retour),
                "serie": serie(legit, t_fin), **info}
    if exp.get("surge"):
        for g in ("abusif", "afflux"):
            sous = [e for e in evs if e["g"] == g]
            resultat[f"{g}_codes"] = {str(c): sum(e["c"] == c for e in sous)
                                      for c in sorted({e["c"] for e in sous})}
        chk = [e for e in evs if e["r"] == "/checkout" and t_panne <= e["t"] < t_retour]
        resultat["checkout_succes_pendant"] = round(100 * sum(e["c"] == 201 for e in chk) / max(1, len(chk)), 1)
        prod = [e for e in evs if e["r"] == "/products" and t_panne <= e["t"] < t_retour and e["g"] != "abusif"]
        resultat["products_succes_pendant"] = round(100 * sum(e["c"] == 200 for e in prod) / max(1, len(prod)), 1)
    if exp.get("paiement"):
        etat = admin("payment")
        succes = sum(ch.paniers.values())
        resultat["paiement"] = {"paniers": len(ch.paniers), "paniers_payes_vus_client": succes,
                                "debits": etat["charges"],
                                "debits_en_trop": etat["charges"] - succes,
                                "taux_paniers_payes": round(100 * succes / max(1, len(ch.paniers)), 2)}
    if exp.get("kill"):
        resultat["echecs_pendant_kill"] = sum(e["c"] == 0 or e["c"] >= 500 for e in evs
                                              if t_panne <= e["t"] < t_retour + 20)

    nom = f"{code}_{mode}{'_' + args.tag if args.tag else ''}.json"
    (RESULTATS / nom).write_text(json.dumps(resultat, ensure_ascii=False, indent=1), encoding="utf-8")
    b = resultat["bilans"]["panne"]
    log(f"{code} [{mode}] SLI panne {b.get('sli')} % | p95 {b.get('p95')} s | dégradé {b.get('degrade')} % "
        f"| détection {resultat['detection_s']} s | récupération {resultat['recuperation_s']} s "
        f"| arrêt {arret} {resultat.get('paiement', '')}")
    return resultat


def main():
    p = argparse.ArgumentParser()
    p.add_argument("experiences", nargs="*", default=list(EXPERIENCES))
    p.add_argument("--modes", default="avant,apres")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", type=float, default=15)
    p.add_argument("--panne", type=float, default=20)
    p.add_argument("--recup", type=float, default=20)
    args = p.parse_args()
    RESULTATS.mkdir(parents=True, exist_ok=True)
    try:
        for code in args.experiences:
            for mode in args.modes.split(","):
                jouer(code.upper(), mode == "apres", args)
    finally:
        retablir()
        deployer_api(True, 2)
        log("Configuration nominale rétablie (patterns actifs, 2 réplicas).")


if __name__ == "__main__":
    main()
