# Kolberg — Multi-Tenant Financial Management Platform

Kolberg is a multi-tenant SaaS platform for financial operations management: payment requests, budgets, payroll, investments, P&L/cashflow reporting, and Telegram-first mobile approvals.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Business Modules](#business-modules)
- [Local Development](#local-development)
- [Development Workflow](#development-workflow)
- [Make Commands](#make-commands)
- [CI/CD Pipeline](#cicd-pipeline)
- [Deployment](#deployment)
- [Environment Variables](#environment-variables)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                        Traefik                          │
│              (reverse proxy + TLS termination)          │
└───────────┬────────────────┬──────────────┬─────────────┘
            │                │              │
     ┌──────┴──────┐  ┌──────┴──────┐  ┌───┴────────┐
     │ frontend_v2 │  │ backend_v2  │  │ tg-gateway │
     │  React SPA  │  │  Django API │  │  FastAPI   │
     │   (nginx)   │  │ (gunicorn)  │  │ (uvicorn)  │
     └─────────────┘  └──────┬──────┘  └───┬────────┘
                             │              │
                      ┌──────┴──────────────┴──────┐
                      │      PostgreSQL 17          │
                      │       (pgvector)            │
                      └────────────────────────────┘
                             │
                      ┌──────┴──────┐
                      │     n8n     │
                      │ (workflows) │
                      └─────────────┘
```

**Multi-tenancy** is handled by subdomain routing — each tenant gets its own subdomain (e.g. `company.kolberg.uz`). The backend resolves the tenant from the `Host` header on every request.

**Integration points** (only three, by design):
- `frontend_v2` — React SPA used by web users
- `n8n` — workflow automation for notifications, approvals, and data pipelines
- Telegram WebApp — mobile-first UI embedded inside Telegram

---

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Backend language | Python | 3.12 |
| Backend framework | Django + DRF | 5.0+ |
| Frontend language | TypeScript | 6.0 |
| Frontend framework | React | 19 |
| UI library | Ant Design | 5.29 |
| Build tool | Vite | 8.0 |
| Database | PostgreSQL + pgvector | 17 |
| Gateway | FastAPI | 0.115 |
| Reverse proxy | Traefik | latest |
| Workflow engine | n8n | latest |
| Container runtime | Docker Compose | — |
| Frontend tests | Vitest | 4.1 |
| Authentication | JWT (SimpleJWT) | — |

---

## Project Structure

```
kolberg/
├── backend_v2/              # Django REST API
│   ├── apps/
│   │   ├── accounts/        # User auth, OTP, custom user model
│   │   ├── tenants/         # Multi-tenancy middleware and settings
│   │   ├── mcp_server/      # Claude MCP server integration
│   │   └── modules/         # 17 business domain modules (see below)
│   ├── config/              # Django settings, root URLs, WSGI/ASGI
│   └── requirements.txt
│
├── frontend_v2/             # React SPA + Telegram WebApp
│   └── src/
│       ├── routes/App.tsx   # React Router configuration
│       ├── ui/              # Pages and components by domain
│       └── lib/             # API transport layer and utilities
│
├── tg-gateway/              # FastAPI service for Telegram bot integration
│
├── n8n_dev/                 # n8n workflow development files
│
├── docs/                    # Architecture and integration documentation
│
├── .github/workflows/       # GitHub Actions CI pipelines
│
├── docker-compose.yml       # Production services
├── docker-compose.local.yml # Local development services
├── Makefile                 # All developer commands
└── deploy.sh                # Automated deployment script
```

---

## Business Modules

All 17 modules live under `backend_v2/apps/modules/`. Each module follows the same structure: `models.py`, `serializers.py`, `views.py`, `urls.py`, `admin.py`, optionally `services.py`, and `migrations/`.

| Module | Description |
|---|---|
| `requests` | Core payment request workflow — creation, approval chains, payment confirmation |
| `vendors` | Vendor / contractor directory |
| `cash_expenses` | Cash register transaction feed |
| `bank_expenses` | Bank transfer transaction feed |
| `corporate_card` | Corporate card expense tracking |
| `payroll` | Employee salary management and documents |
| `wallets` | Cash registers, bank accounts, and card accounts |
| `budgets` | Budget allocation, limits, and spend tracking |
| `reports` | P&L and cashflow report generation |
| `investments` | Investor capital allocation, returns, approval flows |
| `clients_debt` | Client debt tracking |
| `contracts` | Contract management |
| `feedback` | User feedback collection |
| `notes` | Internal notes |
| `telegram_approvals` | Telegram approval card bridge |
| `n8n_integration` | n8n webhook integration (single canonical module) |

> **Source of truth for expenses:** All expenses flow through `requests`. Raw cash/bank/card transaction feeds are reconciliation data only — never query them as the primary expense source.

---

## Local Development

### Prerequisites

- Docker Desktop
- `make`
- Access to `.env` file (copy from `.env.example` and fill in values)

### Start local stack

```bash
cp .env.example .env
# fill in required values in .env

make local-up      # starts db, backend_v2, frontend_v2, tg-gateway
make local-logs    # tail all service logs
```

Services will be available at:

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8001 |
| Telegram Gateway | http://localhost:8080 |
| PostgreSQL | localhost:5433 |

### Stop local stack

```bash
make local-down
```

---

## Development Workflow

```
git checkout main && git pull
git checkout -b dev/<feature-name>   # or fix/<bug-name>

# ... make changes and commit ...

make push            # validates all changes are committed, pushes branch
# GitHub Actions runs Backend Tests + Vitest automatically

# open a Pull Request into main
# wait for CI green + approval
# merge PR

git checkout main && git pull
make deploy          # deploy to production
```

**Branch naming:**
- `dev/<name>` — new feature or module
- `fix/<name>` — bugfix or patch

**Rules:**
- No direct commits or pushes to `main` — only via Pull Request
- Every bugfix must include or update at least one test covering the fixed behaviour
- Local `pytest` / `npm test` are not used — CI runs on push via GitHub Actions

### Parallel development (worktree slots)

Three worktree slots are reserved for parallel agent work:

```bash
git worktree list          # check which slots are free (_slot/N = free)

cd .worktrees/slot-1
git pull origin main
git checkout -b dev/my-feature
# work, commit, push inside the slot

# after PR merge, free the slot:
git -C .worktrees/slot-1 checkout _slot/1
git -C .worktrees/slot-1 branch -d dev/my-feature
```

Do not create new worktrees manually — use the existing slots only.

---

## Make Commands

| Command | Description |
|---|---|
| `make push` | Validate everything is committed, push branch to GitHub |
| `make deploy` | Deploy `main` to production (runs post-deploy tests) |
| `make deploy DEPLOY_AT=23:00` | Schedule deployment at a specific time |
| `make deploy DEPLOY_RUN_TESTS=0` | Deploy without post-deploy tests |
| `make deploy DEPLOY_TEST_PATH=apps.modules.requests.tests` | Deploy with targeted tests |
| `make makemigrations` | Generate migrations on the server, download locally |
| `make showmigrations` | Show migration status on the server |
| `make rollback` | Revert to the previous Docker image (~10 second recovery) |
| `make backup-db` | Create a gzipped database backup |
| `make local-up` | Start the local Docker Compose stack |
| `make local-down` | Stop the local stack |
| `make local-logs` | Tail logs from the local stack |

---

## CI/CD Pipeline

Two GitHub Actions workflows run on every PR to `main` and on every push to `dev/**` or `fix/**`:

### Backend Tests

File: `.github/workflows/backend-tests.yml`

- Environment: Ubuntu, Python 3.12, PostgreSQL 16
- Command: `python manage.py test apps --keepdb -v 2`
- Timeout: 20 minutes

### Frontend Tests (Vitest)

File: `.github/workflows/frontend-tests.yml`

- Environment: Ubuntu, Node 24
- Commands: `npm ci && npm run test -- --run`
- Timeout: 15 minutes

Both checks must pass before merging into `main`.

---

## Deployment

Deployment always runs from `main` only.

```bash
git checkout main && git pull
make deploy
```

The `deploy.sh` script on the server:
1. Pulls latest `main` from GitHub
2. Builds Docker images for `backend_v2`, `frontend_v2`, and `tg-gateway`
3. Runs `python manage.py migrate`
4. Restarts services with `docker compose up -d --no-deps`
5. Runs post-deploy test suite against the live container

**Emergency rollback** (reverts to previous Docker image in ~10 seconds):

```bash
make rollback
```

### Production services

| Service | Role |
|---|---|
| `traefik` | Reverse proxy, TLS termination, host-based routing |
| `backend_v2` | Django REST API (gunicorn + uvicorn) |
| `frontend_v2` | React SPA served by nginx |
| `tg-gateway` | Telegram bot integration (FastAPI) |
| `db` | PostgreSQL 17 with pgvector extension |
| `n8n` | Workflow automation platform |
| `browserless` | Headless Chrome for PDF/screenshot generation |
| `db_backup` | Automated scheduled database backups |
| `gdrive_backup_sync` | Syncs backups to Google Drive |
| `portainer` | Docker management UI |
| `staticfiles` | Static assets server |

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Description |
|---|---|
| `TRAEFIK_FRONTEND_HOST_RULE` | Domain rule for the frontend service |
| `TRAEFIK_BACKEND_V2_HOST_RULE` | Domain rule for the backend API |
| `TRAEFIK_BACKEND_V2_API_PATH_RULE` | Path rule for API routing |
| `TRAEFIK_BACKEND_V2_N8N_RULE` | Routing rule for n8n |
| `MCP_HOST` | Hostname for the Claude MCP server |
| `MCP_BASE_URL` | Base URL for Claude MCP server endpoints |

Additional secrets (database passwords, JWT secret, Telegram token, etc.) are configured directly in the server environment and are not committed to the repository.

---

## Restrictions

The following are **always forbidden** in this codebase:

- Direct SSH commands bypassing the Makefile
- Running `python manage.py makemigrations` locally
- Code that deletes data from the database (tables, rows, files, buckets, volumes)
- Adding new integration points without an explicit requirement (only three integrations exist by design)
- Committing directly to `main` or force-pushing to `main`
