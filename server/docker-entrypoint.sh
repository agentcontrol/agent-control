#!/bin/bash
set -e

echo "==================================="
echo "Agent Control Server - Starting"
echo "==================================="

# Run database migrations
echo "Running database migrations..."
if [ -f "/app/alembic.ini" ]; then
    alembic upgrade head
    echo "✓ Database migrations complete"
else
    echo "⚠ alembic.ini not found, skipping migrations"
fi

echo "==================================="
echo "Starting server..."
echo "==================================="

# Execute the main command (passed as arguments or default CMD)
exec "$@"
