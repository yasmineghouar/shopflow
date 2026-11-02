# ShopFlow — Architecture résiliente complète (projet final, M2 LDF)

Projet final du module *Patterns de résilience* (formatrice : Suzanne KOKOS).
Il prolonge directement les TP 7 à 10 : `shopflow_api` (rate limiting, load shedding, health checks)
devient le cœur d'une architecture à 5 services observée par Prometheus/Grafana et éprouvée par
7 expériences de chaos automatisées, jouées **avant / après** patterns.

Auteure : Yasmine Ghouar · Dossier d'architecture : [`docs/Dossier_Architecture_ShopFlow_Yasmine_Ghouar.pdf`](docs/)

## Lancer tout en une commande

```bash
docker compose up -d --build
```

| Service | URL | Rôle |
|---|---|---|
| gateway (NGINX) | http://localhost:8000 | point d'entrée, répartition sur les réplicas, bascule |
| api ×2 | (interne :8000) | `shopflow_api` : page produit, checkout, sondes, `/metrics` |
| stock / reco / payment | admin : 8081 / 8082 / 8083 | dépendances instables (`flaky_service`) pilotables par `/admin` |
| Prometheus | http://localhost:9090 | collecte, règles d'enregistrement SLO, alertes |
| Grafana | http://localhost:3000 | tableau de bord « ShopFlow — Résilience & SLO » (sans login) |

> Port 8000 déjà pris ? `GATEWAY_PORT=8090 docker compose up -d --build` (puis `GATEWAY_URL=http://localhost:8090` pour le chaos).

Essai rapide :

```bash
curl -i http://localhost:8000/products/A1
curl -i -X POST -H "Content-Type: application/json" -H "Idempotency-Key: panier-1" \
     -d '{"montant": 42}' http://localhost:8000/checkout
curl http://localhost:8000/health/ready
```

## Injecter une panne à la main

```bash
curl "http://localhost:8081/admin?down=1"            # stock indisponible -> circuit ouvert, cache servi
curl "http://localhost:8082/admin?latency_reco=3"    # reco lente -> page sans recommandations
curl "http://localhost:8083/admin?fail_after=0.3"    # paiement : réponses perdues -> retry idempotent
curl "http://localhost:8081/admin?down=0&latency=0.05&fail_rate=0"   # retour à la normale
```

## Expériences de chaos (avant / après)

```bash
python chaos/chaos.py                 # E1..E7, chacune patterns OFF puis ON (~25 min)
python chaos/chaos.py E2 E5           # sélection
python chaos/chaos.py --modes apres --tag v1 E3 E6   # rejouer les premiers réglages (comparaison du correctif)
python chaos/rapport.py               # tableaux + graphiques -> docs/figures, chaos/results/synthese.md
```

`PATTERNS=off docker compose up -d api` lance l'API sans aucun pattern (mode « avant »).

| # | Panne | Patterns éprouvés |
|---|---|---|
| E1 | 30 % d'erreurs sur stock | retry + backoff/jitter, circuit breaker |
| E2 | stock totalement indisponible | circuit breaker, cache résilient (fallback) |
| E3 | latence 2 s sur stock | timeout, deadline, bulkhead, circuit breaker |
| E4 | recommandations à 3 s | dégradation gracieuse, timeout court |
| E5 | paiement : 30 % de réponses perdues | retry + clé d'idempotence |
| E6 | client abusif + afflux soudain | rate limiting, load shedding prioritaire |
| E7 | `kill -9` d'une réplica API | health checks, redémarrage, bascule du gateway |

## Kubernetes (bonus)

```bash
minikube start -p shopflow
minikube -p shopflow image load shopflow-api:latest
minikube -p shopflow image load shopflow-deps:latest
kubectl apply -f k8s/
kubectl -n shopflow get pods -w
```

Deployment à 3 réplicas (startup / readiness / liveness, ressources, `maxUnavailable: 0`, répartition
nœuds + zones), Service, PodDisruptionBudget `minAvailable: 2`, dépendances.

## Arborescence

```
api/            shopflow_api.py, health.py, resilience.py, rate_limit.py, client.py, metrics.py, config.py, Dockerfile
deps/           flaky_service.py (kit du jour 2) + Dockerfile — une image, trois services
gateway/        nginx.conf
observability/  prometheus.yml, alerts.yml (SLO + burn rate), Grafana (datasource, dashboard)
chaos/          chaos.py (expériences), rapport.py (synthèse), results/ (JSON bruts)
k8s/            manifestes Kubernetes
tests/          tests unitaires des patterns : python -m unittest discover tests
docs/           dossier d'architecture (PDF) et figures
```

Aucune bibliothèque externe n'est nécessaire côté services (Python standard uniquement).
`chaos/rapport.py` utilise `matplotlib` pour les graphiques.
