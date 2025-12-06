# 🎬 Panduan Recording Video Demo

**Durasi Maksimal:** 25 menit  
**Format:** YouTube Unlisted atau Public  
**Nama File:** `UAS_SistemTerdistribusi_11221023_HylmiWahyudi`

---

## 📋 Checklist Sebelum Recording

- [ ] Docker Desktop sudah running
- [ ] Semua container dalam keadaan stopped (`docker compose down -v`)
- [ ] Terminal/PowerShell sudah terbuka
- [ ] Browser sudah terbuka (untuk akses API)
- [ ] Postman atau curl siap digunakan
- [ ] VS Code dengan project sudah terbuka

---

## ⏱️ Timeline Video (Total: ~23 menit)

| Waktu | Durasi | Section |
|-------|--------|---------|
| 0:00 | 1 min | Opening & Perkenalan |
| 1:00 | 3 min | Arsitektur & Desain |
| 4:00 | 3 min | Build & Run Docker Compose |
| 7:00 | 4 min | Demo Idempotency & Deduplication |
| 11:00 | 4 min | Demo Transaksi & Konkurensi |
| 15:00 | 3 min | Demo Persistence (Crash Recovery) |
| 18:00 | 2 min | Demo Observability |
| 20:00 | 2 min | Keamanan Jaringan |
| 22:00 | 1 min | Closing & Kesimpulan |

---

## 📝 Script Detail Per Section

---

### Section 1: Opening & Perkenalan (0:00 - 1:00) ⏱️ 1 menit

**Yang diucapkan:**
> "Assalamualaikum warahmatullahi wabarakatuh. Selamat [pagi/siang/malam], perkenalkan nama saya Hylmi Wahyudi dengan NIM 11221023. Video ini merupakan demo untuk Tugas Akhir mata kuliah Sistem Terdistribusi dan Paralel dengan tema Pub-Sub Log Aggregator Terdistribusi."

**Yang ditampilkan:**
- Tampilkan README.md di VS Code
- Scroll ke bagian deskripsi sistem

---

### Section 2: Arsitektur & Desain (1:00 - 4:00) ⏱️ 3 menit

**Yang diucapkan:**
> "Sistem ini terdiri dari 4 komponen utama yang berjalan dalam Docker Compose..."

**Langkah-langkah:**

1. **Buka file `docker-compose.yml`**
   > "Pertama, mari kita lihat arsitektur sistem pada docker-compose.yml"

2. **Jelaskan setiap service:**
   - **storage (PostgreSQL)**: "Database untuk persistent storage dengan unique constraint untuk deduplication"
   - **broker (Redis)**: "Message queue untuk async processing"
   - **aggregator**: "Service utama yang menyediakan REST API"
   - **publisher**: "Simulator event dengan configurable duplicate rate"

3. **Buka file `aggregator/init.sql`**
   > "Ini adalah schema database dengan unique constraint pada topic dan event_id untuk deduplication"

4. **Buka file `aggregator/database.py`**
   > "Di sini kita menggunakan isolation level READ COMMITTED dan pattern INSERT ON CONFLICT DO NOTHING untuk idempotent processing"

5. **Jelaskan keputusan desain:**
   > "Saya memilih READ COMMITTED karena cukup untuk use case dedup dengan unique constraint, dengan trade-off performa yang lebih baik dibanding SERIALIZABLE"

---

### Section 3: Build & Run Docker Compose (4:00 - 7:00) ⏱️ 3 menit

**Yang diucapkan:**
> "Sekarang kita akan build dan menjalankan semua service menggunakan Docker Compose"

**Commands yang dijalankan:**

```powershell
# Step 1: Pastikan tidak ada container running
docker compose down -v

# Step 2: Build dan jalankan
docker compose up --build
```

**Yang ditampilkan:**
- Terminal output saat building
- Log startup dari setiap service
- Tunggu sampai semua service healthy

**Yang diucapkan saat menunggu:**
> "Docker sedang build image untuk aggregator dan publisher. Kita menggunakan python:3.11-slim sebagai base image dengan non-root user untuk security."

**Setelah running:**
```powershell
# Buka terminal baru, cek health
curl http://localhost:8080/health
```

> "Service sudah healthy, database dan broker sudah connected"

---

### Section 4: Demo Idempotency & Deduplication (7:00 - 11:00) ⏱️ 4 menit

**Yang diucapkan:**
> "Sekarang kita akan demo fitur utama: idempotency dan deduplication"

**Langkah-langkah:**

#### 4.1 Cek Stats Awal
```powershell
curl http://localhost:8080/stats
```
> "Stats awal menunjukkan received: 0, unique_processed: 0, duplicate_dropped: 0"

#### 4.2 Publish Event Pertama
```powershell
$event = @{
    topic = "demo-logs"
    event_id = "evt-demo-001"
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    source = "demo-service"
    payload = @{ message = "First event"; level = "INFO" }
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://localhost:8080/publish -Body $event -ContentType "application/json"
```

