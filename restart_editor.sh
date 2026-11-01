#!/usr/bin/env bash
# Restart the SSF2T editor server (stop whatever is on the port, start fresh).
# Usage: ./restart_editor.sh [port]      (default 8765)
#        PYTHON=/path/to/python ./restart_editor.sh   (default python3)
#        ./restart_editor.sh stop        (just stop it)
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
# game files: SSF2T_ROM_DIR (default: the folder that contains the editor), see paths.py
LOG="$DIR/server.log"

ACTION="start"
PORT=8765
if [ "${1:-}" = "stop" ]; then ACTION="stop"; PORT="${2:-8765}"
elif [ -n "${1:-}" ]; then PORT="$1"; fi

# pid listening on the port (empty if none)
port_pid() {
  local pid
  pid="$(ss -ltnpH "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)"
  # ss may not show the owner (other user / restricted namespace): fall back to
  # matching our own uvicorn command line, but only if something is listening.
  if [ -z "$pid" ] && ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q .; then
    pid="$(pgrep -f "uvicorn app:app --host 127.0.0.1 --port $PORT" | head -1)"
  fi
  echo "$pid"
}

stop_server() {
  local pid; pid="$(port_pid)"
  if [ -z "$pid" ]; then echo "nothing listening on :$PORT"; return 0; fi
  # Only kill it if it really is our uvicorn app, never an unrelated process.
  if ! tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'uvicorn.*app:app'; then
    echo "pid $pid holds :$PORT but is not the editor's uvicorn; leaving it alone:"
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null; echo
    return 1
  fi
  echo "stopping editor server (pid $pid)..."
  kill "$pid"
  for _ in $(seq 1 50); do        # wait up to 5s for a clean exit
    [ -z "$(port_pid)" ] && { echo "stopped."; return 0; }
    sleep 0.1
  done
  echo "still running, sending SIGKILL..."
  kill -9 "$pid" 2>/dev/null
  sleep 0.5
  [ -z "$(port_pid)" ]
}

stop_server || exit 1
[ "$ACTION" = "stop" ] && exit 0

cd "$DIR" || exit 1
echo "starting editor on http://127.0.0.1:$PORT (log: $LOG)"
setsid "$PY" -m uvicorn app:app --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 </dev/null &

for _ in $(seq 1 100); do         # wait up to 10s for it to listen
  if [ -n "$(port_pid)" ]; then
    echo "up: http://127.0.0.1:$PORT  (pid $(port_pid))"
    echo "tip: hard-refresh the browser (Ctrl-Shift-R) to drop cached sprites."
    exit 0
  fi
  sleep 0.1
done
echo "server did not come up. last log lines:"
tail -15 "$LOG"
exit 1
