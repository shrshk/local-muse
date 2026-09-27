"""A fake Telegram Bot API for integration tests. Mounted into a test-only container; never in
an image. Implements getUpdates (long poll), sendMessage, answerCallbackQuery, editMessageText,
plus /__test endpoints to inject updates and read what the bot sent."""

import asyncio
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

TOKEN = os.environ.get("MOCK_TOKEN", "test-token")
app = FastAPI()
state: dict[str, Any] = {"updates": [], "next_update": 1, "next_message": 100, "log": []}
changed = asyncio.Condition()


def bad_token(token: str) -> JSONResponse | None:
    if token != TOKEN:
        return JSONResponse({"ok": False, "description": "Unauthorized"}, status_code=401)
    return None


@app.get("/bot{token}/getUpdates")
async def get_updates(
    token: str, offset: int | None = None, wait_s: int = Query(default=0, alias="timeout")
) -> Any:
    if (error := bad_token(token)) is not None:
        return error
    if offset is not None:
        state["updates"] = [u for u in state["updates"] if u["update_id"] >= offset]
    if not state["updates"] and wait_s:
        async with changed:
            try:
                await asyncio.wait_for(changed.wait(), min(wait_s, 25))
            except TimeoutError:
                pass
    return {"ok": True, "result": list(state["updates"])}


@app.post("/bot{token}/{method}")
async def call(token: str, method: str, request: Request) -> Any:
    if (error := bad_token(token)) is not None:
        return error
    body = await request.json()
    entry = {"method": method, **body}
    state["log"].append(entry)
    if method == "sendMessage":
        state["next_message"] += 1
        entry["message_id"] = state["next_message"]
        return {
            "ok": True,
            "result": {"message_id": state["next_message"], "chat": {"id": body["chat_id"]}},
        }
    return {"ok": True, "result": True}


@app.post("/__test/updates")
async def inject(update: dict[str, Any]) -> Any:
    update["update_id"] = state["next_update"]
    state["next_update"] += 1
    state["updates"].append(update)
    async with changed:
        changed.notify_all()
    return {"update_id": update["update_id"]}


@app.get("/__test/log")
async def log() -> Any:
    return state["log"]


@app.post("/__test/reset")
async def reset() -> Any:
    state["log"].clear()
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="warning")
