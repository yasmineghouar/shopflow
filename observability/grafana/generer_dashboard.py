"""generer_dashboard.py — génère dashboards/shopflow.json (évite d'éditer le JSON Grafana à la main).
Lancer : python observability/grafana/generer_dashboard.py
"""
import json
import pathlib

DS = {"type": "prometheus", "uid": "prometheus"}
panels = []
ligne_y = [0]


def panneau(titre, requetes, type_="timeseries", unite=None):
    p = {"type": type_, "title": titre, "datasource": DS,
         "targets": [{"datasource": DS, "expr": e, "legendFormat": l, "refId": chr(65 + i)}
                     for i, (e, l) in enumerate(requetes)],
         "fieldConfig": {"defaults": {}, "overrides": []}, "options": {}}
    if unite:
        p["fieldConfig"]["defaults"]["unit"] = unite
    if type_ == "timeseries":
        p["fieldConfig"]["defaults"]["custom"] = {"lineWidth": 2, "fillOpacity": 10, "showPoints": "never"}
        p["options"] = {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}
    panels.append(p)
    return p


def rangee(liste, largeurs, hauteur=8):
    x = 0
    for p, w in zip(liste, largeurs):
        p["gridPos"] = {"h": hauteur, "w": w, "x": x, "y": ligne_y[0]}
        x += w
    ligne_y[0] += hauteur


def seuils(*etapes):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in etapes]}


def correspondances(table):
    return [{"type": "value", "options": {k: {"text": t, "color": c} for k, (t, c) in table.items()}}]


s1 = panneau("SLI (5 min) — 2xx en < 1 s", [("shopflow:sli:ratio_rate5m", "SLI")], "stat", "percentunit")
s1["fieldConfig"]["defaults"].update(decimals=2, thresholds=seuils(("red", None), ("orange", 0.95), ("green", 0.99)))
s2 = panneau("Burn rate du budget d'erreur (5 min)", [("shopflow:burn_rate:5m", "burn")], "stat")
s2["fieldConfig"]["defaults"].update(decimals=1, thresholds=seuils(("green", None), ("orange", 6), ("red", 14.4)))
s3 = panneau("Réplicas API prêtes", [("sum(shopflow_ready)", "prêtes")], "stat")
s3["fieldConfig"]["defaults"].update(thresholds=seuils(("red", None), ("orange", 1), ("green", 2)))
s4 = panneau("Patterns de résilience", [("min(shopflow_patterns_enabled)", "patterns")], "stat")
s4["fieldConfig"]["defaults"].update(mappings=correspondances({"0": ("OFF", "red"), "1": ("ON", "green")}))
rangee([s1, s2, s3, s4], [6, 6, 6, 6], hauteur=5)

a = panneau("SLI glissant vs objectif 99 %", [("shopflow:sli:ratio_rate1m", "SLI 1 min"),
                                              ("shopflow:sli:ratio_rate5m", "SLI 5 min"),
                                              ("vector(0.99)", "SLO 99 %")], unite="percentunit")
b = panneau("Requêtes/s par route et code",
            [("sum by (route, code) (rate(shopflow_http_requests_total[1m]))", "{{route}} {{code}}")], unite="reqps")
rangee([a, b], [12, 12])

c = panneau("Latence p50 / p95 / p99 (requêtes 2xx)",
            [(f'histogram_quantile({q}, sum by (le) (rate(shopflow_http_request_duration_seconds_bucket{{classe="2xx"}}[1m])))',
              f"p{int(q * 100)}") for q in (0.5, 0.95, 0.99)], unite="s")
d = panneau("Circuit breakers (fermé / ouvert / semi-ouvert)",
            [("max by (dep) (shopflow_circuit_state)", "{{dep}}")], "state-timeline")
d["fieldConfig"]["defaults"].update(mappings=correspondances(
    {"0": ("fermé", "green"), "1": ("ouvert", "red"), "2": ("semi-ouvert", "orange")}))
rangee([c, d], [12, 12])

e = panneau("Appels aux dépendances par issue",
            [("sum by (dep, issue) (rate(shopflow_dependency_calls_total[1m]))", "{{dep}} {{issue}}")], unite="reqps")
f = panneau("Fallbacks (réponses dégradées) /s",
            [("sum by (dep, type) (rate(shopflow_fallback_total[1m]))", "{{dep}} {{type}}")], unite="reqps")
rangee([e, f], [12, 12])

g = panneau("Rate limiting (429) et load shedding (503) /s",
            [("sum by (route) (rate(shopflow_rate_limited_total[1m]))", "429 {{route}}"),
             ("sum by (priorite) (rate(shopflow_load_shed_total[1m]))", "503 délestage {{priorite}}")], unite="reqps")
h = panneau("Retries et timeouts /s",
            [("sum by (dep) (rate(shopflow_retries_total[1m]))", "retry {{dep}}"),
             ("sum by (dep) (rate(shopflow_timeouts_total[1m]))", "timeout {{dep}}")], unite="reqps")
rangee([g, h], [12, 12])

i = panneau("Bulkheads : places occupées et refus",
            [("sum by (dep) (shopflow_bulkhead_in_use)", "{{dep}} occupées"),
             ("sum by (dep) (rate(shopflow_bulkhead_rejected_total[1m]))", "refus {{dep}}/s")])
j = panneau("Requêtes en cours par réplica", [("shopflow_inflight_requests", "{{instance}}")])
rangee([i, j], [12, 12])

for k, p in enumerate(panels, 1):
    p["id"] = k

dashboard = {"uid": "shopflow", "title": "ShopFlow — Résilience & SLO", "tags": ["shopflow", "slo"],
             "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "5s",
             "time": {"from": "now-15m", "to": "now"}, "panels": panels}

sortie = pathlib.Path(__file__).parent / "dashboards" / "shopflow.json"
sortie.write_text(json.dumps(dashboard, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(panels)} panneaux -> {sortie}")
