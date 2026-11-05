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
import urllib.request
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


def etat_sain(depot: Path) -> bool:
    """Aucun marqueur de conflit dans etat/ et tous les .json lisibles. Le 2026-11-04, un --autostash en conflit a
    laissé « <<<<<<< Updated upstream » dans bot-agents/etat/etat.json, puis la boucle l'a commité : suivi mort 3 h."""
    for f in (depot / "etat").glob("*.json"):
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
    return True


def tirer(depot: Path) -> bool:
    ok = git(depot, "pull", "-q", "--rebase", "--autostash").returncode == 0
    if not ok or not etat_sain(depot):
        # conflit : on garde la version distante (une minute de suivi perdue, recalculée au tour suivant)
        git(depot, "rebase", "--abort")
        git(depot, "checkout", "-q", "HEAD", "--", "etat")
        git(depot, "stash", "drop")
        ok = etat_sain(depot)
    return ok


def pousser(depot: Path, message: str, chemins: list[str]) -> str:
    if not etat_sain(depot):
        git(depot, "checkout", "-q", "HEAD", "--", "etat")
        return "REFUSÉ (état illisible, restauré)"
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


# ---- agents 24/24 (demande de Quentin, 2026-11-05) : un cycle de veille toutes les 5 min, lancé en arrière-plan pour ne
# jamais bloquer le suivi à la minute ; le cycle décide lui-même s'il appelle l'IA (délais 15 / 20 / 30 min selon le
# régime). Un mouvement brutal du prix (≥ 1,5 % en 10 min) lance un cycle FORCÉ sans attendre. Sans clé GEMINI_API_KEY
# dans ce dépôt, rien ne se lance et le workflow de secours de bot-agents (toutes les 2 h) reste la veille.
VEILLE_PAS, CHOC_RAPIDE, CHOC_FENETRE, FORCE_ESPACE = 300, 0.015, 600, 180
veille = {"proc": None, "t": 0.0, "force_t": 0.0, "prix": []}


def prix_btc() -> float | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "https://open-api.bingx.com/openApi/swap/v2/quote/price?symbol=BTC-USDT",
                headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
            d = json.loads(r.read())["data"]
        return float((d[0] if isinstance(d, list) else d)["price"])
    except Exception:
        return None


def veille_en_cours() -> bool:
    return veille["proc"] is not None and veille["proc"].poll() is None


def veille_tour() -> str:
    """Termine le cycle fini (journalise sa 1re ligne seulement : le détail reste dans le dépôt privé), en lance un autre si dû."""
    p = veille["proc"]
    if p is not None and p.poll() is not None:
        sortie = (p.stdout.read() if p.stdout else "").strip().splitlines()
        veille["proc"] = None
        pousse_apres = True
        info = (sortie[0][:120] if sortie else "sans sortie") + ("" if p.returncode == 0 else f" · code {p.returncode}")
    else:
        pousse_apres, info = False, ""
    if not os.environ.get("GEMINI_API_KEY"):
        return "veille inactive (pas de clé)"
    if veille_en_cours():
        return "veille en cours"
    if verrou_comite():
        return "veille en pause (comité)"
    maint, b = time.time(), prix_btc()
    if b:
        veille["prix"] = [(t0, v) for t0, v in veille["prix"] if maint - t0 <= CHOC_FENETRE] + [(maint, b)]
    ref = veille["prix"][0][1] if veille["prix"] else None
    choc = bool(b and ref and abs(b / ref - 1) >= CHOC_RAPIDE and maint - veille["force_t"] >= FORCE_ESPACE)
    if choc or maint - veille["t"] >= VEILLE_PAS:
        veille["t"] = maint
        if choc:
            veille["force_t"] = maint
        cmd = [sys.executable, "-m", "agents.comite", "--veille"] + (["--forcer"] if choc else [])
        veille["proc"] = subprocess.Popen(cmd, cwd=BA, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return ("veille FORCÉE (mouvement brutal) lancée" if choc else "veille lancée") + (f" · précédente : {info}" if info else "")
    return f"veille ok ({info})" if pousse_apres else "veille en attente"


def main() -> int:
    fin = time.time() + DUREE
    pousse = {"s3": time.time(), "ba": time.time()}
    ordres_vus, n = None, 0
    while time.time() < fin:
        t0 = time.time()
        n += 1
        # ---- Stratégie 3.0 (le plan de Zoé est recopié d'abord, depuis le dernier état du comité)
        tirer(S3)
        if not veille_en_cours():          # ne pas tirer pendant qu'un cycle écrit dans etat/
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
        if not veille_en_cours():
            tirer(BA)
        if verrou_comite():
            ba = "pause (comité en cours) · " + pousser(BA, f"suivi : {horodatage()}", ["etat"])
            pousse["ba"] = time.time()
        else:
            s = subprocess.run([sys.executable, "-m", "agents.comite", "--suivi"], cwd=BA, capture_output=True,
                               text=True, timeout=240)
            ba = "suivi ok" if s.returncode == 0 else "suivi en échec"
            # Consigne de la veille appliquée : poussée TOUT DE SUITE, avec « CONSIGNE » dans le message. Le workflow
            # notifier.yml de bot-agents (qui a les secrets Telegram, absents d'ici) prévient alors Quentin.
            consigne = "consigne de la veille appliquée" in (s.stdout or "")
            if consigne or time.time() - pousse["ba"] > POUSSE_BA:
                ba += " · " + pousser(BA, f"suivi : {horodatage()}" + (" · CONSIGNE" if consigne else ""), ["etat"])
                pousse["ba"] = time.time()
        vt = veille_tour()
        if vt.startswith("veille ok"):
            pousse["ba"] = 0               # un cycle vient de finir : on pousse ses consignes au prochain tour
        print(f"{horodatage()} · tour {n} · S3 {'erreur' if 'erreur' in r else 'ok'} ({etat}) · comité {ba} · {vt}",
              flush=True)
        time.sleep(max(1.0, PAS - (time.time() - t0)))
    # fin de tâche : laisser finir le cycle de veille en cours, puis tout pousser avant de passer la main
    if veille_en_cours():
        try:
            veille["proc"].wait(timeout=240)
        except Exception:
            veille["proc"].kill()
    pousser(S3, f"état : {horodatage()}", ["etat/state.sqlite", "etat/plan_zoe.json"])
    if not verrou_comite():
        pousser(BA, f"suivi : {horodatage()}", ["etat"])
    print("fin de la tâche, la suivante prend le relais", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
