# PowerShell Script: Quick Test
# Tests basic functionality of the Log Aggregator

Write-Host "=== Log Aggregator Quick Test ===" -ForegroundColor Cyan
Write-Host ""

$baseUrl = "http://localhost:8080"

# Test 1: Health Check
Write-Host "1. Testing Health Endpoint..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "$baseUrl/health" -Method Get
    Write-Host "   Status: $($health.status)" -ForegroundColor Green
    Write-Host "   Database: $($health.database)"
    Write-Host "   Broker: $($health.broker)"
} catch {
    Write-Host "   FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Test 2: Get Initial Stats
Write-Host "2. Getting Initial Stats..." -ForegroundColor Yellow
$statsBefore = Invoke-RestMethod -Uri "$baseUrl/stats" -Method Get
Write-Host "   Received: $($statsBefore.received)"
Write-Host "   Unique: $($statsBefore.unique_processed)"
Write-Host "   Duplicates: $($statsBefore.duplicate_dropped)"
Write-Host ""

# Test 3: Publish Single Event
Write-Host "3. Publishing Single Event..." -ForegroundColor Yellow
$eventId = "evt-test-" + [guid]::NewGuid().ToString()
$event = @{
    topic = "test-topic"
    event_id = $eventId
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    source = "test-script"
    payload = @{
        message = "Test event from PowerShell"
        test_run = $true
    }
} | ConvertTo-Json

$result = Invoke-RestMethod -Uri "$baseUrl/publish" -Method Post -Body $event -ContentType "application/json"
Write-Host "   Success: $($result.success)"
Write-Host "   Is Duplicate: $($result.is_duplicate)"
Write-Host ""

# Test 4: Publish Same Event (Should be duplicate)
Write-Host "4. Publishing Same Event (Duplicate Test)..." -ForegroundColor Yellow
$result2 = Invoke-RestMethod -Uri "$baseUrl/publish" -Method Post -Body $event -ContentType "application/json"
Write-Host "   Success: $($result2.success)"
Write-Host "   Is Duplicate: $($result2.is_duplicate)" -ForegroundColor $(if($result2.is_duplicate){"Green"}else{"Red"})
Write-Host ""

# Test 5: Get Events
Write-Host "5. Getting Events for Topic..." -ForegroundColor Yellow
$events = Invoke-RestMethod -Uri "$baseUrl/events?topic=test-topic&limit=5" -Method Get
Write-Host "   Found: $($events.count) events"
Write-Host ""

# Test 6: Get Final Stats
Write-Host "6. Getting Final Stats..." -ForegroundColor Yellow
$statsAfter = Invoke-RestMethod -Uri "$baseUrl/stats" -Method Get
Write-Host "   Received: $($statsAfter.received) (+$($statsAfter.received - $statsBefore.received))"
Write-Host "   Unique: $($statsAfter.unique_processed) (+$($statsAfter.unique_processed - $statsBefore.unique_processed))"
Write-Host "   Duplicates: $($statsAfter.duplicate_dropped) (+$($statsAfter.duplicate_dropped - $statsBefore.duplicate_dropped))"
Write-Host ""

Write-Host "=== Quick Test Complete ===" -ForegroundColor Cyan
