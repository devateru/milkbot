#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-${MILK_TUNNEL_TARGET:-}}"
if [[ -z "${TARGET}" ]]; then
  echo "usage: $0 USER@SERVER_HOST"
  exit 2
fi

ssh -N \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18080:127.0.0.1:18080 \
  "${TARGET}"
