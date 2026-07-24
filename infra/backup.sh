#!/usr/bin/env bash
# Daily backup of data/ (SQLite + audio) with 7-day rotation. Suggested cron:
#   0 4 * * * /home/triagebox/triagebox/infra/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups-triagebox}"
mkdir -p "$BACKUP_DIR"

# Consistent DB copy even while the service is writing
sqlite3 data/triagebox.db "VACUUM INTO '$BACKUP_DIR/triagebox-snapshot.db'"
tar czf "$BACKUP_DIR/triagebox-$(date +%F).tar.gz" -C "$BACKUP_DIR" triagebox-snapshot.db -C "$PWD" data/audio
rm -f "$BACKUP_DIR/triagebox-snapshot.db"

# Rotation: keep the 7 most recent
ls -1t "$BACKUP_DIR"/triagebox-*.tar.gz | tail -n +8 | xargs -r rm -f
echo "Backup OK: $BACKUP_DIR"
