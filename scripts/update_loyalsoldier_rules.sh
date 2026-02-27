#!/bin/zsh
set -euo pipefail

PORTS=(9097 9090)
PROVIDERS=(reject icloud apple google proxy direct private gfw telegram lancidr cncidr applications final)
SECRET_HEADER="Authorization: Bearer set-your-secret"

wait_for_api() {
  local port="$1"
  local i=0
  while [[ $i -lt 30 ]]; do
    if curl -sS -m 2 "http://127.0.0.1:${port}/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    ((i++))
  done
  return 1
}

update_port() {
  local port="$1"
  local ok=0
  for p in "${PROVIDERS[@]}"; do
    # Try without auth first, then with default secret header.
    if curl -sS -m 5 -X PUT "http://127.0.0.1:${port}/providers/rules/${p}" >/dev/null 2>&1; then
      ok=1
      continue
    fi
    if curl -sS -m 5 -H "$SECRET_HEADER" -X PUT "http://127.0.0.1:${port}/providers/rules/${p}" >/dev/null 2>&1; then
      ok=1
      continue
    fi
  done
  if [[ $ok -eq 1 ]]; then
    return 0
  fi
  return 1
}

# If Clash Verge API isn't up, skip this run.
if ! wait_for_api 9097 && ! wait_for_api 9090; then
  exit 1
fi

for port in "${PORTS[@]}"; do
  if wait_for_api "$port"; then
    if update_port "$port"; then
      exit 0
    fi
  fi
done

exit 1
