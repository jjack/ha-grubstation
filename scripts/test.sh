#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

uv run pytest --cov=custom_components.grubstation "$@"
