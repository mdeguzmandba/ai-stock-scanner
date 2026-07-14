#!/bin/bash
# run.sh — Install deps and run the AI Pre-Market Stock Scanner
# Usage: ./run.sh [--mode normal|aggressive|conservative] [--dry-run] [--no-telegram]

set -e
cd "$(dirname "$0")"

echo "📦 Installing dependencies..."
pip3 install -r requirements.txt -q --break-system-packages

echo "🔍 Starting scanner..."
python3 scanner/scanner.py "$@"
