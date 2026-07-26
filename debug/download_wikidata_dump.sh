#!/usr/bin/env bash
# Télécharge le dump JSON Wikidata (latest-all.json.bz2) avec reprise.
# Usage :
#   chmod +x debug/download_wikidata_dump.sh
#   ./debug/download_wikidata_dump.sh
#   ./debug/download_wikidata_dump.sh /mnt/data/wikidata
#
# Besoin disque : souvent 80–150+ Go libres (dump compressé ~100 Go selon la date).
set -euo pipefail

DEST_DIR="${1:-$HOME/wikidata-dump}"
DUMP_URL="https://dumps.wikimedia.org/wikidatawiki/entities/latest-all.json.bz2"
# Alternative datée (exemple) :
# DUMP_URL="https://dumps.wikimedia.org/wikidatawiki/entities/20260721/wikidata-20260721-all.json.bz2"

mkdir -p "$DEST_DIR"
cd "$DEST_DIR"

FILE="$(basename "$DUMP_URL")"
echo "==> Destination : $DEST_DIR/$FILE"
echo "==> URL         : $DUMP_URL"

# Espace libre (Ko)
avail_kb=$(df -Pk . | awk 'NR==2 {print $4}')
avail_gb=$((avail_kb / 1024 / 1024))
echo "==> Espace libre ≈ ${avail_gb} Go"
if [[ "$avail_gb" -lt 110 ]]; then
  echo "[warn] Moins de 110 Go libres — le dump fait ~95 Go compressé (latest-all.json.bz2)."
  if [[ "${FORCE:-}" != "1" ]]; then
    read -r -p "Continuer quand même ? [y/N] " ans || true
    if [[ "${ans:-}" != "y" && "${ans:-}" != "Y" ]]; then
      exit 1
    fi
  fi
fi

echo "==> Téléchargement (reprise activée)…"
if command -v aria2c >/dev/null 2>&1; then
  # Plus rapide / robuste si aria2 est installé
  aria2c -c -x 4 -s 4 -k 1M \
    --user-agent="MetaKavita-WikidataDump/1.0 (self-hosted; educational)" \
    -o "$FILE" \
    "$DUMP_URL"
elif command -v wget >/dev/null 2>&1; then
  wget -c --show-progress \
    --user-agent="MetaKavita-WikidataDump/1.0 (self-hosted; educational)" \
    -O "$FILE" \
    "$DUMP_URL"
else
  # curl : -C - = resume
  curl -L -C - \
    -A "MetaKavita-WikidataDump/1.0 (self-hosted; educational)" \
    -o "$FILE" \
    "$DUMP_URL"
fi

echo "==> Vérification taille…"
ls -lh "$FILE"
echo "==> OK. Ensuite (extraction manga/comic/book) :"
echo "  PYTHONUNBUFFERED=1 python3 -u debug/extract_wikidata_dump.py \\"
echo "    --dump \"$DEST_DIR/$FILE\" \\"
echo "    --out data/wikidata.db \\"
echo "    --type manga \\"
echo "    2>&1 | tee -a data/wikidata_extract.log"
