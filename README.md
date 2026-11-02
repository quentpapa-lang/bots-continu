# bots-continu

Boucle minute par minute des bots papier de Quentin (Stratégie 3.0 et suivi du comité). Ce dépôt ne contient que
la boucle : le code et l'état des bots sont dans des dépôts privés, ouverts avec une clé de déploiement par dépôt.
Le journal n'affiche que des compteurs.

- `continu.py` : la boucle (~5 h 40 par tâche, relais par la tâche en attente).
- `tour_s3.py` : un passage de Stratégie 3.0.
- `.github/workflows/continu.yml` : déclencheur toutes les 30 min, une seule tâche à la fois.

Papier uniquement : les machines GitHub sont aux États-Unis, où BingX est interdit.
