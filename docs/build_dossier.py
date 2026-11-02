"""build_dossier.py — génère le dossier d'architecture (HTML puis PDF via Chrome/Edge headless).
Lancer après chaos/rapport.py :  python docs/build_dossier.py
"""
import base64
import html
import json
import pathlib
import shutil
import subprocess

DOCS = pathlib.Path(__file__).resolve().parent
RACINE = DOCS.parent
FIG = DOCS / "figures"
S = json.loads((RACINE / "chaos" / "results" / "synthese.json").read_text(encoding="utf-8"))
GW1 = json.loads((RACINE / "chaos" / "results" / "E1_avant_gw1.json").read_text(encoding="utf-8"))
NOM_PDF = "Dossier_Architecture_ShopFlow_Yasmine_Ghouar.pdf"


def img(nom, largeur="100%", legende=""):
    f = FIG / nom
    mime = "image/svg+xml" if nom.endswith(".svg") else "image/png"
    b64 = base64.b64encode(f.read_bytes()).decode()
    cap = f"<figcaption>{legende}</figcaption>" if legende else ""
    return f'<figure><img src="data:{mime};base64,{b64}" style="width:{largeur}">{cap}</figure>'


def v(cle, *chemin, defaut="—"):
    x = S.get(cle)
    for c in chemin:
        if x is None:
            return defaut
        x = x.get(c) if isinstance(x, dict) else None
    return defaut if x is None else x


def fr(x, dec=1):
    if isinstance(x, (int, float)):
        return f"{x:.{dec}f}".replace(".", ",")
    return x


def table(entetes, lignes, classe=""):
    t = f'<table class="{classe}"><thead><tr>' + "".join(f"<th>{h}</th>" for h in entetes) + "</tr></thead><tbody>"
    for l in lignes:
        t += "<tr>" + "".join(f"<td>{c}</td>" for c in l) + "</tr>"
    return t + "</tbody></table>"


def code(fichier, debut=None, fin=None):
    lignes = (RACINE / fichier).read_text(encoding="utf-8").splitlines()
    extrait = "\n".join(lignes[(debut or 1) - 1:fin])
    return f'<pre><code>{html.escape(extrait)}</code></pre>'


# ---------------------------------------------------------------------------
# Contenu
# ---------------------------------------------------------------------------
EXP = ["E1", "E2", "E3", "E4", "E5", "E6", "E7"]


def tableau_resultats():
    lignes = []
    for e in EXP:
        for mode, lib in (("avant", "sans"), ("apres", "avec")):
            k = f"{e}_{mode}"
            b = v(k, "bilans", "panne")
            if b == "—":
                continue
            lignes.append([f"<b>{e}</b>" if mode == "avant" else "", lib,
                           fr(v(k, "bilans", "reference", "sli"), 1), f"<b>{fr(b['sli'], 1)}</b>",
                           fr(b["degrade"], 0), fr(b["p95"], 2), fr(v(k, "detection_s"), 1),
                           fr(v(k, "recuperation_s"), 1), "oui" if v(k, "arret_securite") is True else "non"])
    return table(["Exp.", "Patterns", "SLI réf. %", "SLI panne %", "dégradé %", "p95 panne (s)",
                  "détection (s)", "récup. (s)", "arrêt"], lignes, "num")


def fiche(e, hypothese_validee, rayon, actions, notes=""):
    av, ap = f"{e}_avant", f"{e}_apres"
    t = v(ap, "titre")
    ba, bp = v(av, "bilans", "panne"), v(ap, "bilans", "panne")
    ref = v(ap, "bilans", "reference")
    rows = [
        ["État stable (SLI mesuré)", f"SLI de référence {fr(ref['sli'], 1)} % (2xx en &lt; 1 s), p95 {fr(ref['p95'], 2)} s"],
        ["Hypothèse", v(ap, "hypothese")],
        ["Panne injectée", t + " — durée 20 s, 12 clients réguliers (≈ 60 req/s)"],
        ["Rayon d'impact", rayon],
        ["Critère d'arrêt", "SLI &lt; 80 % sur 10 s glissantes → panne annulée automatiquement"],
        ["Résultat sans patterns", f"SLI {fr(ba['sli'], 1)} %, p95 {fr(ba['p95'], 2)} s, 5xx/réseau "
                                   f"{ba['erreurs_5xx'] + ba['erreurs_reseau']}" +
         (" — <b>arrêt de sécurité déclenché</b>" if v(av, "arret_securite") is True else "")],
        ["Résultat avec patterns", f"SLI <b>{fr(bp['sli'], 1)} %</b>, p95 {fr(bp['p95'], 2)} s, "
                                   f"{fr(bp['degrade'], 0)} % de réponses dégradées, détection "
                                   f"{fr(v(ap, 'detection_s'), 1)} s, récupération {fr(v(ap, 'recuperation_s'), 1)} s" +
         (" — arrêt de sécurité déclenché" if v(ap, "arret_securite") is True else "")],
        ["Hypothèse validée ?", hypothese_validee],
        ["Actions correctives", actions],
    ]
    if notes:
        rows.insert(7, ["Mesures complémentaires", notes])
    return f'<div class="fiche"><h4>Expérience {e} — {t}</h4>' + table(["", ""], rows, "fiche-t") + "</div>"


