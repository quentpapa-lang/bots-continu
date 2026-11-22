#!/usr/bin/env bash
# À lancer UNE fois par Quentin (créer un accès est refusé à Claude) :
#   ! bash /c/Users/quent/bots-continu/installer-cle-desk.sh
# Crée la clé de déploiement du desk (écriture sur desk-agents seulement), la range en secret de bots-continu,
# efface la clé du disque, puis démarre la boucle du desk. Ne touche pas aux clés ni à la boucle existantes.
set -euo pipefail
K="$(mktemp -d)"
trap 'rm -rf "$K"' EXIT
ssh-keygen -q -t ed25519 -N "" -C "bots-continu desk-agents" -f "$K/desk"
gh repo deploy-key add "$K/desk.pub" --allow-write -t "bots-continu (ecriture)" -R quentpapa-lang/desk-agents
gh secret set CLE_DESK_AGENTS -R quentpapa-lang/bots-continu < "$K/desk"
gh workflow run desk.yml -R quentpapa-lang/bots-continu
echo
echo "OK — cle posee, desk lance. Suivi : https://github.com/quentpapa-lang/bots-continu/actions/workflows/desk.yml"
