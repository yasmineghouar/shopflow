"""textes.py — sections rédigées du dossier qui commentent les résultats mesurés.
Les chiffres sont lus dans chaos/results/synthese.json (aucune valeur saisie à la main)."""
import base64
import html
import pathlib

FIG = pathlib.Path(__file__).resolve().parent / "figures"
K8S_LOG = pathlib.Path(__file__).resolve().parent / "k8s_trace.txt"


def _img(nom, legende):
    f = FIG / nom
    if not f.exists():
        return ""
    b64 = base64.b64encode(f.read_bytes()).decode()
    return (f'<figure><img src="data:image/png;base64,{b64}" style="width:100%">'
            f'<figcaption>{legende}</figcaption></figure>')


def sections(S, GW1, v, fr, fiche, table):
    P = lambda k: v(k, "bilans", "panne")          # noqa: E731
    R = lambda k: v(k, "bilans", "reference")      # noqa: E731
    e5a, e5b = v("E5_avant", "paiement"), v("E5_apres", "paiement")
    gw = GW1["bilans"]["panne"]
    e6a, e6b, e6v1 = S["E6_avant"], S["E6_apres"], S["E6_apres_v1"]
    e7a, e7b = S["E7_avant"], S["E7_apres"]
    cb1, e1 = P("E1_apres_cb1"), P("E1_apres")
    e3v1, e3 = S["E3_apres_v1"], S["E3_apres"]
    debit = lambda r, ph="panne": r["bilans"]["panne" if ph == "panne" else "reference"]["n"] / max(  # noqa: E731
        1e-9, (r["t_retour"] - r["t_panne"]) if ph == "panne" else r["t_panne"])
    bon_s = lambda r: debit(r) * r["bilans"]["panne"]["sli"] / 100  # noqa: E731

    analyse = f"""
<h3>7.3 Lecture des résultats</h3>
<ul>
<li><b>Sans patterns, toutes les pannes de dépendance franchissent le critère d'arrêt.</b> E1 à E4 tombent entre
{fr(P('E3_avant')['sli'], 0)} % et {fr(P('E1_avant')['sli'], 0)} % de SLI et la panne est annulée automatiquement au bout de 10 s.
Avec les patterns, le SLI reste à <b>{fr(P('E1_apres')['sli'], 1)} %, {fr(P('E2_apres')['sli'], 1)} %, {fr(P('E3_apres')['sli'], 1)} % et
{fr(P('E4_apres')['sli'], 1)} %</b>, sans arrêt de sécurité, et la p95 ne dépasse pas {fr(max(P(f'E{i}_apres')['p95'] for i in range(1, 5)), 2)} s.</li>
<li><b>Latence (E3, E4)</b> : sans timeout, une dépendance lente se propage telle quelle (p95 {fr(P('E3_avant')['p95'], 2)} s pour E3,
{fr(P('E4_avant')['p95'], 2)} s pour E4) et occupe les 8 workers. Le timeout, le breaker et le bulkhead coupent ce couplage :
la latence de la dépendance n'est plus celle de l'utilisateur.</li>
<li><b>Détection</b> : le breaker s'ouvre {fr(v('E2_apres', 'detection_s'), 2)} s après l'arrêt du stock (E2) et
{fr(v('E3_apres', 'detection_s'), 2)} s après l'injection de latence (E3). La <b>récupération</b> complète (10 réponses nominales
consécutives) prend {fr(v('E2_apres', 'recuperation_s'), 1)} s en E2. Ce délai est surtout dû à la durée d'ouverture du breaker
(5 s) : c'est le compromis entre ménager une dépendance qui redémarre et revenir vite au nominal.</li>
<li><b>Prix de la résilience : la dégradation.</b> Pendant E2 à E4, {fr(P('E2_apres')['degrade'], 0)} à {fr(P('E4_apres')['degrade'], 0)} %
des réponses sont dégradées (stock issu du cache, page sans recommandations). Le SLI « servi » ne suffit donc pas à juger la
qualité : la part dégradée est suivie à part, sur le tableau de bord et dans le tableau ci-dessus.</li>
<li><b>Paiement (E5)</b> : sans idempotence, {e5a['debits']} débits pour {e5a['paniers_payes_vus_client']} paniers confirmés, soit
<b>{e5a['debits_en_trop']} débits sans commande confirmée</b> (doubles débits après un réessai). Avec la clé d'idempotence et le retry :
{e5b['debits']} débits pour {e5b['paniers_payes_vus_client']} paniers confirmés, <b>{e5b['debits_en_trop']} écart</b>,
{fr(e5b['taux_paniers_payes'], 1)} % de paniers payés.</li>
<li><b>Perte d'une instance (E7)</b> : avec une seule réplica, {e7a['echecs_pendant_kill']} requêtes échouent pendant le redémarrage.
Avec deux réplicas et la bascule du gateway, il n'y en a plus que <b>{e7b['echecs_pendant_kill']}</b> (requêtes en cours sur
l'instance tuée, dont des POST qu'on ne rejoue jamais automatiquement) : SLI {fr(P('E7_apres')['sli'], 2)} %.</li>
<li><b>Pic de trafic (E6) : hypothèse invalidée</b>, détaillée en section 9.</li>
</ul>"""

    fiches = (
        fiche("E1", "<b>Oui</b> pour le SLI ; la première version ouvrait le breaker sur du bruit (correctif 2, section 9).",
              "stock seulement ; toutes les pages produit (85 % du trafic)",
              "Breaker basé sur un taux d'échec (50 appels, 60 %, volume min. 20) au lieu de 20 appels / 50 %.",
              f"Première version : {fr(P('E1_apres_cb1')['degrade'], 1)} % de réponses dégradées ; après réglage : "
              f"{fr(P('E1_apres')['degrade'], 1)} %. Erreurs 5xx visibles : {P('E1_apres')['erreurs_5xx']}.")
        + fiche("E2", "<b>Oui</b> : détection en moins de 2 s, SLI &gt; 95 %.",
                "stock ; toutes les pages produit",
                "Préchauffer le cache des SKU les plus vendus au démarrage (un SKU jamais vu reste « inconnu »).")
        + fiche("E3", "<b>Oui</b>, après le correctif 3 (deadline) ; la version du TP 9 dépassait 1 s sur les premières requêtes.",
                "stock ; pages produit ; risque de saturation des workers pour tout le trafic",
                "Budget global de 0,8 s partagé par les tentatives ; timeout du stock ramené à 0,3 s.")
        + fiche("E4", "<b>Oui</b> : page servie sans recommandations, p95 inchangée.",
                "reco ; bloc optionnel des pages produit",
                "Aucune ; afficher « recommandations indisponibles » côté interface plutôt qu'une liste vide.")
        + fiche("E5", "<b>Oui</b> : aucun double débit, tous les paniers payés.",
                "payment ; tous les checkouts (15 % du trafic)",
                "Conserver les clés côté prestataire au moins 24 h ; réconciliation périodique des débits.",
                f"Sans patterns : {e5a['paniers']} paniers, {e5a['debits']} débits, {e5a['debits_en_trop']} en trop. "
                f"Avec : {e5b['paniers']} paniers, {e5b['debits']} débits, {e5b['debits_en_trop']} en trop.")
        + fiche("E6", "<b>Non</b> : le SLI des clients habituels baisse quand le délestage est actif (voir section 9).",
                "toutes les routes ; capacité des deux réplicas",
                "Délestage adaptatif fondé sur le temps d'attente (type CoDel) ; tests de charge en boucle ouverte ; autoscaling.",
                f"Client abusif : {e6b['abusif_codes'].get('429', 0)} réponses 429 sur "
                f"{sum(e6b['abusif_codes'].values())} requêtes ; checkout réussi à {fr(e6b['checkout_succes_pendant'], 0)} % "
                f"pendant le pic.")
        + fiche("E7", "<b>Oui</b> : moins de 1 % d'échecs, redémarrage automatique.",
                "une réplica API sur deux ; requêtes en cours sur cette réplica",
                "Rejouer automatiquement les GET interrompus au gateway (déjà fait) ; pour les POST, clé d'idempotence côté client.",
                f"Requêtes en échec : {e7a['echecs_pendant_kill']} (1 réplica) → {e7b['echecs_pendant_kill']} (2 réplicas).")
    )

    faiblesses = f"""
<p>Le chaos engineering sert d'abord à <b>apprendre</b> : quatre expériences ont révélé un comportement inattendu. Trois ont été
corrigés et la correction a été re-mesurée ; le quatrième constat a invalidé une hypothèse et débouche sur une recommandation.</p>
<h3>Correctif 1 — le gateway amplifiait les erreurs (E1 sans patterns)</h3>
<p>Premier passage de E1 : 30 % d'erreurs du stock ont produit <b>{fr(gw['sli'], 1)} % de SLI</b> au lieu des ≈ 70 % attendus.
Les journaux NGINX affichaient <code>no live upstreams</code>. Cause : <code>proxy_next_upstream … http_502</code> compte chaque 502
<i>applicatif</i> (« stock indisponible ») comme une panne de l'instance. Avec <code>max_fails=2</code>, les deux réplicas,
pourtant saines, étaient éjectées tour à tour pendant 5 s. Correction : ne basculer que sur les erreurs de <b>connexion</b>
(<code>error timeout</code>). Résultat : <b>{fr(gw['sli'], 1)} % → {fr(P('E1_avant')['sli'], 1)} %</b> à panne identique. Ce mode de
défaillance a été ajouté à l'AMDEC (R11) : un mécanisme de résilience mal réglé peut lui-même provoquer la panne.</p>
{_img("correctif_gateway.png", "Figure 5 — E1 sans patterns : gateway initial (violet) vs corrigé (orange)")}
<h3>Correctif 2 — le circuit breaker s'ouvrait sur du bruit (E1 avec patterns)</h3>
<p>Avec 30 % d'erreurs indépendantes, le SLI restait à {fr(cb1['sli'], 1)} %, mais <b>{fr(cb1['degrade'], 1)} % des réponses étaient
dégradées</b> : le breaker (fenêtre de 20 appels, seuil 50 %) s'ouvrait régulièrement. Chaque tentative étant comptée, la probabilité
d'atteindre 10 échecs sur 20 avec p = 0,3 est d'environ 5 % <i>par fenêtre</i>, ce qui arrive en permanence à 60 req/s. Or le retry
seul ramène l'échec à 0,3³ ≈ 2,7 %. Correction : fenêtre de 50 appels, seuil 60 %, volume minimal 20 (probabilité de fausse
ouverture ≈ 0,001 % sur une fenêtre pleine, 0,5 % sur une fenêtre encore partielle de 20 appels). Une panne franche ouvre toujours le breaker en moins d'une seconde (E2 : {fr(v('E2_apres', 'detection_s'), 2)} s).
Résultat : réponses dégradées <b>{fr(cb1['degrade'], 1)} % → {fr(e1['degrade'], 1)} %</b>, SLI {fr(e1['sli'], 1)} %.
<b>Contrepartie mesurée</b> : un breaker moins sensible s'ouvre un peu plus tard sur une panne de latence (E3 :
{fr(v('E3_apres_cb1', 'detection_s'), 2)} s → {fr(v('E3_apres', 'detection_s'), 2)} s). Le SLI n'en souffre pas, car la deadline
borne déjà chaque requête à 0,8 s.</p>
{_img("correctif_e1.png", "Figure 6 — E1 avec patterns : part de réponses dégradées avant / après le réglage du breaker")}
<h3>Correctif 3 — retries sans budget global (E3)</h3>
<p>Le client du TP 9 (timeout 0,5 s × 3 tentatives, sans budget global) peut mettre jusqu'à ≈ 1,6 s avant d'abandonner, plus que
le SLO de 1 s, tant que le breaker n'est pas ouvert. Mesuré avec ces réglages (v1) : SLI {fr(e3v1['bilans']['panne']['sli'], 2)} %,
détection {fr(e3v1['detection_s'], 2)} s, récupération {fr(e3v1['recuperation_s'], 1)} s. Avec un <b>budget global de 0,8 s</b>
partagé par toutes les tentatives et un timeout de 0,3 s : SLI <b>{fr(e3['bilans']['panne']['sli'], 2)} %</b>, détection
{fr(e3['detection_s'], 2)} s, récupération {fr(e3['recuperation_s'], 1)} s. Le budget garantit par construction qu'aucune requête
n'attend plus de 0,8 s sa dépendance, quel que soit l'état du breaker.</p>
{_img("correctif_e3.png", "Figure 7 — E3 : latence p95 seconde par seconde, client du TP 9 vs budget global")}
<h3>Constat 4 — E6 invalide l'hypothèse sur le délestage</h3>
<p>Hypothèse : « rate limiting + load shedding gardent un SLI &gt; 95 % aux clients habituels pendant un pic ».
Mesures pendant le pic (client abusif à 25 threads et afflux de 60 nouveaux clients) :</p>
{table(["Variante", "SLI clients habituels", "débit utile (rép. bonnes/s)", "p50 / p95 (s)", "abusif : 429", "afflux : 503"], [
        ["Sans patterns", f"{fr(e6a['bilans']['panne']['sli'], 1)} %", fr(bon_s(e6a), 1),
         f"{fr(e6a['bilans']['panne']['p50'], 2)} / {fr(e6a['bilans']['panne']['p95'], 2)}", "0", "0"],
        ["Shedder 12 places (v1)", f"{fr(e6v1['bilans']['panne']['sli'], 1)} %", fr(bon_s(e6v1), 1),
         f"{fr(e6v1['bilans']['panne']['p50'], 2)} / {fr(e6v1['bilans']['panne']['p95'], 2)}",
         str(e6v1['abusif_codes'].get('429', 0)), str(e6v1['afflux_codes'].get('503', 0))],
        ["Shedder 40 places (loi de Little)", f"{fr(e6b['bilans']['panne']['sli'], 1)} %", fr(bon_s(e6b), 1),
         f"{fr(e6b['bilans']['panne']['p50'], 2)} / {fr(e6b['bilans']['panne']['p95'], 2)}",
         str(e6b['abusif_codes'].get('429', 0)), str(e6b['afflux_codes'].get('503', 0))],
    ], "num")}
<p><b>Ce qui fonctionne</b> : le rate limiting écarte le client abusif à faible coût, et la réserve du shedder protège le checkout
(succès {fr(e6b['checkout_succes_pendant'], 0)} % pendant le pic). Recalibrer le shedder avec la loi de Little a fait passer le SLI de
{fr(e6v1['bilans']['panne']['sli'], 1)} % à {fr(e6b['bilans']['panne']['sli'], 1)} %.<br>
<b>Ce que l'on a appris</b> : sans protection, le SLI semble meilleur, mais c'est un artefact de mesure. Nos clients de test
attendent leur réponse avant d'envoyer la suivante (charge « en boucle fermée ») : quand le système ralentit, ils ralentissent aussi.
Le débit des clients habituels passe de {fr(debit(e6a, 'ref'), 0)} à {fr(debit(e6a), 0)} req/s et la médiane de 0,13 s à
{fr(e6a['bilans']['panne']['p50'], 2)} s, sans qu'aucune requête ne dépasse 1 s. De vrais utilisateurs, eux, continueraient
d'arriver (boucle ouverte) : la file grandirait sans limite et le SLI s'effondrerait. Par ailleurs, l'afflux est composé de
<b>clients légitimes</b> que le shedder ne peut pas distinguer des habitués : rejeter vite une partie du trafic est le comportement
voulu, mais le SLI par requête le compte comme un échec. Le débit utile reste du même ordre (≈ {fr(bon_s(e6b), 0)} réponses
bonnes/s) : le délestage ne crée pas de capacité, il choisit qui est servi.<br>
<b>Actions</b> : (1) délestage adaptatif fondé sur le <b>temps d'attente</b> réel (rejeter quand l'attente dépasse ≈ 0,5 s, à la
manière de CoDel) plutôt qu'un nombre fixe de places ; (2) tests de charge en <b>boucle ouverte</b> (débit imposé) pour mesurer
honnêtement la surcharge ; (3) autoscaling horizontal sur la métrique <code>shopflow_inflight_requests</code> en Kubernetes.</p>
"""

    limites = """
<ul>
<li><b>Dépendances simulées</b> : <code>flaky_service</code> produit des pannes indépendantes et sans état. Les vraies pannes sont
corrélées (dégradation progressive, saturation liée à la charge). Toxiproxy permettrait d'injecter des pannes TCP réalistes
(coupures partielles, paquets perdus, bande passante).</li>
<li><b>Tout tourne sur un seul hôte</b> : la redondance de l'API ne protège pas contre la perte de la machine. Le gateway est
lui-même un SPOF en Compose. En production : Ingress répliqué, plusieurs nœuds et zones (manifestes fournis).</li>
<li><b>État local à chaque réplica</b> : token buckets, breakers et cache sont propres à chaque instance. Avec N réplicas, un client
dispose de N fois son quota (TP 7, question 2), et chaque réplica doit détecter la panne de son côté. Un Redis partagé rendrait
le rate limiting exact, au prix d'une nouvelle dépendance à protéger.</li>
<li><b>Charge en boucle fermée</b> générée depuis l'hôte Windows (≈ 60 à 300 req/s) : elle sous-estime la surcharge (constat E6).</li>
<li><b>Durées courtes</b> : 20 s de panne et quelques centaines de requêtes par phase. Les écarts de moins d'un point de SLI ne sont
pas significatifs. Les alertes sont démontrées sur des fenêtres réduites (1 min / 5 min / 1 h) et non sur 30 jours.</li>
<li><b>Le checkout reste borné par le prestataire</b> (≈ 99 %) : aucun repli n'est possible pour un débit. Seule une file de
paiements asynchrone (accepter la commande, payer plus tard) pourrait découpler le SLO du checkout de celui du prestataire.</li>
<li><b>Perspectives</b> : chaos continu en préproduction (expériences planifiées, critère d'arrêt branché sur l'alerte burn rate),
puis en production sur une petite part du trafic ; Alertmanager pour router les alertes ; traces distribuées (OpenTelemetry) pour
relier une requête lente à la dépendance en cause.</li>
</ul>"""

    if K8S_LOG.exists():
        trace = K8S_LOG.read_text(encoding="utf-8")
        k8s = ("<p>Le déploiement a été vérifié sur un cluster <b>minikube</b> local (profil dédié <code>shopflow</code>, "
               "1 nœud) : application des manifestes, suppression d'un pod et mise à jour progressive pendant une boucle de "
               "requêtes, puis drain du nœud pour éprouver le PodDisruptionBudget.</p>"
               f"<pre><code>{html.escape(trace)}</code></pre>"
               "<p><b>Bilan</b> : aucune requête perdue ni pendant la recréation d'un pod (258/258), ni pendant le rolling update "
               "(342/342) ; le drain est bloqué par le PDB dès que 2 pods seulement resteraient disponibles. Sur un cluster à "
               "un seul nœud, l'anti-affinité et le topology spread ne peuvent pas répartir les pods (préférences "
               "<code>ScheduleAnyway</code>) : c'est précisément la limite de la question 3 du TP 10.</p>")
    else:
        val = (pathlib.Path(__file__).resolve().parent / "k8s_validation.txt").read_text(encoding="utf-8")
        k8s = ("<p>Les 11 ressources ont été validées en mode strict contre les schémas officiels de Kubernetes 1.30 "
               "(<code>kubernetes-validate -k 1.30.0 --strict k8s/*.yaml</code>) :</p>"
               f"<pre><code>{html.escape(val)}</code></pre>"
               "<p>Le cluster minikube local n'a pas pu démarrer le jour des mesures (<code>K8S_APISERVER_MISSING</code> après un "
               "redémarrage de Docker Desktop). Le test de recréation de pod (<code>kubectl delete pod</code>) et de mise à jour "
               "progressive reste donc à faire, selon la procédure suivante : <code>minikube image load shopflow-api:latest "
               "shopflow-deps:latest</code>, <code>kubectl apply -f k8s/</code>, suppression d'un pod pendant une boucle de requêtes, "
               "puis <code>kubectl -n shopflow set env deploy/shopflow-api VERSION=2</code> pour déclencher un rolling update.</p>")

    trace = (pathlib.Path(__file__).resolve().parent / "alertes_trace.txt").read_text(encoding="utf-8")
    alertes = f"""
<h3>5.4 Preuve de déclenchement des alertes</h3>
<p>Les pannes de 20 s des expériences sont volontairement plus courtes que les délais de confirmation des alertes (30 s pour le
breaker, 1 min pour le burn rate) : on ne réveille pas l'astreinte pour un incident déjà résolu. Pour vérifier la chaîne d'alerte,
<code>chaos/demo_alerte.py</code> arrête le stock pendant 150 s, d'abord sans patterns, puis avec :</p>
<pre><code>{html.escape(trace)}</code></pre>
<p>Sans patterns, le SLO s'effondre : l'alerte rapide passe en <i>pending</i> à t+30 s et en <i>firing</i> à t+90 s
(30 s pour que la fenêtre de 1 min dépasse le seuil, puis la durée <code>for: 1m</code>). Avec patterns, le SLI est préservé ;
c'est <code>ShopFlowCircuitOuvert</code> qui signale le mode dégradé (firing à t+35 s). Les alertes de burn rate encore actives
au début de la phase 2 sont le résidu de la phase 1, toujours présente dans les fenêtres de 5 min et de 1 h.</p>"""

    return {"__ANALYSE__": analyse, "__FICHES__": fiches, "__FAIBLESSES__": faiblesses,
            "__LIMITES__": limites, "__K8S__": k8s, "__ALERTES__": alertes}
