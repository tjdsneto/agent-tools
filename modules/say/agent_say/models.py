from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Option(BaseModel):
    id: str
    label: str


class InputSpec(BaseModel):
    enabled: bool = True
    placeholder: str = ""
    required: bool = False


class PingRequest(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    options: list[Option] = Field(default_factory=list)
    input: InputSpec | None = None
    speak: bool = False
    level: Literal["info", "warn", "critical"] = "info"


class PingResponse(BaseModel):
    status: Literal["ok", "timeout", "cancelled", "error"]
    choice: str | None = None
    text: str | None = None
    elapsed_ms: int = 0
