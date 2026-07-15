"""Prompt-injection detection and context sanitization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.ai.models import SafetyFinding


INJECTION_PATTERNS = {
    "ignore previous": "Attempts to override system or developer instructions.",
    "ignore all previous": "Attempts to override system or developer instructions.",
    "system prompt": "Attempts to reveal or target hidden prompt context.",
    "developer message": "Attempts to reveal or target hidden prompt context.",
    "bypass validation": "Attempts to skip deterministic validation.",
    "bypass schema": "Attempts to skip schema validation.",
    "call gns3 directly": "Attempts to bypass the deterministic workflow boundary.",
    "execute configuration": "Attempts to directly execute device configuration.",
    "approve automatically": "Attempts to skip human approval.",
    "tool call": "Attempts to manipulate tool invocation.",
    "<script": "Potential script injection content.",
    "rm -rf": "Potential destructive shell instruction.",
}


@dataclass(frozen=True)
class SanitizationResult:
    sanitized_text: str
    safety_findings: list[SafetyFinding]


def inspect_text(source: str, text: str) -> list[SafetyFinding]:
    lowered = text.casefold()
    findings: list[SafetyFinding] = []
    for pattern, detail in INJECTION_PATTERNS.items():
        if pattern in lowered:
            findings.append(
                SafetyFinding(
                    source=source,
                    pattern=pattern,
                    detail=detail,
                    severity="high" if pattern in {"ignore previous", "ignore all previous", "call gns3 directly", "approve automatically"} else "warning",
                ),
            )
    return findings


def collect_strings(source: str, value: Any) -> list[tuple[str, str]]:
    if value is None:
        return []
    if isinstance(value, str):
        return [(source, value)]
    if isinstance(value, dict):
        pairs: list[tuple[str, str]] = []
        for key, item in value.items():
            pairs.extend(collect_strings(f"{source}.{key}", item))
        return pairs
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        pairs: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            pairs.extend(collect_strings(f"{source}[{index}]", item))
        return pairs
    return []


def sanitize_context(value: Any) -> tuple[Any, list[SafetyFinding]]:
    findings: list[SafetyFinding] = []
    if isinstance(value, str):
        matches = inspect_text("context", value)
        findings.extend(matches)
        if matches:
            return "[sanitized-context]", findings
        return value, findings
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            sanitized_item, item_findings = sanitize_context(item)
            sanitized[key] = sanitized_item
            findings.extend(item_findings)
        return sanitized, findings
    if isinstance(value, list):
        sanitized_items: list[Any] = []
        for item in value:
            sanitized_item, item_findings = sanitize_context(item)
            sanitized_items.append(sanitized_item)
            findings.extend(item_findings)
        return sanitized_items, findings
    return value, findings


def sanitize_prompt(text: str) -> SanitizationResult:
    findings = inspect_text("user_prompt", text)
    if findings:
        return SanitizationResult(
            sanitized_text=text,
            safety_findings=findings,
        )
    return SanitizationResult(sanitized_text=text.strip(), safety_findings=[])
