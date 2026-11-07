#!/bin/sh
# Ejecutar desde la raíz del proyecto. Conserva las copias fuera del miniPC.
set -eu
umask 077
mkdir -p backups
destination="backups/entrelineas-$(date -u +%Y%m%d-%H%M%S).dump"
docker compose exec -T db pg_dump -U entrelineas -d entrelineas -Fc > "$destination"
if [ ! -s "$destination" ]; then
  echo "La copia no se ha completado." >&2
  exit 1
fi
echo "Copia creada: $destination"
