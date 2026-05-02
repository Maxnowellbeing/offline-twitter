#!/bin/bash
cd "$(dirname "$0")"

# Load .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Start app
python3 app.py
