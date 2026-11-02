"""Boucle continue des bots (papier) — une minute après l'autre, pendant ~5 h 40, puis la tâche suivante prend le relais.

Dépôt PUBLIC (minutes GitHub Actions illimitées) qui ne contient QUE cette boucle. Le code et l'état des bots restent
dans deux dépôts privés, clonés au démarrage avec une clé de déploiement propre à chacun (écriture sur ce dépôt-là
seulement). Le journal public n'affiche que des compteurs, jamais de montant ni de position.

À chaque minute :
  · Stratégie 3.0 : consignes du pupitre, puis un passage (décision sur la dernière bougie close, stops et exécution
    au prix de l'instant) ; état poussé toutes les 30 min, ou tout de suite s'il y a eu un ordre ou une consigne ;
  · comité (bot-agents) : suivi au prix de l'instant (comptes, low caps, Georges) ; poussé toutes les 10 min.
    Quand le comité quotidien pose son verrou (etat/verrou), la boucle pousse ce qu'elle a et se met en pause
    jusqu'à ce qu'il ait fini : un seul écrivain à la fois.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
S3, BA = ICI / "strategie3", ICI / "bot-agents"
DUREE = float(os.environ.get("DUREE_S", 5 * 3600 + 40 * 60))
PAS = 60
POUSSE_S3, POUSSE_BA = 1800, 600
VERROU_MAX = 3600           # un verrou plus vieux qu'une heure = comité planté : on reprend


def git(depot: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(depot), *args], capture_output=True, text=True, timeout=120)


def tirer(depot: Path) -> bool:
    return git(depot, "pull", "-q", "--rebase", "--autostash").returncode == 0


def pousser(depot: Path, message: str, chemins: list[str]) -> str:
    git(depot, "add", *chemins)
    if git(depot, "diff", "--cached", "--quiet").returncode == 0:
        return "rien"
    git(depot, "commit", "-q", "-m", message)
    for _ in range(3):
        if tirer(depot) and git(depot, "push", "-q").returncode == 0:
            return "poussé"
        time.sleep(5)
    return "ÉCHEC"


def horodatage() -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime()) + " UTC"


def tour_s3() -> dict:
    env = {**os.environ, "S3_DB_PATH": "etat/state.sqlite", "S3_HOST": "github", "MODE": "paper"}
    r = subprocess.run([sys.executable, str(ICI / "tour_s3.py")], cwd=S3, env=env, capture_output=True,
                       text=True, timeout=240)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"erreur": (r.stderr or "").strip().splitlines()[-1:] or ["?"]}


def recopier_plan_zoe() -> bool:
    """Plan de Zoé (bot-agents, etat.json → zoe.ordres) recopié dans strategie3/etat/plan_zoe.json, où le bot « zoe » de
    Stratégie 3.0 l'exécute. Renvoie True si le plan a changé (l'état est alors poussé tout de suite)."""
    try:
        z = json.loads((BA / "etat" / "etat.json").read_text(encoding="utf-8")).get("zoe") or {}
    except (OSError, ValueError):
        return False
    ordres = {s: {"sens": o.get("sens", 1), "entree": o["entree"], "stop": o["stop"], "objectif": o["objectif"],
                  "levier": o.get("levier", 4), "pose": o.get("pose"), "expire": o.get("expire"),
                  "unite": (o.get("zone") or {}).get("unite")} for s, o in (z.get("ordres") or {}).items()}
    objectifs = {s: p["objectif"] for s, p in (z.get("positions") or {}).items()}
    neuf = {"source": "bot-agents etat.json → zoe", "regle": z.get("regle"), "ordres": ordres, "objectifs": objectifs}
    f = S3 / "etat" / "plan_zoe.json"
    try:
        ancien = json.loads(f.read_text(encoding="utf-8"))
        ancien.pop("genere", None)
    except (OSError, ValueError):
        ancien = None
    if ancien == neuf:
        return False
    f.write_text(json.dumps({**neuf, "genere": horodatage()}, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def verrou_comite() -> bool:
    f = BA / "etat" / "verrou"
    if not f.exists():
        return False
    try:
        return time.time() - float(f.read_text().strip() or 0) < VERROU_MAX
    except ValueError:
        return True


def main() -> int:
    fin = time.time() + DUREE
    pousse = {"s3": time.time(), "ba": time.time()}
    ordres_vus, n = None, 0
    while time.time() < fin:
        t0 = time.time()
        n += 1
        # ---- Stratégie 3.0 (le plan de Zoé est recopié d'abord, depuis le dernier état du comité)
        tirer(S3)
        tirer(BA)
        plan_neuf = recopier_plan_zoe()
        r = tour_s3()
        bouge = plan_neuf or r.get("consignes", 0) > 0 or (ordres_vus is not None and r.get("ordres") != ordres_vus)
        ordres_vus = r.get("ordres", ordres_vus)
        if bouge or time.time() - pousse["s3"] > POUSSE_S3:
            etat = pousser(S3, f"état : {horodatage()}", ["etat/state.sqlite", "etat/plan_zoe.json"])
            pousse["s3"] = time.time()
        else:
            etat = "local"
        # ---- comité : suivi en direct, sauf pendant le comité quotidien
        tirer(BA)
        if verrou_comite():
            ba = "pause (comité en cours) · " + pousser(BA, f"suivi : {horodatage()}", ["etat"])
            pousse["ba"] = time.time()
        else:
            s = subprocess.run([sys.executable, "-m", "agents.comite", "--suivi"], cwd=BA, capture_output=True,
                               text=True, timeout=240)
            ba = "suivi ok" if s.returncode == 0 else "suivi en échec"
            if time.time() - pousse["ba"] > POUSSE_BA:
                ba += " · " + pousser(BA, f"suivi : {horodatage()}", ["etat"])
                pousse["ba"] = time.time()
        print(f"{horodatage()} · tour {n} · S3 {'erreur' if 'erreur' in r else 'ok'} ({etat}) · comité {ba}",
              flush=True)
        time.sleep(max(1.0, PAS - (time.time() - t0)))
    # fin de tâche : tout pousser avant de passer la main
    pousser(S3, f"état : {horodatage()}", ["etat/state.sqlite", "etat/plan_zoe.json"])
    if not verrou_comite():
        pousser(BA, f"suivi : {horodatage()}", ["etat"])
    print("fin de la tâche, la suivante prend le relais", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
