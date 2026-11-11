#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== 1. Khởi động PostgreSQL + pgvector & Backend FastAPI qua Docker Compose ==="
cd "$ROOT_DIR/backend/docker"
docker compose up -d --build

echo "=== 2. Khởi động Frontend React + Vite (Port 5173) ==="
cd "$ROOT_DIR/frontend"
npm run dev
