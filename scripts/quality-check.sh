#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Backend unit tests =="
cd "$ROOT_DIR/backend"
uv run python -m unittest \
  test.test_agent_event_store \
  test.test_agent_scenarios \
  test.test_agent_scenarios_live \
  test.test_agent_v1 \
  test.test_subject_registry

echo "== Frontend lint =="
cd "$ROOT_DIR/frontend"
pnpm run lint

echo "== Frontend agent tests =="
pnpm run test:agent

echo "== Frontend build =="
pnpm run build

echo "== Quality gate passed =="
