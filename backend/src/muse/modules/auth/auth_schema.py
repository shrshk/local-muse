"""Shapes for the auth domain."""

import uuid

from pydantic import BaseModel, Field


class Principal(BaseModel):
    id: uuid.UUID
    username: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
