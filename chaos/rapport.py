"""rapport.py — synthèse des expériences : tableau Markdown + graphiques pour le dossier.
Lancer : python chaos/rapport.py   (nécessite matplotlib)
"""
import json
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parents[1]
RES = RACINE / "chaos" / "results"
FIG = RACINE / "docs" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

AVANT, APRES, V1 = "#c2410c", "#0f766e", "#7c3aed"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 150})


def charger(code, mode, tag=""):
    f = RES / f"{code}_{mode}{'_' + tag if tag else ''}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def lisser(serie, cle, k=3):
    xs = [p["s"] for p in serie]
    ys = [p[cle] for p in serie]
    out = [sum(ys[max(0, i - k + 1):i + 1]) / len(ys[max(0, i - k + 1):i + 1]) for i in range(len(ys))]
    return xs, out


def tracer_sli(ax, r, couleur, label):
    xs, ys = lisser(r["serie"], "sli")
    ax.plot(xs, [100 * y for y in ys], color=couleur, lw=1.8, label=label)
    if couleur == APRES:                         # fenêtre de panne prévue (20 s), en gris neutre
        ax.axvspan(r["t_panne"], r["t_panne"] + 20, color="#94a3b8", alpha=0.15, lw=0)


def figure_timelines(codes):
    fig, axes = plt.subplots(len(codes), 1, figsize=(7.2, 1.3 * len(codes)), sharex=True)
    for ax, code in zip(axes, codes):
        av, ap = charger(code, "avant"), charger(code, "apres")
        if not (av and ap):
            continue
        tracer_sli(ax, av, AVANT, "sans patterns")
        tracer_sli(ax, ap, APRES, "avec patterns")
        ax.axhline(99, color="#555", ls=":", lw=1)
        ax.set_ylim(-3, 103)
        ax.set_ylabel("SLI %")
        ax.set_title(f"{code} — {ap['titre']}", loc="left", fontsize=9, fontweight="bold")
        for r, c in ((av, AVANT), (ap, APRES)):
            if r["arret_securite"]:
                ax.axvline(r["t_retour"], color=c, ls="--", lw=1)
    axes[0].legend(loc="lower left", ncol=2, frameon=False)
    axes[-1].set_xlabel("temps (s) — zone grise : panne injectée (20 s) ; tirets : arrêt de sécurité (panne annulée)")
    fig.tight_layout()
    fig.savefig(FIG / "chaos_timelines.png")
    plt.close(fig)


def figure_barres(codes):
    av = [charger(c, "avant") for c in codes]
    ap = [charger(c, "apres") for c in codes]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 2.6))
    x = range(len(codes))
    w = 0.38
    a1.bar([i - w / 2 for i in x], [r["bilans"]["panne"]["sli"] for r in av], w, color=AVANT, label="sans patterns")
    a1.bar([i + w / 2 for i in x], [r["bilans"]["panne"]["sli"] for r in ap], w, color=APRES, label="avec patterns")
    a1.set_xticks(list(x), codes)
    a1.set_ylabel("SLI pendant la panne (%)")
    a1.axhline(99, color="#555", ls=":", lw=1)
    a1.legend(frameon=False, fontsize=7, loc="lower left")
    a2.bar([i - w / 2 for i in x], [r["bilans"]["panne"]["p95"] or 0 for r in av], w, color=AVANT)
    a2.bar([i + w / 2 for i in x], [r["bilans"]["panne"]["p95"] or 0 for r in ap], w, color=APRES)
    a2.set_xticks(list(x), codes)
    a2.set_ylabel("latence p95 des 2xx (s)")
    a2.axhline(1, color="#555", ls=":", lw=1)
    fig.tight_layout()
    fig.savefig(FIG / "chaos_barres.png")
    plt.close(fig)


