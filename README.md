# Financial Life Copilot

Financial Life Copilot is a secure, production-ready multi-agent financial planning platform designed to act as an intelligent fiduciary wealth advisor. The system leverages **Google Agent Development Kit (ADK)**, **Gemini 2.5**, and **Model Context Protocol (MCP)** to ingest documents, perform isolated financial simulations, and construct audit-compliant action roadmaps.

---

## 📂 Repository Structure

```
financial-life-copilot/
├── backend/                      # Python FastAPI / Google ADK Microservice
│   ├── app/                      # Main API & Agent application code
│   │   ├── agent.py              # Root Coordinator & Multi-Agent configurations
│   │   ├── schemas.py            # Shared Pydantic data schemas
│   │   └── fast_api_app.py      # FastAPI entry point
│   ├── deployment/               # Terraform & build targets
│   ├── tests/                    # Unit & evaluation testing suites
│   ├── Dockerfile                # Backend production build target
│   └── pyproject.toml            # uv python package dependencies
│
├── frontend/                     # Next.js / TypeScript App Router Web Portal
│   ├── src/app/
│   │   ├── page.tsx              # Interactive Copilot User Interface
│   │   ├── layout.tsx            # Global layout configuration with SEO metadata
│   │   └── globals.css           # Premium custom Vanilla CSS Design System
│   ├── Dockerfile                # Frontend production build target
│   └── package.json              # Frontend node dependencies
│
├── docker-compose.yml            # Local dev orchestration profile
└── .env.example                  # Template environment variables
```

---

## 🛠️ Prerequisites

Before launching the application, ensure the following are installed:
1. **Docker & Docker Compose**
2. **Node.js v20+**
3. **Python 3.11+** with the **uv** package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
4. **Google Cloud SDK (gcloud CLI)**

---

## 🚀 Getting Started

### 1. Setup Environment
Clone the template env file:
```bash
cp .env.example .env
```
Open `.env` and fill in your details (like `GOOGLE_CLOUD_PROJECT`).

### 2. Run with Docker Compose (Recommended)
This will spin up both the Next.js frontend (on port 3000) and the FastAPI backend (on port 8000) concurrently:
```bash
docker-compose up --build
```
* Access the Web portal at [http://localhost:3000](http://localhost:3000)
* Access the API specification at [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🐍 Backend Local Development

To run the backend python service directly on your machine:
```bash
cd backend

# Install dependencies and sync environment
uv sync

# Launch the ADK local playground for interactive model conversation
agents-cli playground

# Or start the local FastAPI web server
uv run python -m uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000 --reload
```

---

## 💻 Frontend Local Development

To run the Next.js frontend service directly on your machine:
```bash
cd frontend

# Install package dependencies
npm install

# Run the development server
npm run dev
```

---

## ⚖️ Safety & Compliance Boundaries
1. **PII Masking**: The platform runs user queries through a custom `DataLossPreventionPlugin` calling Google Cloud DLP to redact sensitive indicators (SSNs, Account numbers).
2. **Execution Sandbox**: Complex simulations (e.g., Monte Carlo) are routed by the **Retirement Agent** to a sandboxed Vertex AI python execution environment (`VertexAiCodeExecutor`).
3. **Transaction Approvals**: Financial actions that alter state or mock brokerage APIs require explicit user verification through ADK's `require_confirmation` gate.
