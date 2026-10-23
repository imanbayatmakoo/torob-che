"""FastAPI app: SSE chat endpoint + static frontend."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app import agent
from app import tools as T

app = FastAPI(title="Torob Shopping Companion")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
STATIC = Path(__file__).resolve().parents[2] / "frontend" / "web"


@app.get("/api/health")
def health():
    return {"ok": True, "snapshot": str(T.snapshot())}


@app.post("/api/chat")
async def chat(req: Request):
    body = await req.json()
    s = agent.get_session(body.get("session_id"))
    q: asyncio.Queue = asyncio.Queue()

    def emit(ev: dict):
        q.put_nowait(ev)

    async def run():
        try:
            await agent.handle(s, body.get("text"), body.get("action"), emit)
        except Exception as e:  # noqa: BLE001
            emit({"type": "message", "text": "خطایی رخ داد؛ دوباره امتحان کنید.", "error": str(e)[:300]})
        finally:
            q.put_nowait(None)

    async def stream():
        yield f"data: {json.dumps({'type': 'session', 'session_id': s.id})}\n\n"
        task = asyncio.create_task(run())
        while True:
            ev = await q.get()
            if ev is None:
                break
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        await task
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/model/{model_key}")
def model(model_key: str):
    return JSONResponse(T.model_specs(model_key))


if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = STATIC / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC / "index.html")
