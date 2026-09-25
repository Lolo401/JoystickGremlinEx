#!/usr/bin/env bash
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python gremlinEx.py "$@"
elif [[ -x venv/bin/python ]]; then
  exec venv/bin/python gremlinEx.py "$@"
else
  exec python3 gremlinEx.py "$@"
fi
