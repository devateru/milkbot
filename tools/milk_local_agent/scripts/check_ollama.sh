#!/usr/bin/env bash
set -euo pipefail

ollama list
curl -fsS http://127.0.0.1:11434/api/tags
echo
