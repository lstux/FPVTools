#!/bin/sh
# Vérifie que les liens http(s) des pages répondent (code 2xx, redirections suivies).
# Usage : ./check-links.sh [page.html ...]   Sans argument : index.html et liens.html du dossier du script.
# Code de retour : 0 si tout répond, 1 sinon. Les adresses appelées par le script d'index.html (API météo, tuiles
# de carte…) ne sont pas des liens href : elles ne sont pas vérifiées ici.
# Un code 429 (trop de requêtes, fréquent sur GitHub) est réessayé quelques secondes plus tard.
# Certains sites refusent les requêtes automatiques (403) alors qu'ils s'ouvrent très bien dans un navigateur :
# à vérifier à la main avant de retirer un lien.
set -eu
if [ "$#" -eq 0 ]; then set -- "$(dirname "$0")/index.html" "$(dirname "$0")/liens.html"; fi
for PAGE in "$@"; do [ -r "${PAGE}" ] || { echo "Erreur : ${PAGE} illisible" >&2; exit 2; }; done
export UA="Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"

URLS="$(cat "$@" | grep -oE 'href="https?://[^"]+"' | sed 's/^href="//; s/"$//' | sort -u)"
TOTAL="$(printf '%s\n' "${URLS}" | grep -c .)"
printf '%s lien(s) à vérifier dans %s\n' "${TOTAL}" "$*" >&2

# 8 requêtes en parallèle ; xargs rend 123 si une vérification a échoué
if printf '%s\n' "${URLS}" | xargs -P 8 -I{} sh -c '
  code="$(curl -sL -o /dev/null -w "%{http_code}" -A "${UA}" --max-time 20 --retry 3 --retry-delay 3 "{}" 2>/dev/null || true)"
  case "${code}" in 2*) ;; *) printf "%s %s\n" "${code:-000}" "{}"; exit 1;; esac'; then
  echo "Tous les liens répondent." >&2
else
  echo "Des liens ne répondent pas (voir ci-dessus)." >&2
  exit 1
fi
