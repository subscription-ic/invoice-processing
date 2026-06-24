#!/bin/bash
# Quick start script for AP Automation Platform

set -e

echo "🚀 Starting AP Automation Platform..."

# Copy env if needed
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  .env created from .env.example — update OPENAI_API_KEY before running"
fi

# Build and start all services
docker compose up --build -d

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 15

# Run database migrations
echo "📦 Running database migrations..."
docker compose exec backend alembic upgrade head

# Seed the database
echo "🌱 Seeding database with reference data..."
docker compose exec backend python /app/../seed/seed.py 2>/dev/null || \
docker compose exec backend python -c "
import sys
sys.path.insert(0, '/app')
exec(open('/seed/seed.py').read())
" || echo "Seed script needs manual run: docker compose exec backend python seed/seed.py"

echo ""
echo "✅ AP Automation Platform is running!"
echo ""
echo "  🌐 Frontend:        http://localhost:3000"
echo "  🔌 Backend API:     http://localhost:8000"
echo "  📚 API Docs:        http://localhost:8000/api/docs"
echo "  🌸 Celery Monitor:  http://localhost:5555"
echo "  🗄️  Database:        localhost:5432"
echo ""
echo "  Default Login: admin@company.com / password123"
echo ""
echo "  📋 To view logs:    docker compose logs -f backend"
echo "  🛑 To stop:         docker compose down"