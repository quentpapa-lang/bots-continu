# bots-continu — boucle minute par minute des bots papier

Racine « Bots h24 » n° 3. Règles universelles : `~/.claude/CLAUDE.md`. Ce dépôt ne contient que la boucle : le code et l'état des bots sont dans des dépôts privés, ouverts avec une clé de déploiement par dépôt.

## Où ça tourne
- **GitHub Actions** : `.github/workflows/continu.yml`, déclencheur toutes les 30 min, une seule tâche à la fois. Chaque tâche dure environ 5 h 40 et passe le relais à la suivante.
- **Desk d'agents IA** (depuis le 2026-11-22) : workflow séparé `desk.yml` + `desk_continu.py`, groupe de concurrence `desk`, clé `CLE_DESK_AGENTS` (posée par `installer-cle-desk.sh`). Indépendant de `continu.yml` : l'un peut tomber sans l'autre.
- `continu.py` : la boucle. `tour_s3.py` : un passage de Stratégie 3.0. `installer-cles.sh` : pose des clés de déploiement.
- **Papier uniquement** : les machines GitHub sont aux États-Unis, où BingX est interdit.

## Règles dures
- **Ne jamais lire, écrire ni afficher une clé de déploiement ou un secret.** Le journal n'affiche que des compteurs : le garder ainsi (aucune donnée de compte ni de position dans un log).
- Ne pas casser la continuité : un seul runner actif à la fois, le relais ne doit pas laisser deux boucles en parallèle ni un trou.
- Toute modification du déclencheur ou de la boucle se teste hors production avant d'être poussée. Quentin décide de ce qui touche `continu.yml`.
- Aucune logique de stratégie ici : elle vit dans `strategie3`. Ce dépôt ne fait que l'orchestration.
- Rien de ce dépôt ne va sur Vercel.

## Définition de « terminé »
La boucle tourne sur au moins un relais complet sans trou ni doublon, le journal ne contient que des compteurs, et aucune clé n'apparaît dans un log ou un commit.
