from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol

from quant_strategies.core.serialization import json_safe_value
from quant_strategies.datetime_utils import parse_aware_datetime
from quant_strategies.evidence_semantics import causality_evidence_fields

RowContractReason = Literal[
    "row_missing_required_field",
    "row_invalid_timestamp",
    "row_invalid_numeric_field",
    "row_invalid_ohlc_order",
    "row_duplicate_symbol_timestamp",
    "row_invalid_available_at",
    "row_missing_available_at",
    "row_missing_quote_field",
    "row_invalid_funding_fields",
]
RowContractSeverity = Literal["warning", "error"]

_BASE_REQUIRED_FIELDS = ("symbol", "timestamp", "open", "high", "low", "close")
_OHLC_FIELDS = ("open", "high", "low", "close")
_QUOTE_FIELDS = ("bid", "ask", "mid")
_ISSUE_SAMPLE_SIZE = 25


@dataclass(frozen=True)
class RowContractIssue:
    reason: RowContractReason
    field: str | None
    symbol: str | None
    timestamp: Any
    severity: RowContractSeverity
    message: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "field": self.field,
            "symbol": self.symbol,
            "timestamp": json_safe_value(self.timestamp),
            "severity": self.severity,
            "message": self.message,
        }

    def as_dict(self) -> dict[str, Any]:
        return self.to_jsonable()


class _IssueSink(Protocol):
    def append(self, issue: RowContractIssue) -> None: ...


class _IssueAccumulator:
    def __init__(self, *, sample_size: int) -> None:
        self._sample_size = sample_size
        self._next_index = 0
        self._first_samples_by_key: dict[
            tuple[object, object, object],
            tuple[int, RowContractIssue],
        ] = {}
        self._overflow_samples: list[tuple[int, RowContractIssue]] = []
        self._issue_reasons: Counter[str] = Counter()
        self._missing_required_fields: Counter[str] = Counter()
        self._funding_event_missing_fields: Counter[str] = Counter()
        self._error_issue_reasons: Counter[str] = Counter()
        self._error_issue_fields: Counter[tuple[str, str | None]] = Counter()
        self.issue_count = 0
        self.has_errors = False

    def append(self, issue: RowContractIssue) -> None:
        index = self._next_index
        self._next_index += 1
        self.issue_count += 1
        self._issue_reasons[issue.reason] += 1
        self._record_summary_counts(issue)
        self._append_sample(index, issue)

    def sample(self) -> tuple[RowContractIssue, ...]:
        samples = [*self._first_samples_by_key.values(), *self._overflow_samples]
        return tuple(issue for _, issue in sorted(samples, key=lambda item: item[0]))

    def issue_reason_items(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self._issue_reasons.items()))

    def missing_required_field_items(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self._missing_required_fields.items()))

    def funding_event_missing_field_items(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self._funding_event_missing_fields.items()))

    def quant_data_feedback_items(self) -> tuple[str, ...]:
        feedback: list[str] = []
        for (reason, field_name), count in sorted(self._error_issue_fields.items()):
            if field_name is None:
                feedback.append(f"{reason}:{count}")
            else:
                feedback.append(f"{reason}:{field_name}:{count}")
        for reason, count in sorted(self._error_issue_reasons.items()):
            if not any(item.startswith(f"{reason}:") for item in feedback):
                feedback.append(f"{reason}:{count}")
        return tuple(feedback)

    def _record_summary_counts(self, issue: RowContractIssue) -> None:
        if issue.severity == "error":
            self.has_errors = True
            self._error_issue_reasons[issue.reason] += 1
            self._error_issue_fields[(issue.reason, issue.field)] += 1

        if issue.field is None:
            return
        if issue.reason in {"row_missing_required_field", "row_missing_quote_field"}:
            self._missing_required_fields[issue.field] += 1
        if issue.reason == "row_missing_available_at":
            self._missing_required_fields[issue.field] += 1
        if issue.reason == "row_invalid_funding_fields":
            self._funding_event_missing_fields[issue.field] += 1

    def _append_sample(self, index: int, issue: RowContractIssue) -> None:
        if self._sample_size <= 0:
            return

        key = _issue_sample_key(issue)
        if key not in self._first_samples_by_key:
            if len(self._first_samples_by_key) < self._sample_size:
                self._first_samples_by_key[key] = (index, issue)
                self._trim_overflow()
            return

        if self._sample_count() < self._sample_size:
            self._overflow_samples.append((index, issue))

    def _sample_count(self) -> int:
        return len(self._first_samples_by_key) + len(self._overflow_samples)

    def _trim_overflow(self) -> None:
        while self._sample_count() > self._sample_size and self._overflow_samples:
            self._overflow_samples.pop()


