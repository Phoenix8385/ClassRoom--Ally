# classroom-ally

[![CI](https://github.com/Phoenix8385/ClassRoom--Ally/actions/workflows/ci.yml/badge.svg)](https://github.com/Phoenix8385/ClassRoom--Ally/actions/workflows/ci.yml)
[![Deploy Frontend](https://github.com/Phoenix8385/ClassRoom--Ally/actions/workflows/deploy-frontend.yml/badge.svg)](https://github.com/Phoenix8385/ClassRoom--Ally/actions/workflows/deploy-frontend.yml)
[![Deploy Backend](https://github.com/Phoenix8385/ClassRoom--Ally/actions/workflows/deploy-backend.yml/badge.svg)](https://github.com/Phoenix8385/ClassRoom--Ally/actions/workflows/deploy-backend.yml)

> Real-time sign-language interpretation and avatar relay for inclusive classrooms.

---

## Architecture

```
  🎤 Microphone / Camera
         │
         ▼
┌─────────────────────┐
│   Next.js Frontend  │  ◄── Teacher & student web UI
│  (apps/web)         │
└────────┬────────────┘
         │  WebSocket / REST
         ▼
┌─────────────────────┐
│   FastAPI  API      │  ◄── Auth, session management, task queue
│  (services/api)     │
└──┬──────────────────┘
   │            │
   ▼            ▼
┌──────┐   ┌─────────┐
│ Redis│   │Postgres │   ◄── Job queue / cache + persistent storage
└──────┘   └─────────┘
   │
   ▼
┌─────────────────────┐
│  AI Pipeline        │
│  ┌───────────────┐  │
│  │ ASR (Whisper) │  │  ◄── Speech → text
│  └──────┬────────┘  │
│         ▼           │
│  ┌───────────────┐  │
│  │  ISL Model    │  │  ◄── Text → Indian Sign Language gloss
│  └──────┬────────┘  │
│         ▼           │
│  ┌───────────────┐  │
│  │Avatar Renderer│  │  ◄── Gloss → animated 3-D avatar
│  └───────────────┘  │
└─────────────────────┘
         │
         ▼
  🧏 Signed Avatar overlay
     streamed to student
```

---

## Tech Stack

| Layer      | Technology                                         |
|------------|----------------------------------------------------|
| Frontend   | Next.js 14, TypeScript, Tailwind CSS, Three.js     |
| Backend    | FastAPI, Python 3.12, Celery, Pydantic v2          |
| AI / ML    | OpenAI Whisper, PyTorch, ONNX Runtime, MediaPipe   |
| Database   | PostgreSQL 16, Redis 7, SQLAlchemy 2, Alembic      |
| Deploy     | Docker, Vercel (web), Railway / Render (API), pnpm |

---

## Team

| Name              | Role                              |
|-------------------|-----------------------------------|
| Aanya Sharma      | Full-Stack Lead & Project Manager |
| Rohan Verma       | AI / ML Engineer (ISL Model)      |
| Priya Nair        | Backend Engineer (API & Queue)    |
| Arjun Mehta       | Frontend Engineer (UI & Avatar)   |
| Sneha Kulkarni    | Data Engineer & QA                |

---

## Quick Start

```bash
# 1. Clone and install all workspace dependencies
git clone https://github.com/your-org/classroom-ally.git && cd classroom-ally
pnpm install

# 2. Copy environment templates and fill in values
cp services/api/.env.example services/api/.env
cp apps/web/.env.example apps/web/.env.local

# 3. Spin up Postgres + Redis + API via Docker
docker compose up -d

# 4. Run database migrations
docker compose exec api alembic upgrade head

# 5. Start the Next.js dev server
pnpm --filter web dev
```

The web app will be available at **http://localhost:3000** and the API at **http://localhost:8000/docs**.

---

## License

MIT © 2024 classroom-ally contributors. See [LICENSE](./LICENSE) for details.
