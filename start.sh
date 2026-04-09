#!/usr/bin/env bash
# Quick start script — runs backend and frontend in parallel

set -e

# Check env
if [ ! -f backend/.env ]; then
  echo "⚠  No backend/.env found. Copy .env.example → backend/.env and fill in ANTHROPIC_API_KEY."
  exit 1
fi

echo "🚀 Starting Hootly..."

# Backend
(
  cd backend
  pip install -r requirements.txt -q
  uvicorn main:app --reload --port 8000
) &

# Frontend
(
  cd frontend
  npm install --silent
  npm run dev
) &

wait