@dataclass(frozen=True)
class NormalizedRows(Sequence[Mapping[str, Any]]):
    data_kind: str
    required_fields: tuple[str, ...]
    issues: tuple[RowContractIssue, ...]
    issue_count: int
    normalized_rows_sha256: str
    data_availability_status: str
    duplicate_key_count: int
    _storage: tuple[tuple[tuple[str, Any], ...], ...] = field(repr=False)
    _range_items: tuple[tuple[str, tuple[tuple[str, Any], ...]], ...] = field(repr=False)
    _availability_coverage_items: tuple[tuple[str, Any], ...] = field(repr=False)
    _issue_reason_items: tuple[tuple[str, int], ...] = field(repr=False)
    _missing_required_field_items: tuple[tuple[str, int], ...] = field(repr=False)
    _funding_event_missing_field_items: tuple[tuple[str, int], ...] = field(repr=False)
    _quant_data_feedback_items: tuple[str, ...] = field(repr=False)
    _has_error_issues: bool = field(repr=False)
    _projection_rows_cache: tuple[Mapping[str, Any], ...] | None = field(
        default=None,
        init=False,
        compare=False,
        repr=False,
    )
    _by_symbol_timestamp_cache: Mapping[tuple[str, datetime], Mapping[str, Any]] | None = field(
        default=None,
        init=False,
        compare=False,
        repr=False,
    )

    @classmethod
    def from_rows(
        cls,
        config: Any,
        rows: Iterable[Mapping[str, Any]],
    ) -> NormalizedRows:
        data_kind = _data_kind(config)
        fill_price = _fill_price(config)
        required_fields = required_row_fields(config)
        normalized_rows: list[dict[str, Any]] = []
        issues = _IssueAccumulator(sample_size=_ISSUE_SAMPLE_SIZE)
        valid_available_at = 0
        invalid_available_at = 0
        seen_keys: set[tuple[str, Any]] = set()
        duplicate_key_count = 0

        for raw_row in rows:
            normalized = _normalize_mapping_keys(raw_row)
            symbol = _symbol_for_issue(normalized)
            raw_timestamp = normalized.get("timestamp")
            parsed_timestamp = _normalize_timestamp_field(
                normalized,
                field_name="timestamp",
                issue_reason="row_invalid_timestamp",
                issues=issues,
                symbol=symbol,
            )

            for field_name in _BASE_REQUIRED_FIELDS:
                if _is_missing_required_field(normalized, field_name):
                    issues.append(
                        _issue(
                            "row_missing_required_field",
                            field_name,
                            normalized,
                            severity="error",
                            message=f"row is missing required field {field_name!r}",
                        )
                    )

            for field_name in _OHLC_FIELDS:
                if _is_missing(normalized, field_name):
                    continue
                _normalize_numeric_field(
                    normalized,
                    field_name,
                    issues,
                    minimum=0.0,
                    allow_zero=False,
                )
            _validate_ohlc_order(normalized, issues)

            _normalize_funding_fields(
                normalized,
                issues,
                require_has_funding_event=data_kind == "crypto_perp_funding",
            )
            _normalize_quote_fields(
                normalized,
                issues,
                require_fields=data_kind == "forex_with_quotes" and fill_price == "quote",
            )

            available_at = normalized.get("available_at")
            if _is_missing(normalized, "available_at"):
                issues.append(
                    _issue(
                        "row_missing_available_at",
                        "available_at",
                        normalized,
                        severity="error",
                        message="row is missing available_at",
                    )
                )
            else:
                parsed_available_at, _ = parse_aware_datetime(available_at)
                if parsed_available_at is None:
                    invalid_available_at += 1
                    issues.append(
                        _issue(
                            "row_invalid_available_at",
                            "available_at",
                            normalized,
                            severity="error",
                            message="available_at must be a timezone-aware datetime",
                        )
                    )
                else:
                    normalized["available_at"] = parsed_available_at
                    valid_available_at += 1

            if symbol is not None and "timestamp" in normalized:
                key_timestamp = _duplicate_timestamp_key(
                    parsed_timestamp=parsed_timestamp,
                    raw_timestamp=raw_timestamp,
                )
                key = (symbol, key_timestamp)
                if key in seen_keys:
                    duplicate_key_count += 1
                    issues.append(
                        RowContractIssue(
                            reason="row_duplicate_symbol_timestamp",
                            field=None,
                            symbol=symbol,
                            timestamp=key_timestamp,
                            severity="error",
                            message="row duplicates an existing symbol/timestamp key",
                        )
                    )
                else:
                    seen_keys.add(key)

            if parsed_timestamp is not None:
                normalized["timestamp"] = parsed_timestamp
            elif raw_timestamp is not None:
                normalized["timestamp"] = raw_timestamp
            normalized_rows.append(normalized)

        storage = tuple(_storage_row(row) for row in normalized_rows)
        total = len(normalized_rows)
        availability_status = _availability_status(
            total=total,
            valid=valid_available_at,
            invalid=invalid_available_at,
        )
        availability_fraction = None if total == 0 else valid_available_at / total
        availability_coverage: dict[str, Any] = {
            "field": "available_at",
            "present": valid_available_at,
            "total": total,
            "fraction": availability_fraction,
        }
        if invalid_available_at:
            availability_coverage["invalid"] = invalid_available_at

        return cls(
            data_kind=data_kind,
            required_fields=required_fields,
            issues=issues.sample(),
            issue_count=issues.issue_count,
            normalized_rows_sha256=_normalized_rows_sha256_from_storage(storage),
            data_availability_status=availability_status,
            duplicate_key_count=duplicate_key_count,
            _storage=storage,
            _range_items=_range_items(normalized_rows),
            _availability_coverage_items=tuple(availability_coverage.items()),
            _issue_reason_items=issues.issue_reason_items(),
            _missing_required_field_items=issues.missing_required_field_items(),
            _funding_event_missing_field_items=issues.funding_event_missing_field_items(),
            _quant_data_feedback_items=issues.quant_data_feedback_items(),
            _has_error_issues=issues.has_errors,
        )

    def __len__(self) -> int:
        return len(self._storage)

    def __iter__(self) -> Iterator[Mapping[str, Any]]:
        return iter(self.projection_rows())

    def __getitem__(self, index: int | slice) -> Mapping[str, Any] | tuple[Mapping[str, Any], ...]:
        return self.projection_rows()[index]

    def projection_rows(self) -> tuple[Mapping[str, Any], ...]:
        cached = self._projection_rows_cache
        if cached is None:
            cached = tuple(MappingProxyType(dict(row)) for row in self._storage)
            object.__setattr__(self, "_projection_rows_cache", cached)
        return cached

    @property
    def by_symbol_timestamp(self) -> Mapping[tuple[str, datetime], Mapping[str, Any]]:
        cached = self._by_symbol_timestamp_cache
        if cached is None:
            index: dict[tuple[str, datetime], Mapping[str, Any]] = {}
            for row in self.projection_rows():
                symbol = row.get("symbol")
                timestamp = row.get("timestamp")
                if not isinstance(symbol, str) or not _is_aware_datetime(timestamp):
                    continue
                index.setdefault((symbol, timestamp), row)
            cached = MappingProxyType(index)
            object.__setattr__(self, "_by_symbol_timestamp_cache", cached)
        return cached

    @property
    def duplicate_keys(self) -> tuple[tuple[str, datetime], ...]:
        keys: list[tuple[str, datetime]] = []
        for issue in self.issues:
            if (
                issue.reason == "row_duplicate_symbol_timestamp"
                and issue.symbol is not None
                and _is_aware_datetime(issue.timestamp)
            ):
                keys.append((issue.symbol, issue.timestamp))
        return tuple(keys)

    @property
    def ranges_by_symbol(self) -> dict[str, dict[str, Any]]:
        return {symbol: dict(items) for symbol, items in self._range_items}

    @property
    def availability_coverage(self) -> dict[str, Any]:
        return dict(self._availability_coverage_items)

    @property
    def issue_reasons(self) -> dict[str, int]:
        return dict(self._issue_reason_items)

    def row_contract_summary(self) -> dict[str, Any]:
        if len(self) == 0:
            status = "not_evaluated"
        elif self._has_error_issues:
            status = "failed"
        else:
            status = "passed"
        return {
            "data_kind": self.data_kind,
            "status": status,
            "required_fields": list(self.required_fields),
            "missing_required_fields": dict(self._missing_required_field_items),
            "timestamp_status": self._timestamp_status(),
            "duplicate_key_count": self.duplicate_key_count,
            "funding_event_missing_fields": dict(self._funding_event_missing_field_items),
            "quant_data_feedback": self._quant_data_feedback(),
            "issues": [issue.to_jsonable() for issue in self.issues],
            "issue_count": self.issue_count,
            "issue_reasons": self.issue_reasons,
        }

    def evidence_quality(
        self,
        *,
        emitted_replay_verified: bool = False,
        strict_no_emission_verified: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "data_availability_status": self.data_availability_status,
            "availability_coverage": self.availability_coverage,
            "row_contract": self.row_contract_summary(),
        }
        payload.update(
            causality_evidence_fields(
                self.data_availability_status,
                emitted_replay_verified=emitted_replay_verified,
                strict_no_emission_verified=strict_no_emission_verified,
            )
        )
        return payload

    def _timestamp_status(self) -> str:
        total = len(self)
        aware_timestamps = sum(
            1 for row in self.projection_rows() if _is_aware_datetime(row.get("timestamp"))
        )
        if total == 0:
            return "empty"
        if aware_timestamps == total:
            return "aware"
        if aware_timestamps == 0:
            return "invalid_or_naive"
        return "mixed"

    def _quant_data_feedback(self) -> list[str]:
        if len(self) == 0:
            return ["row_contract_not_evaluated:no_rows"]
        return list(self._quant_data_feedback_items)


