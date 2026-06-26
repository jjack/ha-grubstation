#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

# Clean up broken virtualenv link if switching between host and dev container
if [ -L .venv/bin/python ] && [ ! -e .venv/bin/python ]; then
    echo "Broken virtual environment detected (linked to a non-existent Python interpreter). Recreating..."
    rm -rf .venv
fi

echo "installing packages"
export UV_LINK_MODE=copy
uv sync

echo "Installing pre-commit hooks..."
uv run pre-commit install
