from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ROW_CONTRACT_ISSUE_SAMPLE_SIZE = 25


def compact_evidence_quality(evidence_quality_payload: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(evidence_quality_payload)
    row_contract = payload.get("row_contract")
    if isinstance(row_contract, Mapping):
        payload["row_contract"] = compact_row_contract(row_contract)
    return payload


def compact_row_contract(row_contract: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row_contract)
    issues = payload.get("issues")
    if not isinstance(issues, list):
        return payload

    issue_count = payload.get("issue_count")
    if not isinstance(issue_count, int):
        issue_count = len(issues)
    payload["issue_count"] = issue_count
    if len(issues) <= ROW_CONTRACT_ISSUE_SAMPLE_SIZE:
        payload["issue_sample_count"] = len(issues)
        payload["issues_truncated"] = issue_count > len(issues)
        return payload

    payload["issues"] = _stratified_issue_sample(issues, ROW_CONTRACT_ISSUE_SAMPLE_SIZE)
    payload["issue_sample_count"] = ROW_CONTRACT_ISSUE_SAMPLE_SIZE
    payload["issues_truncated"] = True
    return payload


def _stratified_issue_sample(issues: Sequence[Any], sample_size: int) -> list[Any]:
    selected: set[int] = set()
    seen_keys: set[tuple[object, object, object]] = set()
    for index, issue in enumerate(issues):
        key = _issue_sample_key(issue)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected.add(index)
        if len(selected) == sample_size:
            return [issues[item] for item in sorted(selected)]

    for index in range(len(issues)):
        if index in selected:
            continue
        selected.add(index)
        if len(selected) == sample_size:
            break
    return [issues[item] for item in sorted(selected)]


def _issue_sample_key(issue: object) -> tuple[object, object, object]:
    if isinstance(issue, Mapping):
        return (
            issue.get("severity"),
            issue.get("reason"),
            issue.get("field"),
        )
    return (None, None, None)