def required_row_fields(config: Any) -> tuple[str, ...]:
    data_kind = _data_kind(config)
    fields = list(_BASE_REQUIRED_FIELDS)
    if data_kind == "crypto_perp_funding":
        fields.append("has_funding_event")
    if data_kind == "forex_with_quotes" and _fill_price(config) == "quote":
        fields.extend(_QUOTE_FIELDS)
    fields.append("available_at")
    return tuple(fields)


def _data_kind(config: Any) -> str:
    return str(config.data.kind)


def _fill_price(config: Any) -> str | None:
    return getattr(config.fill_model, "price", None)


def _normalize_mapping_keys(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in row.items()}


def _is_missing(row: Mapping[str, Any], field_name: str) -> bool:
    return field_name not in row or row.get(field_name) is None


def _is_missing_required_field(row: Mapping[str, Any], field_name: str) -> bool:
    if _is_missing(row, field_name):
        return True
    if field_name != "symbol":
        return False
    value = row.get(field_name)
    return not isinstance(value, str) or _is_blank_symbol(value)


def _is_blank_symbol(value: Any) -> bool:
    return isinstance(value, str) and value.strip() == ""


def _symbol_for_issue(row: Mapping[str, Any]) -> str | None:
    value = row.get("symbol")
    if not isinstance(value, str):
        return None
    if _is_blank_symbol(value):
        return None
    return value


