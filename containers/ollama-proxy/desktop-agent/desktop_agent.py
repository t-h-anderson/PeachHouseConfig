import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config import config

app = FastAPI()

# Session registry — keyed by session ID, shared across all proxy clients
activeSessions: dict[str, float] = {}  # sessionId -> registration timestamp
wasWokenByProxy = False


class SessionRequest(BaseModel):
    proxyCausedWake: bool = False


def getSecondsSinceLastInput() -> float:
    """
    Read idle time from the shared file written by session_monitor.py.
    Returns 0 if the file is stale (monitor dead — assume user active to be safe).
    Returns a large value if no file exists (no user logged in — safe to treat as idle).
    """
    try:
        data = json.loads(config.paths.stateFile.read_text())
        staleness = time.time() - data["timestamp"]
        if staleness > config.timeouts.activityStalenessSeconds:
            return 0.0
        return float(data["secondsSinceInput"])
    except FileNotFoundError:
        return 9999.0
    except Exception:
        return 0.0  # unexpected error — assume active


def checkAndShutdown():
    """
    Shut down only when all proxy sessions are complete, we woke the machine,
    and the user has been idle long enough to confirm no one is using it.
    """
    global wasWokenByProxy

    if activeSessions:
        return

    if not wasWokenByProxy:
        return

    idleSeconds = getSecondsSinceLastInput()
    if idleSeconds < config.timeouts.idleThresholdSeconds:
        # User became active while we were running — relinquish ownership
        wasWokenByProxy = False
        return

    wasWokenByProxy = False
    subprocess.Popen([
        "shutdown", "/s",
        "/t", str(config.timeouts.shutdownWarningSeconds),
        "/c", "Ollama proxy: idle shutdown"
    ])


@app.get("/activity")
def activity():
    return {
        "secondsSinceInput": getSecondsSinceLastInput(),
        "activeSessions": len(activeSessions),
        "wasWokenByProxy": wasWokenByProxy,
    }


@app.post("/session/register")
def registerSession(body: SessionRequest):
    """
    Called by a proxy when it starts using the GPU.
    Returns a session ID the proxy must use when deregistering.
    Only sets wasWokenByProxy on the first session that reports it caused a wake,
    so machines that were already on are never shut down by the proxy.
    """
    global wasWokenByProxy

    sessionId = str(uuid.uuid4())
    activeSessions[sessionId] = time.time()

    if body.proxyCausedWake and len(activeSessions) == 1:
        wasWokenByProxy = True

    return {"sessionId": sessionId, "activeSessions": len(activeSessions)}


@app.delete("/session/{sessionId}")
def deregisterSession(sessionId: str):
    """Called by a proxy when its request completes."""
    if sessionId not in activeSessions:
        raise HTTPException(status_code=404, detail="Unknown session ID")

    del activeSessions[sessionId]
    checkAndShutdown()

    return {"activeSessions": len(activeSessions)}


@app.delete("/shutdown")
def cancelShutdown():
    subprocess.Popen(["shutdown", "/a"])
    return {"status": "shutdown cancelled"}


if __name__ == "__main__":
    if sys.platform != "win32":
        raise RuntimeError("desktop_agent must run on Windows")
    uvicorn.run(app, host="0.0.0.0", port=config.ports.agentPort)
