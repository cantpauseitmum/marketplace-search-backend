#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "🎯 Uruchamianie MarketplaceSearch Backend..."
echo "=========================================================="

if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ Nie znaleziono zainstalowanego Pythona (python3)."
    exit 1
fi

echo "Używany interpreter: $($PYTHON_CMD --version)"
$PYTHON_CMD server.py
