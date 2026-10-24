#!/usr/bin/env bash
set -e

# Change directory to backend folder
cd "$(dirname "$0")"

# Check if .env exists, if not copy from .env.example
if [ ! -f .env ]; then
  echo "⚠️  .env file not found. Creating from .env.example..."
  cp .env.example .env
  echo "ℹ️  Created .env. Please configure your credentials if needed."
fi

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
  echo "📦 Creating virtual environment (.venv)..."
  python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Install / update requirements
echo "📥 Checking and installing dependencies..."
pip install -q -r requirements.txt

# Start FastAPI server using uvicorn
echo "🚀 Starting FastAPI backend on http://localhost:8000 ..."
echo "📖 Swagger Docs: http://localhost:8000/docs"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

