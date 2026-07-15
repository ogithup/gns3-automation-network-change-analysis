"""Structured report models for Sprint 17."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from pydantic import BaseModel, Field


class ReportSection(BaseModel):
    title: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class GeneratedReport(BaseModel):
    id: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    html_content: str
    pdf_base64: str
    summary: str
    sections: list[ReportSection] = Field(default_factory=list)
