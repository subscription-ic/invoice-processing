# Quick start script for AP Automation Platform (Windows PowerShell)

Write-Host "🚀 Starting AP Automation Platform..." -ForegroundColor Green

# Copy env if needed
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "⚠️  .env created from .env.example — update OPENAI_API_KEY before running" -ForegroundColor Yellow
}

# Build and start all services
Write-Host "🐳 Building and starting Docker containers..." -ForegroundColor Cyan
docker compose up --build -d

Write-Host "⏳ Waiting for services to be healthy (30s)..." -ForegroundColor Cyan
Start-Sleep -Seconds 30

# Run database migrations
Write-Host "📦 Running database migrations..." -ForegroundColor Cyan
docker compose exec backend alembic upgrade head

# Seed the database
Write-Host "🌱 Seeding database with reference data..." -ForegroundColor Cyan
docker compose exec backend python /seed/seed.py

Write-Host ""
Write-Host "✅ AP Automation Platform is running!" -ForegroundColor Green
Write-Host ""
Write-Host "  🌐 Frontend:        http://localhost:3000" -ForegroundColor White
Write-Host "  🔌 Backend API:     http://localhost:8000" -ForegroundColor White
Write-Host "  📚 API Docs:        http://localhost:8000/api/docs" -ForegroundColor White
Write-Host "  🌸 Celery Monitor:  http://localhost:5555" -ForegroundColor White
Write-Host ""
Write-Host "  Default Login: admin@company.com / password123" -ForegroundColor Yellow
Write-Host ""
Write-Host "  📋 To view logs:    docker compose logs -f backend" -ForegroundColor Gray
Write-Host "  🛑 To stop:         docker compose down" -ForegroundColor Gray