> "Event berhasil diproses, is_duplicate: false"

#### 4.3 Publish Event yang SAMA (Duplicate Test)
```powershell
# Kirim event yang sama persis
$event = @{
    topic = "demo-logs"
    event_id = "evt-demo-001"  # SAME event_id
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    source = "demo-service"
    payload = @{ message = "First event"; level = "INFO" }
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://localhost:8080/publish -Body $event -ContentType "application/json"
```

> "Perhatikan is_duplicate: true. Event tidak diproses ulang karena sudah ada di database"

#### 4.4 Kirim Duplicate Berkali-kali
```powershell
# Kirim 5 kali
1..5 | ForEach-Object {
    Invoke-RestMethod -Method Post -Uri http://localhost:8080/publish -Body $event -ContentType "application/json"
}
```

> "Semua marked as duplicate"

#### 4.5 Cek Stats Setelah Dedup
```powershell
curl http://localhost:8080/stats
```

> "Perhatikan: received bertambah, tapi unique_processed tetap 1, dan duplicate_dropped bertambah sesuai jumlah duplikat yang dikirim"

#### 4.6 Cek Events
```powershell
curl "http://localhost:8080/events?topic=demo-logs"
```

> "Hanya ada 1 event di database meskipun kita mengirim berkali-kali"

---

### Section 5: Demo Transaksi & Konkurensi (11:00 - 15:00) ⏱️ 4 menit

**Yang diucapkan:**
> "Sekarang kita akan membuktikan bahwa sistem bebas dari race condition saat multiple worker memproses secara paralel"

**Langkah-langkah:**

#### 5.1 Jalankan Publisher dengan Batch
```powershell
# Di terminal baru
docker compose --profile publisher run -e EVENT_COUNT=1000 -e DUPLICATE_RATE=0.3 publisher
```

> "Publisher akan mengirim 1000 event dengan 30% duplicate rate"

**Saat publisher berjalan:**
> "Publisher sedang mengirim batch event. Setiap batch berisi event unik dan duplikat untuk menguji deduplication"

#### 5.2 Cek Stats Setelah Publisher
```powershell
curl http://localhost:8080/stats
```

> "Perhatikan: unique_processed + duplicate_dropped = received. Ini membuktikan consistency statistik"

#### 5.3 Demo Concurrent Requests (Opsional - jika waktu cukup)
```powershell
# Kirim 10 concurrent requests dengan event yang sama
$event = @{
    topic = "concurrent-test"
    event_id = "evt-concurrent-001"
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    source = "concurrent-test"
    payload = @{ test = "concurrent" }
} | ConvertTo-Json

# Concurrent using jobs
1..10 | ForEach-Object -Parallel {
    Invoke-RestMethod -Method Post -Uri http://localhost:8080/publish -Body $using:event -ContentType "application/json"
} -ThrottleLimit 10
```

> "10 request concurrent dengan event yang sama. Hasilnya: exactly 1 diproses, 9 marked as duplicate. Tidak ada race condition"

#### 5.4 Jelaskan Mekanisme
> "Ini dimungkinkan oleh unique constraint di PostgreSQL. Saat 2 transaction mencoba insert event yang sama secara bersamaan, hanya 1 yang berhasil, yang lain mendapat conflict dan diabaikan. Ini adalah pattern 'INSERT ON CONFLICT DO NOTHING' yang idempotent."

---

### Section 6: Demo Persistence / Crash Recovery (15:00 - 18:00) ⏱️ 3 menit

**Yang diucapkan:**
> "Sekarang kita akan membuktikan bahwa data persist meski container dihapus"

**Langkah-langkah:**

#### 6.1 Catat Stats Saat Ini
```powershell
curl http://localhost:8080/stats
```

> "Catat: received = X, unique_processed = Y"

#### 6.2 Stop Semua Container (TANPA -v)
```powershell
# Di terminal docker compose
# Tekan Ctrl+C untuk stop
# Atau di terminal lain:
docker compose down
```

> "Container sudah di-stop dan dihapus, TAPI volume masih ada"

#### 6.3 Tunjukkan Volume Masih Ada
```powershell
docker volume ls | Select-String "uas"
```

> "Volume pg_data dan broker_data masih ada"

#### 6.4 Start Ulang
```powershell
docker compose up -d
```

> "Starting ulang semua service..."

#### 6.5 Cek Stats Setelah Restart
```powershell
# Tunggu healthy
Start-Sleep -Seconds 10
curl http://localhost:8080/stats
```

> "Data masih ada! received = X, unique_processed = Y. Sama seperti sebelum restart"

#### 6.6 Test Dedup Masih Bekerja
```powershell
# Kirim event yang sama seperti sebelumnya
$event = @{
    topic = "demo-logs"
    event_id = "evt-demo-001"
    timestamp = (Get-Date).ToUniversalTime().ToString("o")
    source = "demo-service"
    payload = @{ message = "After restart" }
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://localhost:8080/publish -Body $event -ContentType "application/json"
```

