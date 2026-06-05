from __future__ import annotations

from collections.abc import Sequence

_VALIDATION_SCENARIO_KINDS = (
    "base",
    "realistic_costs",
    "stressed_costs",
    "fill_lag_plus_1",
)
_SCENARIO_ARTIFACT_SUBDIRS = ("decision_records", "trade_ledgers")


def safe_scenario_artifact_path(scenario_id: str) -> str:
    safe_parts = [
        "".join(char if char.isalnum() or char in "_.-" else "-" for char in part).strip(".")
        for part in scenario_id.split("/")
    ]
    safe_parts = [part or "scenario" for part in safe_parts]
    return "/".join(safe_parts)


def validation_artifact_path_collisions(window_ids: Sequence[str]) -> tuple[str, ...]:
    entries = [
        (window_id, artifact_path, _normalized_artifact_parts(artifact_path))
        for window_id in window_ids
        for artifact_path in _window_artifact_paths(window_id)
    ]
    collisions: list[str] = []
    seen: dict[tuple[str, ...], tuple[str, str]] = {}
    for window_id, artifact_path, normalized_parts in entries:
        existing = seen.get(normalized_parts)
        if existing is not None:
            collisions.append(
                f"{existing[0]!r}:{existing[1]!r} and {window_id!r}:{artifact_path!r}"
            )
            continue
        seen[normalized_parts] = (window_id, artifact_path)

    for index, (left_id, left_path, left_parts) in enumerate(entries):
        for right_id, right_path, right_parts in entries[index + 1 :]:
            if _is_prefix(left_parts, right_parts):
                collisions.append(
                    f"{left_id!r}:{left_path!r} is a parent of {right_id!r}:{right_path!r}"
                )
            elif _is_prefix(right_parts, left_parts):
                collisions.append(
                    f"{right_id!r}:{right_path!r} is a parent of {left_id!r}:{left_path!r}"
                )

    return tuple(dict.fromkeys(collisions))


def _window_artifact_paths(window_id: str) -> tuple[str, ...]:
    safe_window_id = safe_scenario_artifact_path(window_id)
    paths = [f"data_rows/{safe_window_id}.jsonl"]
    for subdir in _SCENARIO_ARTIFACT_SUBDIRS:
        for scenario_kind in _VALIDATION_SCENARIO_KINDS:
            safe_scenario_id = safe_scenario_artifact_path(f"{window_id}/{scenario_kind}")
            paths.append(f"backend_runs/{subdir}/{safe_scenario_id}.jsonl")
    return tuple(paths)


def _normalized_artifact_parts(path: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.split("/"))


def _is_prefix(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    return len(left) < len(right) and right[: len(left)] == left