def _issue(
    reason: RowContractReason,
    field_name: str | None,
    row: Mapping[str, Any],
    *,
    severity: RowContractSeverity,
    message: str,
) -> RowContractIssue:
    return RowContractIssue(
        reason=reason,
        field=field_name,
        symbol=_symbol_for_issue(row),
        timestamp=row.get("timestamp"),
        severity=severity,
        message=message,
    )


def _normalize_timestamp_field(
    row: dict[str, Any],
    *,
    field_name: str,
    issue_reason: RowContractReason,
    issues: _IssueSink,
    symbol: str | None,
) -> datetime | None:
    if _is_missing(row, field_name):
        return None
    parsed, _ = parse_aware_datetime(row.get(field_name))
    if parsed is None:
        issues.append(
            RowContractIssue(
                reason=issue_reason,
                field=field_name,
                symbol=symbol,
                timestamp=row.get(field_name)
                if field_name == "timestamp"
                else row.get("timestamp"),
                severity="error",
                message=f"{field_name} must be a timezone-aware datetime",
            )
        )
        return None
    row[field_name] = parsed
    return parsed


def _normalize_numeric_field(
    row: dict[str, Any],
    field_name: str,
    issues: _IssueSink,
    *,
    minimum: float | None = None,
    allow_zero: bool = True,
) -> float | None:
    parsed = _finite_float(row.get(field_name))
    valid = parsed is not None
    if valid and minimum is not None:
        valid = parsed >= minimum if allow_zero else parsed > minimum
    if not valid:
        issues.append(
            _issue(
                "row_invalid_numeric_field",
                field_name,
                row,
                severity="error",
                message=f"{field_name} must be a finite numeric value",
            )
        )
        return None
    row[field_name] = parsed
    return parsed


