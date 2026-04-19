# ollama-link

Routes Ollama requests to a GPU desktop over Tailscale, waking it via Wake-on-LAN if needed and shutting it down again when idle.

## Components

### `ollama-proxy/` — runs on server (Docker)

A transparent HTTP proxy that sits in front of Ollama. Any client that points at servername:11434 gets routed to the desktop's GPU automatically.

- Checks if the desktop is already on before sending a WoL packet
- Waits for Ollama to respond before forwarding requests
- Registers a session with the desktop agent for every in-flight request
- Supports multiple simultaneous clients — the desktop won't shut down until all sessions are complete

### `desktop-agent/` — runs on the Windows desktop (NSSM service + Task Scheduler)

Two processes:

- **`desktop_agent.py`** — FastAPI service (NSSM, runs as SYSTEM). Tracks active proxy sessions and decides when to shut down.
- **`session_monitor.py`** — lightweight poller (Task Scheduler, runs as logged-in user). Writes Win32 idle time to a shared file so the agent can detect whether someone is actually using the machine.

## Setup

### Desktop agent

1. Install dependencies: `pip install fastapi uvicorn pydantic`
2. Edit `desktop-agent/config.toml` to set your preferred ports and timeouts
3. Install `desktop_agent.py` as a Windows service via [NSSM](https://nssm.cc):

```powershell
nssm install OllamaDesktopAgent "C:\Python312\pythonw.exe"
nssm set OllamaDesktopAgent AppParameters "C:\path\to\desktop_agent.py"
nssm set OllamaDesktopAgent AppDirectory "C:\path\to\desktop-agent\"
nssm set OllamaDesktopAgent Start SERVICE_AUTO_START
nssm set OllamaDesktopAgent ObjectName LocalSystem
nssm start OllamaDesktopAgent
```

4. Register `session_monitor.py` in Task Scheduler:
   - Trigger: At log on → Any user
   - Action: `pythonw.exe C:\path\to\session_monitor.py`
   - Run only when user is logged on: ✓

5. Open inbound port 5001 (or your configured `agentPort`) in Windows Firewall

### Ollama as a service (optional but recommended)

So Ollama is available before anyone logs in:

```powershell
nssm install Ollama "C:\Users\tomha\AppData\Local\Programs\Ollama\ollama.exe"
nssm set Ollama AppParameters "serve"
nssm set Ollama Start SERVICE_AUTO_START
nssm set Ollama ObjectName LocalSystem
nssm set Ollama AppEnvironmentExtra OLLAMA_HOST=0.0.0.0
nssm start Ollama
```

### Ollama proxy (server)

1. Edit `ollama-proxy/config.toml` — set `desktop.ip`, `desktop.mac`, and ports
2. Find your desktop MAC address: run `ipconfig /all` on Windows, look for the Ethernet or Wi-Fi adapter
3. Deploy:

```bash
cd ollama-proxy
docker compose up -d
```

Point any Ollama client at `server:11434` instead of the desktop directly.
