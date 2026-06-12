from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

ROW_CONTRACT_ISSUE_SAMPLE_SIZE = 25


@dataclass(frozen=True)
class _FrozenMapping:
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class _FrozenSequence:
    items: tuple[Any, ...]


FrozenMappingPayload = _FrozenMapping


@dataclass(frozen=True)
class CausalityVerification:
    causality_check: str = "micro"
    verified: bool = False
    deterministic_replay_verified: bool = False
    emitted_replay_verified: bool = False
    strict_no_emission_verified: bool = False
    strict_replay_capped: bool = False
    strict_probe_count: int | None = None
    strict_probe_limit: int | None = None
    skipped_probe_count: int = 0
    skipped_probe_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ("runner_causality_not_verified",)
    replay_scope: str | None = None
    candidate_probe_count: int | None = None
    selected_probe_count: int | None = None
    elapsed_seconds: float | None = None
    timeout_seconds: float | None = None
    timed_out: bool = False
    replay_warning: str | None = None

    @classmethod
    def from_replay(
        cls,
        data_availability_status: object,
        *,
        causality_check: str = "micro",
        deterministic_replay_verified: bool | None = None,
        emitted_replay_verified: bool = False,
        strict_no_emission_verified: bool = False,
        strict_replay_capped: bool = False,
        strict_probe_count: int | None = None,
        strict_probe_limit: int | None = None,
        skipped_probe_count: int = 0,
        skipped_probe_reasons: tuple[str, ...] = (),
        replay_scope: str | None = None,
        candidate_probe_count: int | None = None,
        selected_probe_count: int | None = None,
        elapsed_seconds: float | None = None,
        timeout_seconds: float | None = None,
        timed_out: bool = False,
        replay_warning: str | None = None,
    ) -> CausalityVerification:
        if data_availability_status == "complete":
            emitted = bool(emitted_replay_verified)
            strict = bool(strict_no_emission_verified)
            deterministic = (
                emitted and strict
                if deterministic_replay_verified is None
                else bool(deterministic_replay_verified)
            )
            verified = emitted and strict
            warnings: list[str] = []
            if causality_check == "off":
                warnings.append("causality_replay_skipped")
            if emitted and not strict:
                warnings.append("strict_suppression_replay_not_verified")
            if strict_replay_capped:
                warnings.append("strict_replay_capped")
            if replay_warning:
                warnings.append(replay_warning)
            if not verified:
                warnings.append("runner_causality_not_verified")
        else:
            deterministic = False
            emitted = False
            strict = False
            verified = False
            availability_warning = {
                "invalid": "available_at_invalid",
                "partial": "available_at_partial",
            }.get(str(data_availability_status), "available_at_missing")
            warnings = [availability_warning, "runner_causality_not_verified"]
        return cls(
            causality_check=causality_check,
            verified=verified,
            deterministic_replay_verified=deterministic,
            emitted_replay_verified=emitted,
            strict_no_emission_verified=strict,
            strict_replay_capped=bool(strict_replay_capped),
            strict_probe_count=strict_probe_count,
            strict_probe_limit=strict_probe_limit,
            skipped_probe_count=int(skipped_probe_count),
            skipped_probe_reasons=tuple(skipped_probe_reasons),
            warnings=tuple(warnings),
            replay_scope=replay_scope or causality_check,
            candidate_probe_count=candidate_probe_count,
            selected_probe_count=selected_probe_count,
            elapsed_seconds=elapsed_seconds,
            timeout_seconds=timeout_seconds,
            timed_out=bool(timed_out),
            replay_warning=replay_warning,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "causality_check": self.causality_check,
            "causality_verified": self.verified,
            "deterministic_replay_verified": self.deterministic_replay_verified,
            "emitted_replay_verified": self.emitted_replay_verified,
            "strict_no_emission_verified": self.strict_no_emission_verified,
            "strict_replay_capped": self.strict_replay_capped,
            "strict_probe_count": self.strict_probe_count,
            "strict_probe_limit": self.strict_probe_limit,
            "skipped_probe_count": self.skipped_probe_count,
            "skipped_probe_reasons": list(self.skipped_probe_reasons),
            "evidence_quality_warnings": list(self.warnings),
            "replay_scope": self.replay_scope or self.causality_check,
            "candidate_probe_count": self.candidate_probe_count,
            "selected_probe_count": self.selected_probe_count,
            "elapsed_seconds": self.elapsed_seconds,
            "timeout_seconds": self.timeout_seconds,
            "timed_out": self.timed_out,
            "replay_warning": self.replay_warning,
        }