> "Masih detected as duplicate! Ini membuktikan dedup state persist di database"

---

### Section 7: Demo Observability (18:00 - 20:00) ⏱️ 2 menit

**Yang diucapkan:**
> "Sistem ini dilengkapi dengan observability: logging dan metrics"

**Langkah-langkah:**

#### 7.1 Health Check
```powershell
curl http://localhost:8080/health
```

> "Health endpoint menunjukkan status database dan broker, serta uptime"

#### 7.2 Stats Endpoint
```powershell
curl http://localhost:8080/stats
```

> "Stats endpoint menyediakan metrics: received, unique_processed, duplicate_dropped, topics, uptime, workers_active, dan queue_size"

#### 7.3 Tunjukkan Logs
```powershell
docker compose logs aggregator --tail 50
```

> "Logs menunjukkan setiap operasi: event processed, duplicate detected, dll. Ini memudahkan debugging dan audit"

#### 7.4 Tunjukkan Topic Counts
```powershell
curl http://localhost:8080/stats | ConvertFrom-Json | Select-Object -ExpandProperty topic_counts
```

> "Kita juga bisa melihat distribusi event per topic"

---

### Section 8: Keamanan Jaringan (20:00 - 22:00) ⏱️ 2 menit

**Yang diucapkan:**
> "Sistem ini berjalan dalam jaringan Docker internal tanpa akses ke layanan eksternal"

**Langkah-langkah:**

#### 8.1 Tunjukkan Network Config di docker-compose.yml
```yaml
networks:
  aggregator_network:
    driver: bridge
```

> "Semua service berkomunikasi dalam network internal"

#### 8.2 Tunjukkan Hanya Port 8080 yang Exposed
```powershell
docker compose ps
```

> "Perhatikan hanya aggregator yang expose port 8080. Redis dan PostgreSQL tidak accessible dari luar"

#### 8.3 Test Internal Communication
```powershell
# Coba akses Redis langsung - seharusnya tidak bisa dari host
# Test-NetConnection -ComputerName localhost -Port 6379
```

> "Redis dan PostgreSQL hanya accessible dari dalam Docker network, tidak dari host machine. Ini untuk keamanan"

---

### Section 9: Closing & Kesimpulan (22:00 - 23:00) ⏱️ 1 menit

**Yang diucapkan:**
> "Sebagai kesimpulan, sistem Pub-Sub Log Aggregator ini berhasil mengimplementasikan:
> 
> 1. **Idempotency** - Event yang sama tidak diproses ulang
> 2. **Deduplication** - Duplikat terdeteksi menggunakan unique constraint
> 3. **Transaction Safety** - Menggunakan READ COMMITTED dengan ON CONFLICT pattern
> 4. **Concurrency** - Multi-worker tanpa race condition
> 5. **Persistence** - Data aman meski container restart
> 6. **Observability** - Logging dan metrics via API
> 
> Sistem telah diuji dengan 20 test cases dan K6 load testing.
> 
> Terima kasih atas perhatiannya. Wassalamualaikum warahmatullahi wabarakatuh."

---

## 🎯 Tips Recording

### Do's ✅
- Bicara dengan jelas dan tidak terlalu cepat
- Pause sebentar saat menunjukkan output penting
- Zoom in pada bagian code yang penting
- Jelaskan MENGAPA, bukan hanya APA

### Don'ts ❌
- Jangan terlalu cepat berpindah section
- Jangan skip error (jika ada, jelaskan dan fix)
- Jangan lupa pause untuk menunjukkan hasil

### Technical Tips 💡
- Gunakan font size besar di terminal (min 14pt)
- Gunakan dark theme untuk visibility
- Record di resolusi 1080p
- Test audio sebelum recording penuh

---

## 📦 Commands Quick Reference

```powershell
# Setup
docker compose down -v
docker compose up --build

# Health & Stats
curl http://localhost:8080/health
curl http://localhost:8080/stats

# Publish Event
$event = @{topic="test";event_id="evt-$(New-Guid)";timestamp=(Get-Date).ToUniversalTime().ToString("o");source="demo";payload=@{}} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8080/publish -Body $event -ContentType "application/json"

# Get Events
curl "http://localhost:8080/events?topic=test"

# Run Publisher
docker compose --profile publisher run -e EVENT_COUNT=1000 -e DUPLICATE_RATE=0.3 publisher

# Restart Test
docker compose down
docker compose up -d

# Logs
docker compose logs aggregator --tail 50

# Cleanup (with volumes)
docker compose down -v
```

---

## ✅ Final Checklist Setelah Recording

- [ ] Video durasi ≤ 25 menit
- [ ] Semua section tercakup
- [ ] Audio jelas terdengar
- [ ] Semua demo berhasil (tidak ada error)
- [ ] Upload ke YouTube (Unlisted/Public)
- [ ] Update link di README.md

---

**Good luck dengan recording! 🎬**
