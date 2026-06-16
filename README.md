# Fusion Orchestrator

Fusion Orchestrator is an intelligent LLM gateway that uses a **Council of Experts** pattern to generate high-quality, synthesized responses. It concurrently queries multiple AI models (Gemini, OpenAI, DeepSeek) and employs a **Judge** model to fuse their outputs into a single, coherent final answer.

## Key Features

- **Multi‑Model Synthesis** – Reduces hallucinations and improves reasoning by combining outputs from different providers.
- **Council Tiers**:
  - **Normal** – Balanced performance using standard models (`gemini-3.1-flash-lite`, `gpt-5-nano`, `deepseek-v4-flash`).
  - **Advanced** – Higher-tier models with the DeepSeek Pro judge using thinking capabilities enabled.
- **OpenAI‑Compatible API** – Endpoints that work with tools like Open WebUI, LiteLLM, and custom clients.
- **Built‑in Web UI** – A simple browser interface at `/ui` for testing and interaction.
- **Streaming Support** – Both normal and advanced councils provide streaming responses.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed on your machine.
- API keys for:
  - **DeepSeek** – `DEEPSEEK_API_KEY`
  - **OpenAI** – `OPENAI_API_KEY`
  - **Gemini** – `GEMINI_API_KEY`

## Deployment

### 1. Clone the repository

```bash
git clone https://github.com/Davidbkr03/Orchestrator
cd Orchestrator
```

### 2. Configure environment variables

Copy the example file and add your API keys:

```bash
cp .env.example .env
```

Edit the `.env` file with your keys:

```env
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_API_KEY=your_openai_key
GEMINI_API_KEY=your_gemini_key
```

### 3. Build and run with Docker

```bash
docker build -t fusion-orchestrator .
docker run -d -p 8000:8000 --env-file .env fusion-orchestrator
```

The API will be available at `http://localhost:8000`. The Web UI can be accessed at `http://localhost:8000/ui`.

### (Alternative) Run without Docker

If you prefer to run directly with Python:

```bash
pip install -r requirements.txt
uvicorn orchestrator:app --host 0.0.0.0 --port 8000
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Redirects to the Web UI |
| `POST /v1/normal/chat/completions` | OpenAI‑compatible completion using the Normal Council |
| `POST /v1/advanced/chat/completions` | OpenAI‑compatible completion using the Advanced Council |
| `GET /api/info` | Returns current council configuration and server info |
| `GET /health` | Simple health check |

### Example usage (with curl)

```bash
curl -X POST http://localhost:8000/v1/normal/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "What is the capital of France?"}
    ],
    "max_tokens": 512,
    "temperature": 0.7
  }'
```

## Project Structure