@dataclass(frozen=True)
class EvidenceQuality:
    data_availability_status: str
    availability_coverage_items: FrozenMappingPayload
    row_contract_items: FrozenMappingPayload
    causality: CausalityVerification
    focused_causality_items: FrozenMappingPayload | None = None

    @classmethod
    def from_rows(
        cls,
        *,
        data_availability_status: str,
        availability_coverage: Mapping[str, Any],
        row_contract: Mapping[str, Any],
        causality: CausalityVerification | None = None,
    ) -> EvidenceQuality:
        return cls(
            data_availability_status=data_availability_status,
            availability_coverage_items=_freeze_mapping(availability_coverage),
            row_contract_items=_freeze_mapping(compact_row_contract(row_contract)),
            causality=causality or CausalityVerification.from_replay(data_availability_status),
        )

    @property
    def availability_coverage(self) -> Mapping[str, Any]:
        return MappingProxyType(_thaw_mapping(self.availability_coverage_items))

    @property
    def row_contract(self) -> Mapping[str, Any]:
        return MappingProxyType(_thaw_mapping(self.row_contract_items))

    @property
    def focused_causality(self) -> Mapping[str, Any] | None:
        if self.focused_causality_items is None:
            return None
        return MappingProxyType(_thaw_mapping(self.focused_causality_items))

    def with_causality(self, causality: CausalityVerification) -> EvidenceQuality:
        return replace(self, causality=causality)

    def with_focused_causality(self, focused_causality: Mapping[str, object]) -> EvidenceQuality:
        return replace(self, focused_causality_items=_freeze_mapping(focused_causality))

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "data_availability_status": self.data_availability_status,
            "availability_coverage": _thaw_mapping(self.availability_coverage_items),
            "row_contract": _thaw_mapping(self.row_contract_items),
        }
        payload.update(self.causality.to_payload())
        if self.focused_causality_items is not None:
            payload["focused_causality"] = _thaw_mapping(self.focused_causality_items)
        return payload


EvidenceQualityPayload = Mapping[str, Any] | EvidenceQuality


def compact_evidence_quality(evidence_quality_payload: EvidenceQualityPayload) -> dict[str, Any]:
    if isinstance(evidence_quality_payload, EvidenceQuality):
        return evidence_quality_payload.to_payload()
    payload = dict(evidence_quality_payload)
    row_contract = payload.get("row_contract")
    if isinstance(row_contract, Mapping):
        payload["row_contract"] = compact_row_contract(row_contract)
    return payload


def _freeze_mapping(mapping: Mapping[str, Any]) -> FrozenMappingPayload:
    return _FrozenMapping(tuple((str(key), _freeze_value(value)) for key, value in mapping.items()))


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return _FrozenSequence(tuple(_freeze_value(item) for item in value))
    return value


def _thaw_mapping(items: FrozenMappingPayload) -> dict[str, Any]:
    return {key: _thaw_value(value) for key, value in items.items}


def _thaw_value(value: Any) -> Any:
    if isinstance(value, _FrozenMapping):
        return _thaw_mapping(value)
    if isinstance(value, _FrozenSequence):
        return [_thaw_value(item) for item in value.items]
    return value


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