CSS = """
@page { size: A4; margin: 17mm 16mm 18mm 16mm;
  @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; color: #64748b; } }
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', Calibri, Arial, sans-serif; font-size: 9.4pt; line-height: 1.38; color: #1e293b; }
h1 { font-size: 22pt; margin: 0 0 4mm; color: #0f172a; }
h2 { font-size: 13pt; color: #0f766e; border-bottom: 2px solid #0f766e; padding-bottom: 1.2mm; margin: 5mm 0 2.5mm;
     break-after: avoid; }
h3 { break-after: avoid; }
.saut { break-before: page; margin-top: 0; }
h2.suite { break-before: auto; margin-top: 6mm; }
h3 { font-size: 11pt; color: #0f172a; margin: 4.5mm 0 1.5mm; }
h4 { font-size: 10pt; margin: 0 0 1.5mm; color: #0f766e; }
p { margin: 0 0 2.2mm; text-align: justify; }
ul { margin: 0 0 2.5mm; padding-left: 5mm; } li { margin-bottom: 0.8mm; }
table { border-collapse: collapse; width: 100%; margin: 1.5mm 0 3mm; font-size: 8.1pt; break-inside: avoid; }
th { background: #0f766e; color: #fff; text-align: left; padding: 1.1mm 1.5mm; font-weight: 600; }
td { border-bottom: 1px solid #e2e8f0; padding: 0.8mm 1.5mm; vertical-align: top; }
tr:nth-child(even) td { background: #f8fafc; }
table.num td:nth-child(n+3) { text-align: right; font-variant-numeric: tabular-nums; }
.fiches { columns: 2; column-gap: 4mm; }
.fiche { border: 1px solid #cbd5e1; border-left: 3px solid #0f766e; border-radius: 3px; padding: 1.8mm 2mm 0;
         margin: 0 0 3mm; break-inside: avoid; }
table.fiche-t { font-size: 7.4pt; margin: 0 0 1.5mm; } table.fiche-t td { padding: 0.5mm 1mm; }
table.fiche-t thead { display: none; }
table.fiche-t td:first-child { width: 27%; font-weight: 600; color: #334155; }
table.fiche-t tr:nth-child(even) td { background: transparent; }
figure { margin: 2mm 0 3.5mm; text-align: center; break-inside: avoid; }
figcaption { font-size: 8.5pt; color: #64748b; margin-top: 1mm; }
pre { background: #0f172a; color: #e2e8f0; font-size: 7pt; line-height: 1.35; padding: 2.5mm 3mm; border-radius: 3px;
      white-space: pre-wrap; break-inside: avoid; margin: 1.5mm 0 3mm; }
code { font-family: Consolas, 'Cascadia Mono', monospace; }
p code, li code, td code { background: #f1f5f9; color: #0f172a; padding: 0 1mm; border-radius: 2px; font-size: 8.8pt; }
.encadre { background: #f0fdfa; border: 1px solid #99f6e4; border-radius: 3px; padding: 2.5mm 3.5mm; margin: 2mm 0 3.5mm;
           break-inside: avoid; }
.alerte { background: #fff7ed; border-color: #fdba74; }
.cols { display: flex; gap: 5mm; } .cols > div { flex: 1; }
.couverture { height: 258mm; break-after: page; display: flex; flex-direction: column; justify-content: space-between; }
.couverture .bandeau { background: #0f766e; color: #fff; padding: 9mm 9mm 8mm; border-radius: 4px; }
.couverture .bandeau h1 { color: #fff; font-size: 26pt; margin: 2mm 0 3mm; }
.couverture .sur { font-size: 10pt; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.85; }
.kpis { display: flex; gap: 4mm; margin: 4mm 0; } .kpi { flex: 1; border: 1px solid #cbd5e1; border-radius: 4px; padding: 3mm; }
.kpi b { display: block; font-size: 17pt; color: #0f766e; } .kpi span { font-size: 8.5pt; color: #475569; }
.toc li { margin-bottom: 1.2mm; }
.petit { font-size: 8.5pt; color: #475569; }
"""


