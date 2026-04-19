import asyncio
import logging
import socket
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

stateLock = asyncio.Lock()


def sendWolPacket(macAddress: str):
    """Broadcast a WoL magic packet — 6x FF then the MAC repeated 16 times."""
    mac = macAddress.replace(":", "").replace("-", "")
    magicPacket = bytes.fromhex("FF" * 6 + mac * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magicPacket, ("<broadcast>", 9))


async def isOllamaReachable() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{config.ollamaBaseUrl}/api/tags")
            return response.status_code == 200
    except Exception:
        return False


async def waitForDesktop() -> bool:
    """Poll Ollama every wakePollIntervalSeconds until it responds or we time out."""
    deadline = time.monotonic() + config.timeouts.wakeTimeoutSeconds
    while time.monotonic() < deadline:
        if await isOllamaReachable():
            return True
        await asyncio.sleep(config.timeouts.wakePollIntervalSeconds)
    return False


async def ensureDesktopReady() -> tuple[bool, bool]:
    """
    Wake the desktop if needed, wait for Ollama to respond.
    Returns (isReady, proxyCausedWake) so the caller can inform the agent
    whether it was responsible for waking the machine.
    """
    if await isOllamaReachable():
        return True, False

    logger.info("Desktop offline — sending WoL packet")
    sendWolPacket(config.desktop.mac)

    logger.info("Waiting for desktop to come online (timeout: %ds)...", config.timeouts.wakeTimeoutSeconds)
    ready = await waitForDesktop()
    if not ready:
        logger.error("Desktop did not respond within %ds", config.timeouts.wakeTimeoutSeconds)
    return ready, True


async def registerSession(proxyCausedWake: bool) -> str | None:
    """Register with the agent and return a session ID for later deregistration."""
    try:
        async with httpx.AsyncClient(timeout=config.timeouts.agentRequestTimeoutSeconds) as client:
            response = await client.post(
                f"{config.agentBaseUrl}/session/register",
                json={"proxyCausedWake": proxyCausedWake}
            )
            return response.json()["sessionId"]
    except Exception:
        logger.warning("Could not register session with desktop agent")
        return None


async def deregisterSession(sessionId: str):
    try:
        async with httpx.AsyncClient(timeout=config.timeouts.agentRequestTimeoutSeconds) as client:
            await client.delete(f"{config.agentBaseUrl}/session/{sessionId}")
    except Exception:
        logger.warning("Could not deregister session %s", sessionId)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(request: Request, path: str):
    ready, proxyCausedWake = await ensureDesktopReady()
    if not ready:
        return JSONResponse({"error": "Desktop did not come online in time"}, status_code=503)

    sessionId = await registerSession(proxyCausedWake)

    targetUrl = f"{config.ollamaBaseUrl}/{path}"
    bodyBytes = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}

    client = httpx.AsyncClient(timeout=None)
    upstreamRequest = client.build_request(
        request.method,
        targetUrl,
        headers=headers,
        params=dict(request.query_params),
        content=bodyBytes,
    )

    try:
        upstreamResponse = await client.send(upstreamRequest, stream=True)
    except Exception as e:
        await client.aclose()
        if sessionId:
            await deregisterSession(sessionId)
        return JSONResponse({"error": str(e)}, status_code=502)

    async def streamGenerator():
        """Stream response chunks, then deregister the session once exhausted."""
        try:
            async for chunk in upstreamResponse.aiter_bytes():
                yield chunk
        finally:
            await upstreamResponse.aclose()
            await client.aclose()
            if sessionId:
                await deregisterSession(sessionId)

    # Strip hop-by-hop headers that shouldn't be forwarded to the client
    forwardHeaders = {
        k: v for k, v in upstreamResponse.headers.items()
        if k.lower() not in ("transfer-encoding", "content-encoding")
    }

    return StreamingResponse(
        streamGenerator(),
        status_code=upstreamResponse.status_code,
        headers=forwardHeaders,
        media_type=upstreamResponse.headers.get("content-type"),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.ports.proxyPort)