def _normalize_funding_fields(
    row: dict[str, Any],
    issues: _IssueSink,
    *,
    require_has_funding_event: bool,
) -> None:
    has_funding_event = row.get("has_funding_event")
    funding_event_required = False

    if _is_missing(row, "has_funding_event"):
        if require_has_funding_event:
            issues.append(
                _issue(
                    "row_missing_required_field",
                    "has_funding_event",
                    row,
                    severity="error",
                    message="row is missing required field 'has_funding_event'",
                )
            )
    elif not isinstance(has_funding_event, bool):
        issues.append(
            _issue(
                "row_invalid_funding_fields",
                "has_funding_event",
                row,
                severity="error",
                message="has_funding_event must be a boolean",
            )
        )
    else:
        funding_event_required = has_funding_event

    if _is_missing(row, "funding_timestamp"):
        if funding_event_required:
            issues.append(
                _issue(
                    "row_invalid_funding_fields",
                    "funding_timestamp",
                    row,
                    severity="error",
                    message="funding event row is missing funding_timestamp",
                )
            )
    else:
        parsed_funding_timestamp, _ = parse_aware_datetime(row.get("funding_timestamp"))
        if parsed_funding_timestamp is None:
            issues.append(
                _issue(
                    "row_invalid_funding_fields",
                    "funding_timestamp",
                    row,
                    severity="error",
                    message="funding_timestamp must be a timezone-aware datetime",
                )
            )
        else:
            row["funding_timestamp"] = parsed_funding_timestamp

    if _is_missing(row, "funding_rate"):
        if funding_event_required:
            issues.append(
                _issue(
                    "row_invalid_funding_fields",
                    "funding_rate",
                    row,
                    severity="error",
                    message="funding event row is missing funding_rate",
                )
            )
        return
    parsed_funding_rate = _finite_float(row.get("funding_rate"))
    if parsed_funding_rate is None:
        issues.append(
            _issue(
                "row_invalid_funding_fields",
                "funding_rate",
                row,
                severity="error",
                message="funding_rate must be finite",
            )
        )
        return
    row["funding_rate"] = parsed_funding_rate


def _normalize_quote_fields(
    row: dict[str, Any],
    issues: _IssueSink,
    *,
    require_fields: bool,
) -> None:
    for field_name in _QUOTE_FIELDS:
        if _is_missing(row, field_name):
            if require_fields:
                issues.append(
                    _issue(
                        "row_missing_quote_field",
                        field_name,
                        row,
                        severity="error",
                        message=f"quote fill row is missing required quote field {field_name!r}",
                    )
                )
            continue
        _normalize_numeric_field(
            row,
            field_name,
            issues,
            minimum=0.0,
            allow_zero=False,
        )
    _validate_quote_order(row, issues)


