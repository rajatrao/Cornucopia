"""Typed request/response contracts. Exported to contracts/openapi.json."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Liveness(BaseModel):
    status: Literal["ok"]
    service: Literal["cornucopia-api"]
    version: str
    environment: str
    transport: str
    runtime: str = Field(description="'sprite' when running inside a Fly.io Sprite")


class DbHealthOut(BaseModel):
    status: Literal["ok", "error"]
    transport: str
    db_schema: str
    server_time: datetime | None = None
    latency_ms: float
    detail: str | None = None


class ProbeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=500)


class ProbeOut(BaseModel):
    id: UUID
    note: str
    source: str
    created_at: datetime
