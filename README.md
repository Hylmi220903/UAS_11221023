# 🚀 Pub-Sub Log Aggregator Terdistribusi

Sistem Pub-Sub log aggregator multi-service dengan **Idempotent Consumer**, **Deduplication**, dan **Transaksi/Kontrol Konkurensi**.

**Nama:** Hylmi Wahyudi  
**NIM:** 11221023  
**Mata Kuliah:** Sistem Paralel dan Terdistribusi - B

---

## 📋 Daftar Isi

- [Deskripsi Sistem](#-deskripsi-sistem)
- [Arsitektur](#-arsitektur)
- [Teknologi](#-teknologi)
- [Instalasi & Menjalankan](#-instalasi--menjalankan)
- [API Endpoints](#-api-endpoints)
- [Fitur Utama](#-fitur-utama)
- [Testing](#-testing)
- [Video Demo](#-video-demo)

---

## 📝 Deskripsi Sistem

Sistem ini adalah **Log Aggregator** berbasis arsitektur **Publish-Subscribe** yang dirancang untuk mengumpulkan dan memproses log dari berbagai sumber secara terdistribusi. Sistem ini menjamin:

1. **Idempotency**: Event yang sama tidak akan diproses ulang
2. **Deduplication**: Duplikat event akan dideteksi dan diabaikan
3. **Transaction Safety**: Operasi database dilakukan secara atomic
4. **Concurrency Control**: Multiple worker dapat memproses secara paralel tanpa race condition

---

## 🏗 Arsitektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Compose Network                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │
│  │              │     │              │     │              │        │
│  │  Publisher   │────▶│    Redis     │◀────│  Aggregator  │        │
│  │  (Simulator) │     │   (Broker)   │     │    (API)     │        │
│  │              │     │              │     │              │        │
│  └──────────────┘     └──────────────┘     └──────┬───────┘        │
│                              │                     │                 │
│                              │                     │                 │
│                              ▼                     ▼                 │
│                       ┌──────────────┐     ┌──────────────┐        │
│                       │   Volume:    │     │  PostgreSQL  │        │
│                       │ broker_data  │     │  (Storage)   │        │
│                       └──────────────┘     └──────┬───────┘        │
│                                                   │                 │
│                                                   ▼                 │
│                                            ┌──────────────┐        │
│                                            │   Volume:    │        │
│                                            │   pg_data    │        │
│                                            └──────────────┘        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Komponen

| Service | Deskripsi | Port |
|---------|-----------|------|
| **aggregator** | API utama untuk publish dan akses event | 8080 |
| **publisher** | Simulator event dengan configurable duplicate rate | - |
| **broker** | Redis sebagai message queue | 6379 (internal) |
| **storage** | PostgreSQL untuk persistent storage | 5432 (internal) |

---

## 🛠 Teknologi

| Komponen | Teknologi |
|----------|-----------|
| Language | Python 3.11 |
| Framework | FastAPI + Uvicorn |
| Database | PostgreSQL 16 |
| Message Broker | Redis 7 |
| Container | Docker + Docker Compose |
| Testing | Pytest + K6 |

---

## 🚀 Instalasi & Menjalankan

### Prerequisites

- Docker dan Docker Compose terinstall
- Port 8080 tersedia

### Quick Start

```bash
# Clone repository
git clone <repository-url>
cd UAS_11221023

# Build dan jalankan semua service
docker compose up --build

# Atau jalankan di background
docker compose up --build -d
```

### Menjalankan Publisher (Event Simulator)

```bash
# Jalankan publisher dengan profile
docker compose --profile publisher up publisher

# Atau dengan konfigurasi custom
docker compose --profile publisher run -e EVENT_COUNT=5000 -e DUPLICATE_RATE=0.4 publisher
```

### Menjalankan Multiple Workers

```bash
# Jalankan additional workers untuk concurrency testing
docker compose --profile workers up -d
```

### Stop Semua Service

```bash
docker compose down

# Dengan menghapus volumes (reset data)
docker compose down -v
```

---

## 📡 API Endpoints

### Health Check

```http
GET /health
```

Response:
```json
{
    "status": "healthy",
    "database": "connected",
    "broker": "connected",
    "uptime_seconds": 3600.5,
    "version": "1.0.0"
}
```

### Publish Single Event

```http
POST /publish
Content-Type: application/json

{
    "topic": "application-logs",
    "event_id": "evt-550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2024-12-04T10:30:00Z",
    "source": "service-a",
    "payload": {
        "level": "INFO",
        "message": "User login successful"
    }
}
```

Response:
```json
{
    "success": true,
    "message": "Event processed successfully",
    "event_id": "evt-550e8400-e29b-41d4-a716-446655440000",
    "is_duplicate": false,
    "received_at": "2024-12-04T10:30:01Z"
}
```

### Publish Batch Events

```http
POST /publish/batch
Content-Type: application/json

{
    "events": [
        {
            "topic": "app-logs",
            "event_id": "evt-1",
            "timestamp": "2024-12-04T10:30:00Z",
            "source": "service-a",
            "payload": {}
        },
        {
            "topic": "app-logs",
            "event_id": "evt-2",
            "timestamp": "2024-12-04T10:30:01Z",
            "source": "service-b",
            "payload": {}
        }
    ]
}
```

Response:
```json
{
    "success": true,
    "total_received": 2,
    "unique_processed": 2,
    "duplicates_dropped": 0,
    "failed": 0
}
```

### Get Events

```http
GET /events?topic=application-logs&limit=100&offset=0
```

Response:
```json
{
    "success": true,
    "topic": "application-logs",
    "count": 2,
    "events": [
        {
            "topic": "application-logs",
            "event_id": "evt-1",
            "timestamp": "2024-12-04T10:30:00Z",
            "source": "service-a",
            "payload": {},
            "received_at": "2024-12-04T10:30:01Z",
            "processed_at": "2024-12-04T10:30:01Z"
        }
    ]
}
```

### Get Statistics

```http
GET /stats
```

Response:
```json
{
    "received": 10000,
    "unique_processed": 7000,
    "duplicate_dropped": 3000,
    "topics": ["app-logs", "security-logs", "system-logs"],
    "topic_counts": {
        "app-logs": 4000,
        "security-logs": 2000,
        "system-logs": 1000
    },
    "uptime_seconds": 3600.5,
    "uptime_formatted": "0d 1h 0m 0s",
    "workers_active": 4,
    "queue_size": 0
}
```

---

## ✨ Fitur Utama

### 1. Idempotency & Deduplication

- **Unique Constraint**: Kombinasi `(topic, event_id)` dijadikan unique constraint
- **Atomic Dedup**: Menggunakan `INSERT ... ON CONFLICT DO NOTHING`
- **Persistent State**: Dedup store disimpan di PostgreSQL dengan volume

### 2. Transaction & Concurrency Control

- **Isolation Level**: READ COMMITTED
- **Atomic Operations**: Setiap insert event dalam satu transaction
- **Concurrent Workers**: Multiple workers dapat memproses paralel
- **No Race Condition**: Unique constraint mencegah double-processing

### 3. Reliability

- **At-least-once Delivery**: Publisher dapat mengirim ulang tanpa masalah
- **Crash Tolerance**: Data persistent via Docker volumes
- **Retry dengan Backoff**: Exponential backoff untuk failed operations

### 4. Observability

- **Logging**: Structured logging untuk setiap operasi
- **Metrics**: Real-time statistics via `/stats` endpoint
- **Health Check**: Liveness/readiness probe via `/health`

---

## 🧪 Testing

### Unit/Integration Tests

```bash
# Install test dependencies
pip install -r tests/requirements.txt

# Jalankan semua tests (pastikan service sudah running)
pytest tests/test_aggregator.py -v

# Jalankan test specific
pytest tests/test_aggregator.py::TestIdempotencyAndDeduplication -v

# Dengan coverage report
pytest tests/test_aggregator.py -v --cov=aggregator
```

### Test Coverage (20 Tests)

| Category | Tests |
|----------|-------|
| Schema Validation | 3 tests |
| Idempotency & Dedup | 4 tests |
| Concurrency & Transactions | 4 tests |
| API Endpoints | 3 tests |
| Persistence | 2 tests |
| Stress & Performance | 2 tests |
| Edge Cases | 2 tests |

### Load Testing dengan K6

```bash
# Install K6: https://k6.io/docs/get-started/installation/

# Run load test
k6 run k6/load_test.js

# Custom configuration
k6 run --vus 100 --duration 5m k6/load_test.js
```

---

## 🎬 Video Demo

**Link YouTube:** (https://youtu.be/sOQY6KkZVFk)

Video demo mencakup:
1. ✅ Arsitektur multi-service dan alasan desain
2. ✅ Build image dan menjalankan Compose
3. ✅ Pengiriman event duplikat dan bukti idempotency
4. ✅ Demonstrasi transaksi/konkurensi (multi-worker)
5. ✅ GET /events dan GET /stats sebelum/sesudah
6. ✅ Crash/recreate container + bukti data persisten
7. ✅ Keamanan jaringan lokal
8. ✅ Observability (logging, metrik)

---

## 📁 Struktur Direktori

```
UAS_11221023/
├── aggregator/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py           # FastAPI application
│   ├── config.py         # Configuration settings
│   ├── models.py         # Pydantic models
│   ├── database.py       # PostgreSQL operations
│   ├── broker.py         # Redis operations
│   └── init.sql          # Database schema
├── publisher/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py           # Event generator
│   └── config.py         # Publisher settings
├── tests/
│   ├── requirements.txt
│   └── test_aggregator.py  # 20 pytest tests
├── k6/
│   └── load_test.js      # K6 load testing script
├── docs/
│   └── buku-utama.pdf    # Reference book
├── docker-compose.yml
├── README.md
├── report.md             # Laporan lengkap
└── CROSSCHECK.md         # Requirements checklist
```

---

## 📚 Referensi

- Tanenbaum, A. S., & Van Steen, M. (2017). *Distributed Systems: Principles and Paradigms* (3rd ed.). Pearson.
- FastAPI Documentation: https://fastapi.tiangolo.com/
- PostgreSQL Documentation: https://www.postgresql.org/docs/
- Redis Documentation: https://redis.io/docs/
- K6 Documentation: https://k6.io/docs/

---

## 📄 Lisensi

Proyek ini dibuat untuk keperluan akademis pada mata kuliah Sistem Paralel dan Terdistribusi.

---

**© 2024 - Sistem Paralel dan Terdistribusi**
