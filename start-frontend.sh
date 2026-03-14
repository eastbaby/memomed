#!/bin/bash
# 启动 Memomed 前端
echo "Starting Memomed Frontend..."
cd "$(dirname "$0")/frontend"
npm run dev
