# Clairify <-> OpenClaw Chat - Tailscale POC

A proof of concept demonstrating how Clairify app users can chat
directly with an OpenClaw instance over a secure Tailscale network,
with the backend only handling authentication.

---

## Prerequisites

- Docker
- [Python 3.11+](https://www.python.org/downloads/)
- Internet connection for first-time setup

---

## Step 1: Install Tailscale

1. Download from [https://tailscale.com/download/windows](https://tailscale.com/download/windows)
2. Install and open it
3. Click **Log in** using Google, Microsoft, or GitHub
4. Verify it is working:
   - `tailscale status`
5. You should see your machine listed with a `100.x.x.x` IP
6. Generate an auth key
7. Go to `https://login.tailscale.com/admin/settings/keys`
8. Click **Generate auth key**

Copy the key. It will start with `tskey-auth-...`

## Step 2: Install Ollama

Ollama runs AI models locally. OpenClaw uses it to generate chat responses.

1. Download from `https://ollama.com/download`
2. Install and open it
3. Pull a model:
   - `ollama pull llama3.2`
   - or `ollama pull tinyllama:latest`
4. Start Ollama:
   - `ollama serve`
5. Verify it is running:
   - `curl http://localhost:11434/api/tags`
6. You should see a JSON response listing your model

## Step 3: Clone and Configure

1. Clone the repo:
   - `git clone <repo-url>`
   - `cd tailscale-chat-demo`

2. Create a root `.env` file using `.env.example` as the template.
   Example values:
   - `TS_AUTHKEY_GATEWAY=tskey-auth-xxxx`
   - `TS_AUTHKEY_OPENCLAW=tskey-auth-yyyy`
   - `BACKEND_PORT=8000`
   - `GATEWAY_PORT=8080`
   - `OPENCLAW_HOSTNAME=openclaw-production`
   - `OPENCLAW_PORT=8001`

3. The root `.env` is used by the backend and gateway stack.

4. Create a .env inside the openclaw floder as well and put the TS_AUTHKEY_OPENCLAW in the .env.

5. This .env is used by the openclaw

## Step 4: Install Python Dependencies

1. Create and activate a virtual environment:
   - `python -m venv venv`
   - `.\venv\Scripts\activate`

2. Install backend requirements if you want to run backend outside Docker: (Optional)
   - `cd backend`
   - `pip install -r requirements.txt`

3. Install client requirements:
   - `cd ..\client`
   - `pip install -r requirements.txt`

4. Install gateway requirements if you want to run gateway outside Docker: (Optional)
   - `cd ..\gateway`
   - `pip install -r requirements.txt`

## Step 5: Start OpenClaw

1. Open a new terminal:
   ```
   cd tailscale-chat-demo\openclaw
   docker compose up --build -d
   ```

2. Verify the OpenClaw stack is running:
   ```
   docker compose ps
   ```

3. Check logs if startup is taking time:
   ```
   docker logs --tail 120 openclaw-production
   docker logs --tail 120 ts-openclaw-isolated
   ```

4. Notes:
   - `openclaw-production` runs Open WebUI
   - `ts-openclaw-isolated` is the Tailscale sidecar that gives OpenClaw its tailnet IP
   - On first startup, OpenClaw can take a little time before it becomes reachable

## Step 6: Update the Root `.env` with the Current OpenClaw IP

1. After the OpenClaw stack joins Tailscale, confirm its current tailnet IP.

2. Update the root `.env` file:
   ```env
   OPENCLAW_IP=<current tailscale ip>
   OPENCLAW_PORT=8001
   ```

3. Notes:
   - The gateway reads `OPENCLAW_IP` from the root `.env`
   - If the OpenClaw Tailscale IP changes, update the root `.env` before starting or restarting the root stack

## Step 7: Start Backend and Gateway

1. Open a new terminal at the repo root:
   ```
   cd tailscale-chat-demo
   docker compose up --build -d
   ```

2. Verify both services are running:
   ```
   docker compose ps
   ```

3. Optional health checks:
   ```
   curl http://localhost:8000/health
   curl http://localhost:8080/health
   ```

4. Notes:
   - `backend` runs on `http://localhost:8000`
   - `gateway` runs on `http://localhost:8080`
   - `gateway` forwards chat requests to OpenClaw over Tailscale

## Step 8: Run the Client

1. Open a new terminal:
   ```
   cd tailscale-chat-demo
   .\venv\Scripts\activate
   cd client
   python main.py
   ```

2. Expected flow:
   - client authenticates with backend
   - backend returns a session token and gateway URL
   - client sends chat requests to gateway
   - gateway forwards them to OpenClaw over Tailscale

You should now see users authenticate with the backend and then chat through the gateway to OpenClaw.

## Optional: Run Backend or Gateway Without Docker

1. Backend:
   ```
   cd tailscale-chat-demo
   .\venv\Scripts\activate
   cd backend
   python -m uvicorn main:app --host 0.0.0.0 --port 8000
   ```

2. Gateway:
   ```
   cd tailscale-chat-demo
   .\venv\Scripts\activate
   cd gateway
   $env:OPENCLAW_IP="<current tailscale ip>"
   $env:OPENCLAW_PORT="8001"
   python -m uvicorn main:app --host 0.0.0.0 --port 8080
   ```

## Terminal Summary

You usually need these running:

- Terminal 1: `ollama serve`
- Terminal 2: `cd openclaw && docker compose up --build -d`
- Terminal 3: `cd tailscale-chat-demo && docker compose up --build -d`
- Terminal 4: `cd client && python main.py`

## Troubleshooting

`Gateway returns 404 Not Found`
- Restart the gateway service or the root docker stack. A stale old process may still be using port `8080`.

`Gateway returns 503 Cannot connect`
- OpenClaw is not reachable yet. Check `docker compose ps` inside `openclaw` and confirm `OPENCLAW_IP` in the root `.env`.

`Gateway returns 401 Not authenticated`
- Make sure the gateway is running the latest code and can sign in to the current OpenClaw instance.

`OpenClaw not reachable`
- Wait for OpenClaw to finish starting. Check `docker logs --tail 120 openclaw-production`.

`OpenClaw container is unhealthy`
- Review the OpenClaw logs. Startup may still be in progress.

`No model found`
- Make sure Ollama is running and that a model such as `tinyllama:latest` or `llama3.2` is available.

`Client says ModuleNotFoundError`
- Activate the virtual environment and install `client/requirements.txt`.

`Docker cannot pull images`
- Check internet connection and make sure Docker Desktop is running.

`TS_AUTHKEY error`
- Make sure the correct `.env` file exists and the auth key is valid.
