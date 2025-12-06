# PowerShell Helper Script for Log Aggregator
# Run: .\scripts\help.ps1

Write-Host "=== Log Aggregator Helper Scripts ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "Available commands:" -ForegroundColor Yellow
Write-Host ""

Write-Host "  Start all services:" -ForegroundColor Green
Write-Host "    docker compose up --build"
Write-Host ""

Write-Host "  Start in background:" -ForegroundColor Green
Write-Host "    docker compose up --build -d"
Write-Host ""

Write-Host "  Run publisher (event simulator):" -ForegroundColor Green
Write-Host "    docker compose --profile publisher up publisher"
Write-Host ""

Write-Host "  Run with multiple workers:" -ForegroundColor Green
Write-Host "    docker compose --profile workers up -d"
Write-Host ""

Write-Host "  View logs:" -ForegroundColor Green
Write-Host "    docker compose logs -f aggregator"
Write-Host ""

Write-Host "  Stop all:" -ForegroundColor Green
Write-Host "    docker compose down"
Write-Host ""

Write-Host "  Stop and remove volumes (reset data):" -ForegroundColor Green
Write-Host "    docker compose down -v"
Write-Host ""

Write-Host "  Check health:" -ForegroundColor Green
Write-Host "    Invoke-RestMethod http://localhost:8080/health"
Write-Host ""

Write-Host "  Check stats:" -ForegroundColor Green
Write-Host "    Invoke-RestMethod http://localhost:8080/stats"
Write-Host ""

Write-Host "  Publish test event:" -ForegroundColor Green
Write-Host '    $body = @{topic="test";event_id="evt-$(New-Guid)";timestamp=(Get-Date -Format o);source="test";payload=@{}} | ConvertTo-Json'
Write-Host '    Invoke-RestMethod -Method Post -Uri http://localhost:8080/publish -Body $body -ContentType "application/json"'
Write-Host ""

Write-Host "  Run tests:" -ForegroundColor Green
Write-Host "    pip install -r tests/requirements.txt"
Write-Host "    pytest tests/test_aggregator.py -v"
Write-Host ""

Write-Host "  Run K6 load test:" -ForegroundColor Green
Write-Host "    k6 run k6/load_test.js"
Write-Host ""