def figure_correctif(code, cle, titre, nom, unite="%", tag="v1", ref=None):
    v1 = charger(code, *(ref or ("apres", tag)))
    v2 = charger(code, "apres")
    if not (v1 and v2):
        return
    fig, ax = plt.subplots(figsize=(7.2, 1.8))
    for r, c, l in ((v1, V1, "avant correctif"), (v2, APRES, "après correctif")):
        xs, ys = lisser(r["serie"], cle)
        ax.plot(xs, [100 * y if unite == "%" else y for y in ys], color=c, lw=1.8, label=l)
        ax.axvspan(r["t_panne"], r["t_retour"], color=c, alpha=0.06)
    ax.set_title(titre, loc="left", fontsize=9, fontweight="bold")
    ax.set_ylabel({"sli": "SLI %", "deg": "% dégradé", "p95": "p95 (s)"}[cle])
    ax.set_xlabel("temps (s)")
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(FIG / nom)
    plt.close(fig)


def main():
    codes = [c for c in ("E1", "E2", "E3", "E4", "E5", "E6", "E7") if charger(c, "apres") and charger(c, "avant")]
    figure_timelines(codes)
    figure_barres(codes)
    figure_correctif("E1", "deg", "Correctif 2 — E1 : part de réponses dégradées, breaker 20 appels/50 % vs 50 appels/60 %",
                     "correctif_e1.png", tag="cb1")
    figure_correctif("E3", "p95", "Correctif 3 — E3 : p95, client du TP 9 (0,5 s × 3, sans budget) vs deadline 0,8 s",
                     "correctif_e3.png", unite="s")
    figure_correctif("E6", "sli", "E6 : shedder à 12 places (v1) vs 40 places (Little)", "correctif_e6.png")
    gw = charger("E1", "avant", "gw1")
    av = charger("E1", "avant")
    if gw and av:
        fig, ax = plt.subplots(figsize=(7.2, 1.8))
        for r, c, l in ((gw, V1, "gateway v1 (next_upstream http_502)"), (av, AVANT, "gateway corrigé")):
            xs, ys = lisser(r["serie"], "sli")
            ax.plot(xs, [100 * y for y in ys], color=c, lw=1.8, label=l)
            ax.axvspan(r["t_panne"], r["t_retour"], color=c, alpha=0.06)
        ax.set_title("Correctif 1 — E1 sans patterns : 30 % d'erreurs de stock vues par l'utilisateur", loc="left",
                     fontsize=9, fontweight="bold")
        ax.set_ylabel("SLI %")
        ax.set_xlabel("temps (s)")
        ax.legend(frameon=False, loc="lower left")
        fig.tight_layout()
        fig.savefig(FIG / "correctif_gateway.png")
        plt.close(fig)

    lignes = ["| Exp. | Mode | SLI réf. | SLI panne | 2xx panne | dégradé | p95 panne | détection | récup. | arrêt |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    synthese = {}
    for c in codes:
        for mode in ("avant", "apres"):
            r = charger(c, mode)
            b = r["bilans"]
            synthese[f"{c}_{mode}"] = r
            lignes.append(f"| {c} | {mode} | {b['reference']['sli']} | {b['panne']['sli']} | {b['panne']['succes_2xx']} | "
                          f"{b['panne']['degrade']} | {b['panne']['p95']} | {r['detection_s']} | {r['recuperation_s']} | "
                          f"{'oui' if r['arret_securite'] else 'non'} |")
    for c, mode, tag in (("E3", "apres", "v1"), ("E6", "apres", "v1"), ("E1", "apres", "cb1"), ("E1", "avant", "gw1"),
                          ("E3", "apres", "cb1")):
        r = charger(c, mode, tag)
        if r:
            synthese[f"{c}_{mode}_{tag}"] = r
    (RES / "synthese.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    sans_series = {k: {kk: vv for kk, vv in v.items() if kk != "serie"} for k, v in synthese.items()}
    (RES / "synthese.json").write_text(json.dumps(sans_series, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lignes))


if __name__ == "__main__":
    main()
