# Clairify ↔ OpenClaw Chat — Tailscale POC

A proof of concept demonstrating how Clairify app users can chat
directly with an OpenClaw instance over a secure Tailscale network,
with the backend only handling authentication.

---

## Prerequisites

- Docker
- [Python 3.11+](https://www.python.org/downloads/)
- Internet connection (for first-time setup)

---

## Step 1: Install Tailscale

1. Download from [https://tailscale.com/download/windows](https://tailscale.com/download/windows)
2. Install and open it
3. Click **Log in** (use Google / Microsoft / GitHub)
4. After login, verify it's working:
    - tailscale status
5. You should see your machine listed with a 100.x.x.x IP.
6. Generate an Auth Key
7. Go to https://login.tailscale.com/admin/settings/keys
8. Click Generate auth key

Copy the key (starts with tskey-auth-...)

### Step 2: Install Ollama
Ollama runs AI models locally. OpenClaw needs it to generate chat responses.

1. Download from https://ollama.com/download
2. Install and open it
3. Pull a model:
   - ollama pull llama3.2

4. Start Ollama:
   - ollama serve
5. Verify it's running:
   - curl http://localhost:11434/api/tags
6. You should see a JSON response listing your model.


### Step 3: Clone & Configure

1. - git clone <repo-url>
   - cd tailscale-chat-demo
2. Create a .env file and putin the auth key as 
   - TS_AUTHKEY=tskey-auth-xxxxx-xxx


### Step 4: Install Python Dependencies
1. Activate the virtual env as:
  - python -m venv venv
  - .\venv\Scripts\activate

2. Install backend requirements 
  - cd backend
  - pip install -r requirements.txt

3. Install client requirements (acts as frontend for this demo)
  - cd ..\client
  - pip install -r requirements.txt

### Step 5: Start OpenClaw (Docker)
1. Run docker compose as:
   - docker-compose up --build
2. Verify OpenClaw is Reachable via Tailscale
   - tailscale status
        - Should show: 100.x.x.x  openclaw-remote  linux  active
    - Test connectivity
        - tailscale ping openclaw-remote
             - Should show: pong from openclaw-remote (100.x.x.x) via ... in Xms
    - Test HTTP
        - curl http://<TAILSCALE_IP>:8001/
        - Should return HTML (200 OK)

### Step 6: Start Backend
1. Open a new terminal:
   - ``` 
        cd tailscale-chat-demo
        .\venv\Scripts\activate
        cd backend
        python main.py
     ```


### Step 7: Run Client
1. Open a new terminal:
   - ``` 
        cd tailscale-chat-demo
        .\venv\Scripts\activate
        cd client
        python main.py
     ```

# You should see users authenticating, connecting directly to OpenClaw via Tailscale, and receiving AI responses — all without the backend being involved in the chat.


### Terminal Summary 
1. You need 4 terminals running:
    - Terminal 1: ollama serve
    - Terminal 2: docker-compose up
    - Terminal 3: cd backend && python main.py
    - Terminal 4: cd client && python main.py

### Troubleshooting
Problem	                            Fix
OpenClaw not reachable	            Wait for OpenClaw to finish starting. Check docker logs openclaw
tailscale status shows offline	    Delete stale nodes at admin panel, then docker-compose down -v && docker-compose up
No model found	                    Make sure Ollama is running (ollama serve) and you've pulled a model (ollama pull llama3.2)
curl returns connection refused	    OpenClaw is still starting. Wait for Uvicorn running in Docker logs
Docker can't pull images	        Check internet connection and Docker Desktop is running
TS_AUTHKEY error	                Make sure .env file exists and the key is valid