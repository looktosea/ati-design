#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
lock_dir="${ATI_SCHEDULE_LOCK_DIR:-/tmp/ati-schedule.lock}"
if ! mkdir "$lock_dir" 2>/dev/null; then
  echo 'ATI schedule already running; skip'
  exit 0
fi
cleanup() { rmdir "$lock_dir" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
python3 -m ati schedule
status=$?
exit "$status"
