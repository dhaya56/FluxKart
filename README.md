# FluxKart — Distributed Flash Sale Engine

[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791?logo=postgresql)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis)](https://redis.io/)
[![RabbitMQ](https://img.shields.io/badge/RabbitMQ-3.13-FF6600?logo=rabbitmq)](https://www.rabbitmq.com/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-HPA-326CE5?logo=kubernetes)](https://kubernetes.io/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)](https://www.docker.com/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Tracing-425CC7?logo=opentelemetry)](https://opentelemetry.io/)

Production-grade distributed flash sale engine that solves thundering herd traffic, inventory oversell, and queue fairness problems at scale — the same engineering challenges faced by Amazon Great Indian Festival and Flipkart Big Billion Days. Built with FastAPI, Redis Lua atomic scripts, RabbitMQ with Outbox pattern for guaranteed delivery, PostgreSQL with PgBouncer connection pooling, and a React frontend with a BookMyShow-style virtual waiting room. Full observability through Prometheus, Grafana, and OpenTelemetry distributed tracing with Jaeger. Deployed on Kubernetes with HorizontalPodAutoscaler for automatic pod scaling under load.

---

## Table of Contents
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Installation & Setup](#installation--setup)
- [Running Load Tests](#running-load-tests)
- [Observability](#observability)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Database Migrations](#database-migrations)
- [Environment Variables](#environment-variables)

---

## Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │                   Clients                    │
                        └─────────────────┬───────────────────────────┘
                                          │
                                          ▼
                        ┌─────────────────────────────────────────────┐
                        │              Nginx (Load Balancer)           │
                        │           least-conn, rate limiting          │
                        └──────────────┬──────────────┬───────────────┘
                                       │              │
                          ┌────────────▼──┐      ┌───▼────────────┐
                          │   FastAPI 1   │      │   FastAPI 2    │
                          │  (API Server) │      │  (API Server)  │
                          └──────┬────────┘      └───────┬────────┘
                                 │                       │
               ┌─────────────────┼───────────────────────┤
               │                 │                       │
               ▼                 ▼                       ▼
     ┌──────────────┐   ┌─────────────────┐   ┌──────────────────┐
     │  Redis 7     │   │  PgBouncer      │   │   RabbitMQ       │
     │  Lua Scripts │   │  → PostgreSQL   │   │   + Dead Letter  │
     │  Inventory   │   │  10K→90 conns   │   │   + Outbox       │
     └──────────────┘   └─────────────────┘   └────────┬─────────┘
                                                        │
                                          ┌─────────────▼──────────┐
                                          │   Consumer Worker       │
                                          │   Order Processing      │
                                          │   Expiry Worker         │
                                          │   Outbox Worker         │
                                          │   Reconciliation Worker │
                                          └────────────────────────┘

     ┌──────────────────────────────────────────────────────────────┐
     │                      Observability                            │
     │          Prometheus + Grafana + OpenTelemetry + Jaeger        │
     └──────────────────────────────────────────────────────────────┘
```

---

## Key Features

### Inventory Management
- **Atomic inventory reservation** via Redis Lua scripts — prevents oversell under any concurrent load
- **Redis ↔ PostgreSQL reconciliation worker** — detects and auto-corrects inventory drift
- **Inventory expiry worker** — bulk processes expired reservations, releases inventory back to pool

### Queue & Admission
- **Virtual waiting room** — SSE-based real-time queue (BookMyShow/IPL style)
- **Staggered admission worker** — admits users in controlled FIFO batches at 500 users/sec
- **Heartbeat mechanism** — removes ghost users from queue, prevents inflated wait times

### Reliability
- **Outbox pattern** — reservation and outbox event written in a single atomic transaction, guaranteeing zero message loss even if RabbitMQ is temporarily unavailable
- **Circuit breaker** — auto-opens on RabbitMQ failures, closes when service recovers
- **Dead letter queue** — failed messages routed for inspection and replay
- **Payment idempotency** — prevents double charges on retries

### Behavioral Scoring
- **Trust scoring system** — calculates user score based on order history, abandonment rate, and account age
- **Dynamic TTL** — trusted users get longer reservation windows (up to 15 min), suspicious users get shorter windows (3 min)
- **Legitimate abandonment recovery** — grace period reinstates reservations for trusted users

### Observability
- **Prometheus + Grafana** — metrics dashboards for request rates, latency, inventory levels
- **OpenTelemetry + Jaeger** — distributed traces spanning API → Redis → PostgreSQL → RabbitMQ → Consumer
- **Structured logging** — JSON-ready via structlog with correlation IDs per request

### Infrastructure
- **PgBouncer** — multiplexes 10,000 app connections into 90 PostgreSQL connections
- **Kubernetes manifests** — full K8s deployment with HPA (2→10 pods, auto-scaling at 60% CPU)
- **Two-layer rate limiting** — Nginx (IP-based) + FastAPI dependency (per-user sliding window Lua)

---

## Tech Stack

| Layer | Technology |
|:---|:---|
| Backend | Python 3.12, FastAPI, asyncpg, uvloop |
| Frontend | React 18, Vite |
| Database | PostgreSQL 17 |
| Cache | Redis 7 |
| Message Queue | RabbitMQ 3.13 |
| Connection Pool | PgBouncer |
| Load Balancer | Nginx |
| Observability | Prometheus, Grafana, OpenTelemetry, Jaeger |
| Orchestration | Docker Compose (dev), Kubernetes with HPA (prod) |
| Load Testing | k6 |

---

## Project Structure

```text
FluxKart/
├── backend/
│   ├── app/
│   │   ├── consumers/          # RabbitMQ message consumers
│   │   ├── db/queries/         # Raw SQL query functions
│   │   ├── middleware/         # Rate limiter, correlation ID
│   │   ├── models/             # Pydantic schemas
│   │   ├── routers/            # FastAPI route handlers
│   │   ├── services/           # Business logic
│   │   ├── utils/              # Circuit breaker, metrics, security
│   │   ├── workers/            # Background workers
│   │   ├── config.py           # Settings via pydantic-settings
│   │   ├── dependencies.py     # FastAPI dependency injection
│   │   ├── main.py             # FastAPI app entry point
│   │   └── telemetry.py        # OpenTelemetry setup
│   ├── alembic/                # Database migrations
│   ├── consumers/              # Worker process entry point
│   ├── k8s/                    # Kubernetes manifests + HPA
│   ├── nginx/                  # Nginx config
│   ├── scripts/                # Seed data, test users, load test helpers
│   ├── tests/                  # Test suite
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── prometheus.yml
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── api/                # API client
    │   ├── components/         # Reusable UI components
    │   ├── context/            # Auth context
    │   ├── hooks/              # Custom hooks
    │   ├── pages/              # Page components
    │   └── styles/             # Global CSS
    ├── index.html
    ├── package.json
    └── vite.config.js
```

---

## Installation & Setup

### Prerequisites
- Python 3.12
- Node.js 18+
- Docker Desktop
- PostgreSQL 17 (running locally)
- conda (recommended) or virtualenv

### 1. Clone the repository
```bash
git clone https://github.com/dhaya56/FluxKart.git
cd FluxKart
```

### 2. Backend setup
```bash
cd backend

# Create conda environment
conda create -n FluxKart python=3.12
conda activate FluxKart

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, JWT_SECRET_KEY, and other values
```

### 3. Database setup
```bash
# Create the database in PostgreSQL
psql -U postgres -c "CREATE DATABASE fluxkart_db;"

# Run all migrations
alembic upgrade head

# Seed initial data (creates admin account + sample sale)
python scripts/seed_data.py
```

### 4. Start all services
```bash
docker compose up -d
```

Wait 60 seconds for all services to initialize, then verify:
```bash
curl http://localhost/health
```

Expected response:
```json
{"status": "healthy", "services": {"postgresql": "healthy", "redis": "healthy", "rabbitmq": "healthy"}}
```

### 5. Frontend setup
```bash
cd ../frontend
npm install
npm run dev
```

| Service | URL |
|:---|:---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost |

### 6. Admin account
```
Email:    dhaya@fluxkart.com
Password: 123
```

---

## Running Load Tests

```bash
cd backend

# Step 1 — Create 5000 test users (one time only)
python scripts/create_test_users.py

# Step 2 — Generate JWT tokens (re-run if expired after 30 min)
python scripts/generate_tokens.py

# Step 3 — Reset sale inventory before each test run
python scripts/reset_sales.py

# Sustained load test (ramps to 2000 VUs)
docker compose --profile loadtest run --rm \
  -e SALE_ID=<your-sale-id> \
  k6 run /scripts/load_test.js

# Thundering herd test (5000 VU spike at T=0)
docker compose --profile loadtest run --rm \
  -e SALE_ID=<your-sale-id> \
  -e MODE=herd \
  k6 run /scripts/load_test.js
```

> Get the SALE_ID from the admin panel at `http://localhost/admin` or from the database.

---

## Observability

| Service | URL | Credentials |
|:---|:---|:---|
| Grafana | http://localhost:3000 | admin / (set in .env) |
| Prometheus | http://localhost:9090 | — |
| Jaeger (Tracing) | http://localhost:16686 | — |
| RabbitMQ Management | http://localhost:15672 | fluxkart / fluxkart123 |

In Jaeger, select service `fluxkart-api` → operation `POST /reservations` to see full distributed traces spanning API, Redis, PostgreSQL, RabbitMQ, and the consumer worker.

---

## Kubernetes Deployment

### Prerequisites
- minikube
- kubectl

```bash
# Start minikube
minikube start --driver=docker --memory=4096 --cpus=2

# Deploy all services
cd backend
k8s\deploy.bat

# Verify all pods are running
kubectl get pods -n fluxkart

# Check HPA status
kubectl get hpa -n fluxkart

# Access the service
minikube service nginx-service -n fluxkart
```

The HPA automatically scales API pods from 2 to 10 when CPU utilization exceeds 60%.

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "your_migration_description"

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

| Variable | Description |
|:---|:---|
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `JWT_SECRET_KEY` | Secret key for JWT signing — use a long random string in production |
| `RABBITMQ_PASSWORD` | RabbitMQ password |
| `GF_SECURITY_ADMIN_PASSWORD` | Grafana admin password |
| `JAEGER_OTLP_ENDPOINT` | Jaeger collector endpoint (default: `http://jaeger:4317`) |
| `APP_ENV` | `development` or `production` — disables Swagger UI in production |
| `RESERVATION_TTL_SECONDS` | How long a reservation is held before inventory is released (default: 600) |

---