def _validate_ohlc_order(row: Mapping[str, Any], issues: _IssueSink) -> None:
    values = {field_name: row.get(field_name) for field_name in _OHLC_FIELDS}
    if not all(isinstance(value, float) and value > 0 for value in values.values()):
        return
    high = values["high"]
    low = values["low"]
    if high >= max(values["open"], values["close"], low) and low <= min(
        values["open"],
        values["close"],
        high,
    ):
        return
    issues.append(
        _issue(
            "row_invalid_ohlc_order",
            "ohlc",
            row,
            severity="error",
            message="OHLC fields must satisfy high >= max(open, close, low) and low <= min(open, close, high)",
        )
    )


def _validate_quote_order(row: Mapping[str, Any], issues: _IssueSink) -> None:
    values = {
        field_name: value
        for field_name in _QUOTE_FIELDS
        if isinstance((value := row.get(field_name)), float) and value > 0
    }
    bid = values.get("bid")
    ask = values.get("ask")
    mid = values.get("mid")
    if (
        (bid is None or ask is None or bid <= ask)
        and (mid is None or bid is None or mid >= bid)
        and (mid is None or ask is None or mid <= ask)
    ):
        return
    issues.append(
        _issue(
            "row_invalid_numeric_field",
            "quote",
            row,
            severity="error",
            message="quote fields must satisfy bid <= ask and bid <= mid <= ask when quote pairs are present",
        )
    )


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _is_aware_datetime(value: Any) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _duplicate_timestamp_key(
    *,
    parsed_timestamp: datetime | None,
    raw_timestamp: Any,
) -> datetime | tuple[str, Any]:
    if parsed_timestamp is not None:
        return parsed_timestamp
    return ("invalid_timestamp", _hashable_json_safe_value(raw_timestamp))


def _issue_sample_key(issue: RowContractIssue) -> tuple[object, object, object]:
    return (issue.severity, issue.reason, issue.field)


def _hashable_json_safe_value(value: Any) -> Any:
    safe_value = json_safe_value(value)
    if isinstance(safe_value, Mapping):
        return tuple(
            (str(key), _hashable_json_safe_value(item)) for key, item in sorted(safe_value.items())
        )
    if isinstance(safe_value, list | tuple):
        return tuple(_hashable_json_safe_value(item) for item in safe_value)
    return safe_value


def _availability_status(*, total: int, valid: int, invalid: int) -> str:
    if total > 0 and valid == total:
        return "complete"
    if invalid:
        return "invalid"
    if valid:
        return "partial"
    return "missing"


def _range_items(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, tuple[tuple[str, Any], ...]], ...]:
    ranges: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "")
        timestamp = row.get("timestamp")
        summary = ranges.setdefault(
            symbol,
            {"count": 0, "min_timestamp": None, "max_timestamp": None},
        )
        summary["count"] += 1
        if not _is_aware_datetime(timestamp):
            continue
        if summary["min_timestamp"] is None or timestamp < summary["min_timestamp"]:
            summary["min_timestamp"] = timestamp
        if summary["max_timestamp"] is None or timestamp > summary["max_timestamp"]:
            summary["max_timestamp"] = timestamp
    json_ranges = {
        symbol: {
            "count": summary["count"],
            "min_timestamp": json_safe_value(summary["min_timestamp"]),
            "max_timestamp": json_safe_value(summary["max_timestamp"]),
        }
        for symbol, summary in ranges.items()
    }
    return _mapping_items(dict(sorted(json_ranges.items())))


def _storage_row(row: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(
        sorted(
            ((key, _freeze_storage_value(value)) for key, value in row.items()),
            key=lambda item: item[0],
        )
    )


def _freeze_storage_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_storage_value(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_storage_value(item) for item in value)
    return value


def _mapping_items(
    mapping: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, tuple[tuple[str, Any], ...]], ...]:
    return tuple((key, tuple(value.items())) for key, value in mapping.items())


def _normalized_rows_sha256_from_storage(
    storage: Sequence[tuple[tuple[str, Any], ...]],
) -> str:
    digest = hashlib.sha256()
    for row in storage:
        line = json.dumps(
            json_safe_value(dict(row)),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


__all__ = [
    "NormalizedRows",
    "RowContractIssue",
    "RowContractReason",
    "RowContractSeverity",
    "required_row_fields",
]
