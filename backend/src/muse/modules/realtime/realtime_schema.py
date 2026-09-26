"""Shapes for the realtime domain."""

from pydantic import BaseModel


class ConnectionToken(BaseModel):
    token: str
    expires_in: int
