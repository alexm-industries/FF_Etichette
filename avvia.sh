#!/usr/bin/env bash
# FF Etichette — avvio su macOS / Linux: crea l'ambiente, installa le dipendenze, avvia.
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Serve Python 3.10 o più recente. Su Mac: brew install python" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creo l'ambiente Python (.venv)…"
  "$PY" -m venv .venv
fi

# reinstalla solo se requirements.txt è cambiato
if ! cmp -s requirements.txt .venv/.requirements.installati 2>/dev/null; then
  echo "Installo le dipendenze…"
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  if ! .venv/bin/python -m pip install -r requirements.txt; then
    echo >&2
    echo "Installazione non riuscita. Se l'errore riguarda pycairo, installa cairo:" >&2
    echo "  brew install cairo pkg-config     (macOS)" >&2
    echo "  sudo apt install libcairo2-dev pkg-config python3-dev     (Debian/Ubuntu)" >&2
    exit 1
  fi
  cp requirements.txt .venv/.requirements.installati
fi

exec .venv/bin/python -m app
