#!/bin/sh
set -e

echo "=== Bookstore API Container Startup ==="

# Wait for PostgreSQL to become reachable
echo "Checking database readiness..."
python - << 'EOF'
import os
import socket
import time
import urllib.parse
import sys

db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/bookstore")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

try:
    parsed = urllib.parse.urlparse(db_url)
    host = parsed.hostname or "db"
    port = parsed.port or 5432
except Exception as e:
    print(f"Error parsing DATABASE_URL: {e}", file=sys.stderr)
    sys.exit(1)

print(f"Waiting for PostgreSQL service at {host}:{port}...")
retries = 30
for attempt in range(1, retries + 1):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"Successfully connected to PostgreSQL at {host}:{port}!")
            sys.exit(0)
    except Exception:
        print(f"PostgreSQL not ready yet (attempt {attempt}/{retries}). Retrying in 1s...")
        time.sleep(1)

print("Error: Timed out waiting for PostgreSQL to become available.", file=sys.stderr)
sys.exit(1)
EOF

# Run database migrations automatically on startup
echo "Running database migrations with Alembic..."
uv run alembic upgrade head
echo "Migrations completed successfully."

# Start FastAPI application
echo "Starting Uvicorn web server..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
