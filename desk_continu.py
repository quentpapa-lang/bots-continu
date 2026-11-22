"""Boucle continue du desk d'agents (papier) — un passage par minute pendant ~5 h 40, puis la tâche suivante.

Chaque passage part au début de la minute (+2 s, le temps que la bougie 1 min se ferme côté API) : les stops et les
relevés suivent la clôture au plus près. Un passage qui déborde la minute est suivi tout de suite : jamais de pause.

Séparée de continu.py (workflow desk.yml, groupe de concurrence « desk ») : une panne du desk ne touche pas
Stratégie 3.0 ni le comité, et l'inverse. Le code et l'état du desk sont dans le dépôt privé desk-agents, ouvert avec
sa clé de déploiement (CLE_DESK_AGENTS). Le journal public n'affiche que des compteurs.

État poussé toutes les 10 min, ou tout de suite quand le passage a créé etat/pousser (ordre, remplissage, sortie,
coupe-circuit, nouvelle version de la stratégie).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
DESK = ICI / "desk-agents"
DUREE = float(os.environ.get("DUREE_S", 5 * 3600 + 40 * 60))
PAS, POUSSE, CALE = 60, 600, 2


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(DESK), *args], capture_output=True, text=True, timeout=120)


def etat_sain() -> bool:
    for f in (DESK / "etat").glob("*.json"):
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
    return True


def tirer() -> bool:
    ok = git("pull", "-q", "--rebase", "--autostash").returncode == 0
    if not ok or not etat_sain():
        git("rebase", "--abort")
        git("checkout", "-q", "HEAD", "--", "etat")
        git("stash", "drop")
        ok = etat_sain()
    return ok


def pousser() -> str:
    if not etat_sain():
        git("checkout", "-q", "HEAD", "--", "etat")
        return "REFUSÉ (état illisible, restauré)"
    git("add", "etat")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return "rien"
    git("commit", "-q", "-m", f"desk : {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC")
    for _ in range(3):
        if tirer() and git("push", "-q").returncode == 0:
            return "poussé"
        time.sleep(5)
    return "ÉCHEC"


def passage() -> dict:
    r = subprocess.run([sys.executable, "-m", "desk.tour"], cwd=DESK, capture_output=True, text=True, timeout=240,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"erreur": f"code {r.returncode}"}


def main() -> int:
    fin, dernier_push, n = time.time() + DUREE, time.time(), 0
    while time.time() < fin:
        debut = time.time()
        n += 1
        tirer()                     # une nouvelle version de strategie.json poussée entre-temps est prise tout de suite
        try:
            r = passage()
        except subprocess.TimeoutExpired:
            r = {"erreur": "délai dépassé"}
        signal = DESK / "etat" / "pousser"
        pousse = "—"
        if signal.exists() or time.time() - dernier_push >= POUSSE:
            signal.unlink(missing_ok=True)
            pousse, dernier_push = pousser(), time.time()
        print(f"{time.strftime('%H:%M', time.gmtime())} UTC · desk tour {n} · "
              f"{'erreur' if r.get('erreur') else 'ok'} · {r.get('evenements', 0)} événement(s) · "
              f"{r.get('duree_s', '?')} s · état {pousse}", flush=True)
        time.sleep(max(0, (debut // PAS + 1) * PAS + CALE - time.time()))
    print(f"fin de la tâche desk, état {pousser()}, la suivante prend le relais", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