def construire():
    e2a, e2b = v("E2_avant", "bilans", "panne"), v("E2_apres", "bilans", "panne")
    e5a, e5b = v("E5_avant", "paiement"), v("E5_apres", "paiement")
    e7a, e7b = S.get("E7_avant", {}), S.get("E7_apres", {})
    e3v1, e6v1 = v("E3_apres_v1", "bilans", "panne"), v("E6_apres_v1", "bilans", "panne")
    sli_avant = [v(f"{e}_avant", "bilans", "panne", "sli") for e in EXP]
    sli_apres = [v(f"{e}_apres", "bilans", "panne", "sli") for e in EXP]
    moy_av = sum(sli_avant) / len(sli_avant)
    moy_ap = sum(sli_apres) / len(sli_apres)
    gw_b = GW1["bilans"]["panne"]

    corps = f"""
<section class="couverture">
 <div>
  <div class="bandeau">
   <div class="sur">Patterns de résilience · M2 LDF · Projet final</div>
   <h1>ShopFlow — Architecture résiliente complète</h1>
   <div>Dossier d'architecture : contexte, risques, patterns, observabilité, chaos engineering, déploiement</div>
  </div>
  <p style="margin-top:7mm"><b>Étudiante :</b> Yasmine Ghouar &nbsp;·&nbsp; <b>Formatrice :</b> Suzanne KOKOS &nbsp;·&nbsp;
  <b>Date :</b> 2 novembre 2026</p>
  <p>Ce dossier prolonge les TP 7 à 10 (rate limiting, health checks, chaos engineering, déploiement) : le service
  <code>shopflow_api</code> devient le cœur d'une architecture de cinq services HTTP, instrumentée avec Prometheus et
  Grafana, et éprouvée par sept expériences de chaos automatisées, chacune jouée <b>sans</b> puis <b>avec</b> patterns.
  Tous les chiffres de ce document proviennent de mesures réelles (fichiers JSON dans <code>chaos/results/</code>).</p>
  <div class="kpis">
   <div class="kpi"><b>{fr(moy_av, 1)} % → {fr(moy_ap, 1)} %</b><span>SLI moyen pendant les 7 pannes, sans → avec patterns</span></div>
   <div class="kpi"><b>10</b><span>patterns implémentés, chacun relié à un risque de l'AMDEC</span></div>
   <div class="kpi"><b>{e5a.get('debits_en_trop', '—') if isinstance(e5a, dict) else '—'} → {e5b.get('debits_en_trop', '—') if isinstance(e5b, dict) else '—'}</b><span>paiements débités sans confirmation (E5), sans → avec idempotence</span></div>
   <div class="kpi"><b>3 + 1</b><span>faiblesses découvertes par le chaos et corrigées (re-mesurées) + 1 hypothèse invalidée</span></div>
  </div>
 </div>
 <div>
  <h3>Sommaire</h3>
  <ol class="toc">
   <li>Contexte, objectifs et SLO</li><li>Architecture</li>
   <li>Analyse des risques : dépendances, disponibilité théorique, SPOF, AMDEC</li>
   <li>Patterns de résilience et paramètres justifiés</li><li>Observabilité : métriques, tableau de bord, alertes</li>
   <li>Déploiement : Docker Compose et Kubernetes</li><li>Chaos engineering : protocole et résultats</li>
   <li>Fiches d'expérience</li><li>Faiblesses découvertes et corrections (avant / après)</li>
   <li>Limites et perspectives</li>
  </ol>
  <p class="petit">Dépôt : <code>projet_final/</code> — tout lancer : <code>docker compose up -d --build</code> · tests :
  <code>python -m unittest discover tests</code> · expériences : <code>python chaos/chaos.py</code> puis
  <code>python chaos/rapport.py</code> · ce dossier : <code>python docs/build_dossier.py</code> · détails : <code>README.md</code>.</p>
 </div>
</section>

<h2>1. Contexte, objectifs et SLO</h2>
<p>ShopFlow est une boutique en ligne simplifiée. Deux parcours comptent pour l'utilisateur : <b>consulter une fiche produit</b>
(stock disponible et recommandations) et <b>payer sa commande</b>. Ces parcours reposent sur trois services tiers que l'on ne
maîtrise pas : le stock, le moteur de recommandations et le prestataire de paiement. Ils sont simulés par le
<code>flaky_service</code> du kit du jour 2, dont on peut piloter les pannes (erreurs, latence, indisponibilité, réponses perdues).</p>
<p>L'objectif du projet est de démontrer, preuves à l'appui, que l'application <b>continue de rendre un service acceptable</b>
face à des pannes réalistes, et qu'elle est <b>prête à être exploitée</b> : déploiement reproductible, sondes de santé,
métriques, tableau de bord et alertes.</p>
<h3>Indicateur et objectif de niveau de service</h3>
<div class="encadre"><b>SLI</b> : part des requêtes métier (<code>GET /products/…</code>, <code>POST /checkout</code>) servies avec un code
<b>2xx en moins de 1 s</b>, réponses dégradées comprises (définition du TP 9). Les 429 renvoyés volontairement à un client qui
dépasse son quota sont exclus : c'est le comportement attendu.<br>
<b>SLO</b> : 99 % sur 30 jours glissants, soit un <b>budget d'erreur de 1 %</b> (≈ 7 h 18 min par mois).<br>
<b>Suivi séparé de la qualité</b> : part de réponses dégradées (stock issu du cache, page sans recommandations). Le TP 9 a montré
qu'un SLI « servi » peut rester haut alors que la dépendance est entièrement en panne : on suit donc aussi la part dégradée.</div>
<h3>Exigences du projet et réponse apportée</h3>
{table(["Exigence", "Réalisation"], [
        ["≥ 3 services HTTP dont une dépendance instable", "5 services : gateway NGINX, <code>shopflow-api</code> (2 réplicas), stock, reco, payment (3 dépendances instables)"],
        ["Analyse des risques", "Graphe de dépendances, disponibilité théorique, SPOF, AMDEC à 12 modes de défaillance (section 3)"],
        ["≥ 6 patterns reliés à l'AMDEC", "10 patterns : timeout, retry, circuit breaker, bulkhead, fallback, cache résilient, dégradation gracieuse, rate limiting, load shedding, health checks"],
        ["Observabilité", "≥ 1 métrique Prometheus par pattern, tableau de bord Grafana provisionné, alertes SLO multi-fenêtres"],
        ["≥ 5 expériences de chaos", "7 expériences automatisées, hypothèse, critère d'arrêt, résultats avant / après"],
        ["Déploiement", "Docker Compose (une commande) ; manifestes Kubernetes avec 3 sondes et PodDisruptionBudget (bonus)"],
    ])}

<h2>2. Architecture</h2>
{img("architecture.svg", "92%", "Figure 1 — Architecture de ShopFlow : flux HTTP (traits pleins) et collecte des métriques (pointillés)")}
<h3>Rôle de chaque service</h3>
{table(["Service", "Technologie", "Responsabilité", "Criticité"], [
        ["gateway", "NGINX 1.27", "Point d'entrée unique ; répartit sur les réplicas (DNS Docker réévalué toutes les 5 s) ; bascule sur l'autre réplica si une connexion échoue", "Critique"],
        ["shopflow-api ×2", "Python 3.12, stdlib", "<code>GET /products/&lt;sku&gt;</code> (stock + reco), <code>POST /checkout</code> (paiement), sondes, <code>/metrics</code>. Porte tous les patterns", "Critique"],
        ["stock", "flaky_service", "Quantité disponible par SKU. Dépendance critique mais <b>tolérante à la fraîcheur</b> : une valeur de quelques secondes reste utile", "Critique, avec repli"],
        ["reco", "flaky_service", "Recommandations associées au produit. <b>Optionnelles</b> : la page reste utile sans elles", "Optionnelle"],
        ["payment", "flaky_service", "Débit de la commande. Aucune valeur de repli possible ; opération <b>non idempotente</b> par nature", "Critique, sans repli"],
        ["Prometheus / Grafana", "v2.54 / v11.2", "Collecte (découverte DNS des réplicas), règles SLO, alertes ; tableau de bord", "Hors chemin des requêtes"],
    ])}
<h3>Chaîne de traitement d'une requête dans l'API</h3>
<p>À l'entrée, chaque requête traverse : <b>rate limiting</b> (token bucket par <code>X-Client-Id</code>) → <b>load shedding</b>
(file d'attente bornée, places réservées au checkout) → <b>capacité de l'instance</b> (8 workers, qui simulent un pool de connexions).
À la sortie, chaque appel à une dépendance est enveloppé, dans l'ordre vu au jour 2 :
<code>fallback( retry( circuit_breaker( bulkhead( appel_http(timeout) ) ) ) )</code>, avec en plus un <b>budget de temps global</b>
(deadline) partagé par toutes les tentatives. La variable <code>PATTERNS=off</code> désactive tous ces mécanismes : timeout naïf de
10 s, aucun retry, aucun repli. C'est la configuration « avant » des expériences.</p>

<h2>3. Analyse des risques</h2>
<h3>3.1 Graphe de dépendances</h3>
<div class="cols"><div>
<p><b>Page produit</b> : client → gateway → API → <b>stock</b> (requis) + <b>reco</b> (optionnelle).<br>
<b>Checkout</b> : client → gateway → API → <b>payment</b> (requis, non idempotent).</p>
<p>Sans patterns, toutes les flèches sont des dépendances <b>dures en série</b> : la page produit tombe si la reco tombe, alors que
les recommandations n'ont aucune valeur critique. Avec patterns, la reco devient une dépendance <b>souple</b> (dégradation) et le
stock une dépendance <b>dure mais avec repli</b> (cache de la dernière valeur connue).</p>
</div><div>
{table(["Composant", "Dispo. supposée", "Justification"], [
        ["gateway", "99,9 %", "processus simple, sans état"],
        ["réplica API", "99,5 %", "crashs, déploiements"],
        ["stock", "99,0 %", "dépendance instable"],
        ["reco", "98,0 %", "service non critique, moins soigné"],
        ["payment", "99,0 %", "prestataire externe"],
        ["couverture du cache", "95 %", "SKU déjà consultés &lt; 5 min"],
    ])}
</div></div>
<h3>3.2 Disponibilité théorique</h3>
{table(["Parcours", "Sans patterns (série, 1 réplica)", "Avec patterns", "Indisponibilité / mois"], [
        ["Page produit", "A<sub>gw</sub>·A<sub>api</sub>·A<sub>stock</sub>·A<sub>reco</sub> = 0,999 × 0,995 × 0,99 × 0,98 = <b>96,44 %</b>",
         "A<sub>gw</sub> · [1−(1−A<sub>api</sub>)²] · [1−(1−A<sub>stock</sub>)(1−0,95)] = 0,999 × 0,999975 × 0,9995 = <b>99,85 %</b>",
         "26,0 h → 1,1 h"],
        ["Checkout", "0,999 × 0,995 × 0,99 = <b>98,41 %</b>", "0,999 × 0,999975 × 0,99 = <b>98,90 %</b>", "11,6 h → 8,0 h"],
    ])}
<p>Le calcul montre où les patterns agissent : la redondance de l'API et le cache font passer la page produit de 96,4 % à 99,85 %,
et la dégradation retire la reco de la chaîne. En revanche, le <b>checkout reste borné par la disponibilité du paiement</b> (99 %) :
le retry corrige les erreurs <i>transitoires</i>, pas une panne franche du prestataire, et aucun repli n'est possible pour un débit.
Le checkout ne peut donc pas tenir 99 % si le prestataire est lui-même à 99 %. C'est une limite assumée (section 10).</p>
<h3>3.3 Points de défaillance uniques (SPOF)</h3>
<ul>
<li><b>gateway NGINX</b> (instance unique) : sa perte coupe tout. En Kubernetes, il est remplacé par un Service et un Ingress répliqués.</li>
<li><b>payment</b> : critique, sans repli. Atténuation : circuit breaker et réponse 503 + <code>Retry-After</code> rapides (on n'attend pas 10 s), alerte.</li>
<li><b>hôte Docker unique</b> en Compose : les 2 réplicas partagent la même machine (question 3 du TP 10). Kubernetes répartit les pods sur des nœuds et des zones.</li>
<li><b>stock</b> : SPOF de données, atténué par le cache stale-if-error (≤ 5 min) ; un SKU jamais consulté reste sans valeur (« stock inconnu »).</li>
<li>Prometheus et Grafana ne sont <b>pas</b> sur le chemin des requêtes : leur perte aveugle l'exploitation sans couper le service.</li>
</ul>
<h3>3.4 AMDEC</h3>
<p>Gravité (G), occurrence (O) et non-détection (D) sont notées de 1 à 10 ; criticité C = G × O × D. La colonne C' donne la
criticité estimée <b>après</b> mise en place des patterns, que les expériences de la section 7 viennent vérifier.</p>
{table(["#", "Mode de défaillance", "Effet sans protection", "G", "O", "D", "C", "Pattern(s)", "C'", "Exp."], [
        ["R1", "Erreurs transitoires du stock (503)", "page produit en erreur", 6, 7, 3, 126, "retry + backoff exponentiel + jitter", 18, "E1"],
        ["R2", "Stock indisponible", "toutes les pages en erreur", 8, 4, 2, 64, "circuit breaker + cache résilient", 16, "E2"],
        ["R3", "Stock lent (latence)", "threads bloqués, saturation, panne en cascade", 8, 5, 6, 240, "timeout + deadline + bulkhead + breaker", 32, "E3"],
        ["R4", "Reco lente ou en panne", "page produit lente ou en erreur", 5, 6, 5, 150, "dégradation gracieuse + timeout court + bulkhead", 15, "E4"],
        ["R5", "Paiement : réponse perdue après débit", "double débit au réessai, ou commande « perdue »", 9, 3, 8, 216, "retry + clé d'idempotence de bout en bout", 27, "E5"],
        ["R6", "Paiement indisponible", "clients bloqués 10 s, threads épuisés", 9, 3, 3, 81, "circuit breaker + 503 Retry-After + alerte", 54, "E5"],
        ["R7", "Client abusif / robot", "capacité monopolisée, latence pour tous", 6, 5, 4, 120, "rate limiting par client (429)", 24, "E6"],
        ["R8", "Pic de trafic légitime", "files d'attente, latence &gt; SLO pour tous", 7, 4, 5, 140, "load shedding prioritaire (503)", 42, "E6"],
        ["R9", "Crash d'une instance API", "requêtes en erreur jusqu'au redémarrage", 7, 3, 3, 63, "redondance + health checks + restart", 21, "E7"],
        ["R10", "Arrêt / déploiement coupant des requêtes", "erreurs à chaque mise en production", 5, 6, 5, 150, "readiness + drain 5 s, rolling update, PDB", 20, "TP 8/10"],
        ["R11", "Gateway qui éjecte des instances saines", "erreurs amplifiées, panne totale", 9, 3, 7, 189, "bascule sur erreurs de connexion seulement + alerte", 27, "E1*"],
        ["R12", "Tempête de retries", "charge ×3 sur une dépendance déjà fragile", 7, 4, 6, 168, "retries bornés, jitter, deadline, breaker", 28, "E1, E3"],
    ], "num")}
<p class="petit">* R11 n'était pas dans l'AMDEC initiale : il a été <b>découvert</b> par l'expérience E1 (section 9).</p>

<h2>4. Patterns de résilience et paramètres justifiés</h2>
{table(["Pattern", "Où", "Paramètres", "Justification", "Risque"], [
        ["Timeout", "client.py, chaque appel", "stock 0,3 s · reco 0,25 s · payment 1 s", "p99 nominal du stock ≈ 0,08 s : 0,3 s laisse 4× de marge. Reco plus courte car optionnelle. Payment plus long car rare et coûteux à abandonner", "R3, R4"],
        ["Deadline (budget global)", "resilience.Dependance", "stock 0,8 s · payment 2,5 s", "Les tentatives successives ne doivent jamais dépasser le SLO de 1 s (correctif issu de E3, section 9)", "R3, R12"],
        ["Retry", "resilience.Dependance", "3 tentatives, backoff 0,05·2<sup>i</sup> avec full jitter, respecte Retry-After", "30 % d'erreurs indépendantes → 0,3³ = 2,7 % d'échec résiduel ; le jitter évite la synchronisation des clients (TP 3, TP 7)", "R1, R5"],
        ["Circuit breaker", "resilience.CircuitBreaker", "fenêtre 20 appels, ≥ 50 % d'échecs, volume min. 10, ouvert 5 s, 1 essai en semi-ouvert", "Taux d'échec plutôt que compteur consécutif : insensible au bruit (30 % d'erreurs ne l'ouvrent pas, une panne franche l'ouvre en moins d'une seconde)", "R2, R3, R6"],
        ["Bulkhead", "resilience.Bulkhead", "stock 10 · reco 4 · payment 6 places, attente 50 ms", "Une dépendance lente ne peut pas occuper plus que sa part des 8 workers : la reco (4) ne peut jamais bloquer le stock", "R3, R4"],
        ["Fallback", "page_produit, checkout", "stock → cache ; reco → [] ; payment → 503 + Retry-After", "Repli adapté à la valeur métier de chaque donnée", "R2, R4, R6"],
        ["Cache résilient", "resilience.CacheResilient", "stale-if-error, âge max. 300 s", "Une quantité vieille de quelques minutes est préférable à une erreur ; la donnée nominale reste toujours fraîche", "R2"],
        ["Dégradation gracieuse", "page_produit", "en-tête <code>X-Degraded</code>, champ <code>degrade</code>", "La page reste utile sans reco ; le client sait que la réponse est dégradée", "R4"],
        ["Rate limiting", "rate_limit.TokenBucket (TP 7)", "par client : 20 jetons, 10 jetons/s ; 429 + Retry-After", "Un utilisateur réel fait ≈ 1 à 5 req/s : 10/s avec une rafale de 20 ne gêne que les robots", "R7"],
        ["Load shedding", "rate_limit.LoadShedder (TP 7)", "40 requêtes en cours par réplica, 25 % réservées au checkout ; 503 + Retry-After: 1", "Loi de Little : 8 workers × (0,6 s de budget d'attente / 0,12 s de service) ≈ 40 (recalibré après E6, section 9)", "R8"],
        ["Health checks", "health.py (TP 8)", "startup (3 s), readiness locale, liveness processus, drain 5 s sur SIGTERM", "La readiness <b>n'inclut plus</b> les dépendances partagées : sinon toutes les instances quitteraient le pool ensemble (TP 8, question 2)", "R9, R10"],
    ])}
<h3>Idempotence du paiement</h3>
<p>Le client fournit une clé <code>Idempotency-Key</code> par panier (générée par l'API s'il n'en fournit pas). L'API la transmet au
prestataire à chaque tentative, qu'elle vienne du retry interne ou d'un réessai de l'utilisateur. Le prestataire renvoie le paiement
déjà enregistré au lieu de débiter une seconde fois. Sans cette clé, réessayer un POST dont la réponse a été perdue revient à
<b>débiter deux fois</b> (expérience E5).</p>

<h2>5. Observabilité</h2>
<h3>5.1 Métriques exposées (<code>GET /metrics</code>, format Prometheus)</h3>
<p>Le module <code>metrics.py</code> (bibliothèque standard uniquement) expose des compteurs, des jauges et des histogrammes.
Prometheus découvre chaque réplica par le DNS Docker (<code>dns_sd_configs</code> sur le nom de service <code>api</code>), toutes les 5 s.</p>
{table(["Pattern", "Métrique(s)"], [
        ["SLI / latence", "<code>shopflow_http_requests_total{route,code}</code>, <code>shopflow_http_request_duration_seconds{route,classe}</code> (histogramme)"],
        ["Timeout / retry", "<code>shopflow_timeouts_total{dep}</code>, <code>shopflow_retries_total{dep}</code>, <code>shopflow_dependency_calls_total{dep,issue}</code>"],
        ["Circuit breaker", "<code>shopflow_circuit_state{dep}</code> (0/1/2), <code>shopflow_circuit_transitions_total{dep,vers}</code>"],
        ["Bulkhead", "<code>shopflow_bulkhead_in_use{dep}</code>, <code>shopflow_bulkhead_rejected_total{dep}</code>"],
        ["Fallback / cache / dégradation", "<code>shopflow_fallback_total{dep,type}</code>, <code>shopflow_cache_events_total</code>, <code>shopflow_degraded_responses_total</code>"],
        ["Rate limiting / load shedding", "<code>shopflow_rate_limited_total{route}</code>, <code>shopflow_load_shed_total{route,priorite}</code>, <code>shopflow_inflight_requests</code>"],
        ["Health checks", "<code>shopflow_ready</code>, <code>up{job=&quot;shopflow-api&quot;}</code>, <code>shopflow_patterns_enabled</code>"],
    ])}
<h3>5.2 Tableau de bord Grafana</h3>
{img("grafana.png", "80%", "Figure 2 — Tableau de bord « ShopFlow — Résilience &amp; SLO » (provisionné automatiquement), capturé pendant la campagne d'expériences")}
<h3>5.3 Règles d'alerte sur le SLO</h3>
<p>Des règles d'enregistrement calculent le SLI sur 1 min, 5 min et 1 h, puis le <b>taux de consommation du budget</b>
(burn rate = taux d'erreur / 1 %). On applique la méthode multi-fenêtres : une fenêtre longue garantit que le problème est
significatif, une fenêtre courte que l'alerte retombe vite une fois le problème résolu. Un burn rate de 14,4 consomme 2 % du budget
mensuel en une heure (fenêtres réduites à 5 min / 1 min pour rester observables à l'échelle d'un TP).</p>
{code("observability/prometheus/alerts.yml", 25, 35)}
<p>Trois alertes complètent le SLO : <code>ShopFlowCircuitOuvert</code> (dépendance en panne, service dégradé),
<code>ShopFlowInstanceIndisponible</code> (réplica injoignable) et <code>ShopFlowDelestageEleve</code> (&gt; 5 % de 503 :
la capacité est insuffisante).</p>
__ALERTES__

<h2>6. Déploiement</h2>
<h3>6.1 Docker Compose (obligatoire) — une commande</h3>
<p><code>docker compose up -d --build</code> construit deux images (API et dépendances : Python <i>slim</i>, utilisateur non root
<code>uid 10001</code>, <code>CMD</code> en forme exec, <code>HEALTHCHECK</code>) et démarre 8 conteneurs. Quelques choix notables :</p>
<ul>
<li><code>depends_on: condition: service_healthy</code> : l'API attend que ses dépendances soient saines, et le gateway attend l'API ;</li>
<li><code>init: true</code> : tini en PID 1 relaie SIGTERM (drain de 5 s) et permet un vrai <code>kill -9</code> du processus, suivi
d'un redémarrage par <code>restart: unless-stopped</code> (un <code>docker kill</code>, lui, est vu comme un arrêt manuel et ne
redémarre pas, ce qui expliquait l'observation du TP 10) ;</li>
<li><code>stop_grace_period: 15s</code> &gt; drain de 5 s ; limites CPU/mémoire ; 2 réplicas (<code>API_REPLICAS</code>) ;</li>
<li>NGINX : <code>resolve</code> sur le nom <code>api</code>, keepalive, timeouts courts, bascule <code>proxy_next_upstream error timeout</code>
(jamais pour un POST).</li>
</ul>
<h3>6.2 Kubernetes (bonus)</h3>
<p>Le dossier <code>k8s/</code> contient : un namespace, une ConfigMap, le <b>Deployment</b> de l'API (3 réplicas ; sondes
startup / readiness / liveness ; requests et limits ; <code>RollingUpdate maxUnavailable: 0, maxSurge: 1</code> ;
<code>topologySpreadConstraints</code> par nœud et par zone et anti-affinité ; <code>runAsNonRoot</code>,
<code>readOnlyRootFilesystem</code>, capabilities supprimées ; <code>terminationGracePeriodSeconds: 20</code>), le <b>Service</b>,
le <b>PodDisruptionBudget</b> <code>minAvailable: 2</code> et les trois dépendances.</p>
__K8S__

<h2>7. Chaos engineering : protocole et résultats</h2>
<h3>7.1 Protocole automatisé (<code>chaos/chaos.py</code>)</h3>
<p>Chaque expérience suit la démarche du jour 1 : <b>mesure de référence</b> (15 s) → <b>injection</b> (via <code>/admin</code>,
un pic de charge ou un <code>kill -9</code>) → <b>mesure pendant la panne</b> (20 s) avec <b>critère d'arrêt automatique</b>
(SLI &lt; 80 % sur 10 s glissantes : la panne est annulée) → <b>retour à la normale</b> → <b>mesure de la récupération</b> (20 s).
La charge vient de 12 clients réguliers (≈ 60 req/s, 85 % de pages produit sur 100 SKU, 15 % de checkouts avec réessai
utilisateur et même clé). Chaque expérience est jouée deux fois : l'API est redéployée avec <code>PATTERNS=off</code>
(« avant »), puis <code>PATTERNS=on</code> (« après »).</p>
<ul>
<li><b>Détection</b> : délai entre l'injection et la première réponse portant <code>X-Circuit-…: ouvert</code> (ouverture du breaker).</li>
<li><b>Récupération</b> : délai entre le retour à la normale et 10 réponses nominales consécutives (2xx, &lt; 1 s, non dégradées).</li>
</ul>
<h3>7.2 Synthèse avant / après</h3>
{tableau_resultats()}
{img("chaos_barres.png", "92%", "Figure 3 — SLI et latence p95 pendant la panne, sans (orange) et avec (vert) patterns. Pointillés : SLO 99 % et 1 s")}
__ANALYSE__
{img("chaos_timelines.png", "86%", "Figure 4 — SLI seconde par seconde (moyenne glissante sur 3 s). Zone grise : panne injectée (20 s) ; tirets : arrêt de sécurité (panne annulée)")}

<h2>8. Fiches d'expérience</h2>
<div class="fiches">__FICHES__</div>

<h2>9. Faiblesses découvertes et corrections (avant / après)</h2>
__FAIBLESSES__

<h2>10. Limites et perspectives</h2>
__LIMITES__

"""
    return corps


def ecrire(corps):
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Dossier d'architecture ShopFlow — Yasmine Ghouar</title><style>{CSS}</style></head><body>{corps}</body></html>"""
    sortie = DOCS / "dossier_architecture.html"
    sortie.write_text(page, encoding="utf-8")
    return sortie


def pdf(html_path):
    for nav in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                shutil.which("chromium") or "", shutil.which("google-chrome") or ""):
        if nav and pathlib.Path(nav).exists():
            cible = DOCS / NOM_PDF
            subprocess.run([nav, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            f"--print-to-pdf={cible}", html_path.as_uri()], capture_output=True, timeout=120)
            print("PDF :", cible)
            return cible
    print("Aucun navigateur trouvé : ouvrir le HTML et imprimer en PDF.")


if __name__ == "__main__":
    import textes
    c = construire()
    for cle, val in textes.sections(S, GW1, v, fr, fiche, table).items():
        c = c.replace(cle, val)
    pdf(ecrire(c))
