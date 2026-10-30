"""Shared response envelopes."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Uniform pagination envelope used by every list endpoint."""

    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class ErrorDetail(BaseModel):
    code: str
    message: str
    field_errors: dict[str, list[str]] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """The only error shape the API returns. Never contains a stack trace."""

    error: ErrorDetail


class ActionResult(BaseModel):
    ok: bool = True
    message: str = ""
    detail: dict[str, object] = Field(default_factory=dict)


class PaginationParams(BaseModel):
    limit: int = Field(default=25, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
