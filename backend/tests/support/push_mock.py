"""Fake push service for integration tests: records every push, can answer 410 Gone."""

from typing import Any

import uvicorn
from fastapi import FastAPI, Request, Response

app = FastAPI()
received: list[dict[str, Any]] = []
gone: set[str] = set()


@app.post("/p/{sub_id}")
async def push(sub_id: str, request: Request) -> Response:
    if sub_id in gone:
        return Response(status_code=410)
    received.append(
        {"sub": sub_id, "headers": dict(request.headers), "body": (await request.body()).hex()}
    )
    return Response(status_code=201)


@app.get("/__test/received")
async def log() -> list[dict[str, Any]]:
    return received


@app.post("/__test/gone/{sub_id}")
async def mark_gone(sub_id: str) -> None:
    gone.add(sub_id)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8082, log_level="warning")
