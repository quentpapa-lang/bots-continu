"""Un passage de Stratégie 3.0 (lancé dans le dossier du dépôt privé strategie3). N'imprime que des compteurs."""
import json
import logging
import sys
import time

sys.path.insert(0, ".")
logging.disable(logging.INFO)

from src import commands  # noqa: E402
from src.core.config import ROOT  # noqa: E402
from src.data import store  # noqa: E402
from src.runner import refresh_performance, step  # noqa: E402

lignes = commands.apply_pending(ROOT / "etat" / "consignes.json")
step()
store.kv_set("runner_heartbeat", time.time())
store.kv_set("runner_continu", time.time())          # les workflows de secours ne passent pas tant que ceci est frais
if time.time() - (store.kv_get("perf_refresh", 0) or 0) > 3600:
    refresh_performance()
    store.kv_set("perf_refresh", time.time())
with store.db() as con:
    n = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
print(json.dumps({"consignes": len(lignes), "ordres": n}))
