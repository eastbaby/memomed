#!/bin/bash
# 启动 Memomed 后端
echo "Starting Memomed Backend on port 8010..."
cd "$(dirname "$0")/backend"
uv run uvicorn main:app --reload --port 8010
