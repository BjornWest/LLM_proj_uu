#!/usr/bin/env python3
"""Inspect Codex session usage metadata and estimate catalog-priced cost.

The scanner intentionally retains only session, turn-context, and token-accounting
metadata. Conversation and tool payloads are never added to the in-memory index.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

UTC = dt.timezone.utc
COUNTERS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens")


class CliError(Exception):
    """A user-facing CLI error."""


def object_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_timestamp(value: Any, label: str = "timestamp") -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} is not a string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone: {value!r}")
    return parsed.astimezone(UTC)


def iso_utc(value: dt.datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def nested(payload: dict[str, Any], key: str) -> Any:
    for container in (payload, object_value(payload.get("request")), object_value(payload.get("metadata"))):
        if container.get(key) is not None:
            return container[key]
    return None


def scan_sessions(root: Path) -> dict[str, Any]:
    threads: dict[str, dict[str, Any]] = {}
    contexts: dict[tuple[str, str], list[tuple[dt.datetime, str]]] = defaultdict(list)
    records: list[dict[str, Any]] = []
    invalid_timestamp_records: list[dict[str, str]] = []
    diagnostics = {"session_files_scanned": 0, "malformed_json_lines": 0, "invalid_event_timestamps": 0}

    for filename in sorted(root.glob("**/*.jsonl")):
        diagnostics["session_files_scanned"] += 1
        first_meta: dict[str, Any] | None = None
        file_contexts: list[tuple[dt.datetime, dict[str, Any]]] = []
        file_records: list[tuple[dt.datetime, dict[str, Any]]] = []
        file_invalid_timestamp_records: list[dict[str, Any]] = []
        cumulative_count = 0
        try:
            stream = filename.open(encoding="utf-8")
        except OSError:
            continue
        with stream:
            for raw in stream:
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    diagnostics["malformed_json_lines"] += 1
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("type")
                payload = object_value(event.get("payload"))
                if kind == "session_meta" and first_meta is None:
                    first_meta = payload
                    continue
                if kind == "event_msg" and payload.get("type") == "token_count":
                    cumulative_count += 1
                    continue
                if kind not in ("turn_context", "token_usage_record"):
                    continue
                try:
                    when = parse_timestamp(event.get("timestamp"))
                except ValueError:
                    diagnostics["invalid_event_timestamps"] += 1
                    if kind == "token_usage_record":
                        file_invalid_timestamp_records.append(payload)
                    continue
                if kind == "turn_context":
                    file_contexts.append((when, payload))
                else:
                    file_records.append((when, payload))
        if first_meta is None:
            continue
        thread_id = first_meta.get("id") or first_meta.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            continue
        source = object_value(first_meta.get("source"))
        spawn = object_value(object_value(source.get("subagent")).get("thread_spawn"))
        parent = first_meta.get("parent_thread_id") or spawn.get("parent_thread_id")
        agent_path = first_meta.get("agent_path") or spawn.get("agent_path")
        current = threads.setdefault(thread_id, {
            "thread_id": thread_id,
            "parent_thread_id": parent if isinstance(parent, str) else None,
            "agent_path": agent_path if isinstance(agent_path, str) else None,
            "cwd": first_meta.get("cwd") if isinstance(first_meta.get("cwd"), str) else None,
            "files": 0,
            "cumulative_events": 0,
        })
        current["files"] += 1
        current["cumulative_events"] += cumulative_count
        for key, value in (("parent_thread_id", parent), ("agent_path", agent_path), ("cwd", first_meta.get("cwd"))):
            if current.get(key) is None and isinstance(value, str):
                current[key] = value
        for when, payload in file_contexts:
            turn_id, model = payload.get("turn_id"), payload.get("model")
            if isinstance(turn_id, str) and isinstance(model, str) and model:
                contexts[(thread_id, turn_id)].append((when, model))
        for when, payload in file_records:
            # Forked session files can contain inherited history. Attribute only
            # records whose own thread identity matches the file's first metadata.
            if payload.get("thread_id") == thread_id:
                records.append({"timestamp": when, "payload": payload, "thread_id": thread_id, "file": str(filename)})
        for payload in file_invalid_timestamp_records:
            if payload.get("thread_id") == thread_id:
                invalid_timestamp_records.append({"thread_id": thread_id, "file": str(filename)})

    for values in contexts.values():
        values.sort(key=lambda item: item[0])
    for record in records:
        payload = record["payload"]
        model = nested(payload, "model")
        if not isinstance(model, str) or not model:
            turn_id = payload.get("turn_id")
            matches = contexts.get((record["thread_id"], turn_id), []) if isinstance(turn_id, str) else []
            eligible = [candidate for when, candidate in matches if when <= record["timestamp"]]
            model = eligible[-1] if eligible else "unknown"
        record["model"] = model
    return {
        "threads": threads, "records": records,
        "invalid_timestamp_records": invalid_timestamp_records,
        "diagnostics": diagnostics,
    }


def in_window(when: dt.datetime, start: dt.datetime | None, end: dt.datetime | None) -> bool:
    return (start is None or start <= when) and (end is None or when < end)


def resolve_descendants(threads: dict[str, dict[str, Any]], roots: set[str]) -> set[str]:
    selected = set(roots)
    changed = True
    while changed:
        changed = False
        for thread_id, meta in threads.items():
            if meta.get("parent_thread_id") in selected and thread_id not in selected:
                selected.add(thread_id)
                changed = True
    return selected


def command_threads(args: argparse.Namespace) -> int:
    index = scan_sessions(args.sessions)
    start = parse_timestamp(args.start, "--start") if args.start else None
    end = parse_timestamp(args.end, "--end") if args.end else None
    if start and end and start >= end:
        raise CliError("--start must be before --end")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in index["records"]:
        if in_window(record["timestamp"], start, end):
            grouped[record["thread_id"]].append(record)
    rows = []
    for thread_id, meta in index["threads"].items():
        selected = grouped.get(thread_id, [])
        if (start is not None or end is not None) and not selected:
            continue
        stamps = [record["timestamp"] for record in selected]
        rows.append({
            "thread_id": thread_id,
            "parent": meta.get("parent_thread_id"),
            "agent_path": meta.get("agent_path"),
            "cwd": meta.get("cwd"),
            "models": sorted({record["model"] for record in selected}),
            "first_usage": iso_utc(min(stamps)) if stamps else None,
            "last_usage": iso_utc(max(stamps)) if stamps else None,
            "counts": {
                "token_usage_records": len(selected),
                "legacy_cumulative_events": meta.get("cumulative_events", 0),
            },
        })
    rows.sort(key=lambda row: (row["last_usage"] is not None, row["last_usage"] or "", row["thread_id"]), reverse=True)
    print(json.dumps(rows[:args.limit], separators=(",", ":"), ensure_ascii=False))
    return 0


def load_catalog(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        catalog = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(f"cannot read price catalog {path}: {exc}") from exc
    if not isinstance(catalog, dict) or catalog.get("schema") != "codex-token-prices-v1":
        raise CliError("price catalog must use schema codex-token-prices-v1")
    if catalog.get("currency") != "USD":
        raise CliError("price catalog currency must be USD")
    if not isinstance(catalog.get("models"), dict) or not isinstance(catalog.get("tier_multipliers"), dict):
        raise CliError("price catalog is missing models or tier_multipliers")
    if not catalog["models"]:
        raise CliError("price catalog models must not be empty")
    for tier, value in catalog["tier_multipliers"].items():
        if not isinstance(tier, str) or not tier:
            raise CliError("price catalog tier names must be nonempty strings")
        validated_decimal(value, f"tier_multipliers.{tier}")
    for model, model_price in catalog["models"].items():
        if not isinstance(model, str) or not model or not isinstance(model_price, dict):
            raise CliError("price catalog model entries must map nonempty names to objects")
        for field in ("input", "cached_input", "cache_write_input", "output"):
            validated_decimal(model_price.get(field), f"models.{model}.{field}")
        long_cfg = model_price.get("long_context")
        if not isinstance(long_cfg, dict):
            raise CliError(f"price catalog models.{model}.long_context must be an object")
        threshold = long_cfg.get("threshold_input_tokens")
        if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0:
            raise CliError(f"price catalog models.{model}.long_context.threshold_input_tokens must be a positive integer")
        for field in ("input_multiplier", "output_multiplier"):
            validated_decimal(long_cfg.get(field), f"models.{model}.long_context.{field}")
    return catalog, hashlib.sha256(raw).hexdigest()


def nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_usage(usage: Any) -> tuple[dict[str, int] | None, str | None]:
    if not isinstance(usage, dict):
        return None, "missing_usage"
    missing = [name for name in COUNTERS if name not in usage]
    if missing:
        return None, "missing_counter:" + ",".join(missing)
    if any(not nonnegative_integer(usage[name]) for name in COUNTERS):
        return None, "invalid_counter"
    values = {name: usage[name] for name in COUNTERS}
    if values["cached_input_tokens"] + values["cache_write_input_tokens"] > values["input_tokens"]:
        return None, "cached_plus_write_exceeds_input"
    if values["reasoning_output_tokens"] > values["output_tokens"]:
        return None, "reasoning_exceeds_output"
    return values, None


def validated_decimal(value: Any, label: str) -> Decimal:
    if not isinstance(value, str):
        raise CliError(f"price catalog {label} must be a decimal string")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise CliError(f"price catalog {label} must be a decimal string") from exc
    if not number.is_finite() or number < 0:
        raise CliError(f"price catalog {label} must be finite and nonnegative")
    return number


def decimal_field(container: dict[str, Any], key: str) -> Decimal:
    return validated_decimal(container.get(key), key)


def empty_totals() -> dict[str, int]:
    return {name: 0 for name in COUNTERS} | {"uncached_input_tokens": 0, "responses": 0, "long_context_responses": 0}


def add_tokens(total: dict[str, int], usage: dict[str, int], long_context: bool) -> None:
    for key in COUNTERS:
        total[key] += usage[key]
    total["uncached_input_tokens"] += usage["input_tokens"] - usage["cached_input_tokens"] - usage["cache_write_input_tokens"]
    total["responses"] += 1
    total["long_context_responses"] += int(long_context)


def money_string(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000000000001")), "f")


def price_record(usage: dict[str, int], model_price: dict[str, Any], tier_multiplier: Decimal) -> tuple[Decimal, bool]:
    long_cfg = model_price.get("long_context")
    is_long = isinstance(long_cfg, dict) and usage["input_tokens"] > int(long_cfg.get("threshold_input_tokens", 0))
    input_multiplier = decimal_field(long_cfg, "input_multiplier") if is_long else Decimal(1)
    output_multiplier = decimal_field(long_cfg, "output_multiplier") if is_long else Decimal(1)
    uncached = usage["input_tokens"] - usage["cached_input_tokens"] - usage["cache_write_input_tokens"]
    micro_cost = (
        Decimal(uncached) * decimal_field(model_price, "input") * input_multiplier
        + Decimal(usage["cached_input_tokens"]) * decimal_field(model_price, "cached_input") * input_multiplier
        + Decimal(usage["cache_write_input_tokens"]) * decimal_field(model_price, "cache_write_input") * input_multiplier
        + Decimal(usage["output_tokens"]) * decimal_field(model_price, "output") * output_multiplier
    )
    # Reasoning tokens are already a subset of output_tokens and are not added.
    return micro_cost * tier_multiplier / Decimal(1_000_000), is_long


def record_identity(record: dict[str, Any]) -> str:
    payload = record["payload"]
    relevant = {
        "thread_id": payload.get("thread_id"), "turn_id": payload.get("turn_id"),
        "response_id": payload.get("response_id"), "usage": payload.get("usage"), "model": record["model"],
    }
    return json.dumps(relevant, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def summarize_group(records: Iterable[dict[str, Any]], catalog: dict[str, Any], tier: str) -> dict[str, Any]:
    totals = empty_totals()
    known_cost = Decimal(0)
    unpriceable = 0
    invalid = 0
    reasons: dict[str, int] = defaultdict(int)
    tier_multiplier = decimal_field(catalog["tier_multipliers"], tier)
    for record in records:
        usage, error = validate_usage(record["payload"].get("usage"))
        model_price = catalog["models"].get(record["model"])
        if error:
            invalid += 1
            unpriceable += 1
            reasons[error] += 1
            continue
        assert usage is not None
        is_long = isinstance(model_price, dict) and isinstance(model_price.get("long_context"), dict) and usage["input_tokens"] > int(model_price["long_context"].get("threshold_input_tokens", 0))
        add_tokens(totals, usage, is_long)
        if not isinstance(model_price, dict):
            unpriceable += 1
            reasons["unknown_model"] += 1
            continue
        try:
            cost, _ = price_record(usage, model_price, tier_multiplier)
        except (CliError, TypeError, ValueError):
            unpriceable += 1
            reasons["invalid_model_price"] += 1
            continue
        known_cost += cost
    return {
        **totals,
        "known_cost_usd": money_string(known_cost),
        "estimated_cost_usd": None if unpriceable else money_string(known_cost),
        "unpriceable_responses": unpriceable,
        "invalid_usage_responses": invalid,
        "unpriceable_reasons": dict(sorted(reasons.items())),
    }


def command_estimate(args: argparse.Namespace) -> int:
    start, end = parse_timestamp(args.start, "--start"), parse_timestamp(args.end, "--end")
    if start >= end:
        raise CliError("--start must be before --end")
    index = scan_sessions(args.sessions)
    requested = list(dict.fromkeys(args.thread))
    missing = [thread_id for thread_id in requested if thread_id not in index["threads"]]
    if missing:
        raise CliError("thread ID not found: " + ", ".join(missing))
    roots = set(requested)
    selected_ids = resolve_descendants(index["threads"], roots) if args.include_descendants else roots
    selected_records = [record for record in index["records"] if record["thread_id"] in selected_ids and in_window(record["timestamp"], start, end)]
    active_threads = {record["thread_id"] for record in selected_records}

    by_response: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_response_id = 0
    missing_response_threads: set[str] = set()
    for record in selected_records:
        response_id = record["payload"].get("response_id")
        if isinstance(response_id, str) and response_id:
            by_response[response_id].append(record)
        else:
            missing_response_id += 1
            missing_response_threads.add(record["thread_id"])
    unique: list[dict[str, Any]] = []
    duplicate_records = 0
    conflicting_ids: list[str] = []
    conflicting_threads: set[str] = set()
    for response_id, copies in by_response.items():
        identities = {record_identity(record) for record in copies}
        duplicate_records += max(0, len(copies) - 1)
        if len(identities) != 1:
            conflicting_ids.append(response_id)
            conflicting_threads.update(record["thread_id"] for record in copies)
            continue
        unique.append(min(copies, key=lambda record: (record["timestamp"], record["file"])))
    unique.sort(key=lambda record: (record["timestamp"], record["thread_id"], str(record["payload"].get("response_id"))))

    catalog, fingerprint = load_catalog(args.prices)
    if args.tier not in catalog["tier_multipliers"]:
        raise CliError(f"tier {args.tier!r} is absent from price catalog")
    overall = summarize_group(unique, catalog, args.tier)
    invalid_timestamp_threads = {
        record["thread_id"] for record in index["invalid_timestamp_records"]
        if record["thread_id"] in selected_ids
    }
    threads_with_supported_telemetry = {record["thread_id"] for record in index["records"]}
    unsupported_threads = selected_ids - threads_with_supported_telemetry - invalid_timestamp_threads
    selected_cumulative_only = sorted(thread_id for thread_id in unsupported_threads if index["threads"][thread_id].get("cumulative_events"))
    selected_missing_telemetry = sorted(unsupported_threads - set(selected_cumulative_only))
    per_thread = []
    for thread_id in sorted(selected_ids):
        row = summarize_group((record for record in unique if record["thread_id"] == thread_id), catalog, args.tier)
        row_complete = not (
            row["unpriceable_responses"]
            or thread_id in conflicting_threads
            or thread_id in missing_response_threads
            or thread_id in invalid_timestamp_threads
            or thread_id in unsupported_threads
        )
        row["complete"] = row_complete
        if not row_complete:
            row["estimated_cost_usd"] = None
        meta = index["threads"][thread_id]
        per_thread.append({"thread_id": thread_id, "parent_thread_id": meta.get("parent_thread_id"), "agent_path": meta.get("agent_path"), **row})
    per_model = []
    for model in sorted({record["model"] for record in unique}):
        per_model.append({"model": model, **summarize_group((record for record in unique if record["model"] == model), catalog, args.tier)})

    completeness = not (
        conflicting_ids or missing_response_id or overall["unpriceable_responses"]
        or selected_cumulative_only or selected_missing_telemetry or invalid_timestamp_threads
    )
    # A known subtotal remains useful, but excluded ambiguous/missing telemetry
    # means there is no defensible full dollar total for the requested scope.
    if not completeness:
        overall["estimated_cost_usd"] = None
    output = {
        "schema": "codex-usage-estimate-v1",
        "scope": {
            "requested_roots": requested,
            "include_descendants": args.include_descendants,
            "resolved_threads": sorted(selected_ids),
            "resolved_descendants": sorted(selected_ids - roots),
            "active_threads": sorted(active_threads),
            "active_descendants": sorted(active_threads - roots),
            "active_thread_basis": "exact-thread token_usage_record with a valid timestamp in the window, before response-ID and usage-counter validation; unplaceable invalid timestamps are reported in coverage",
            "window": {"start": iso_utc(start), "end_exclusive": iso_utc(end)},
            "tier_scenario": args.tier,
        },
        "pricing": {
            "catalog": str(args.prices), "catalog_sha256": fingerprint,
            "catalog_schema": catalog["schema"], "as_of": catalog.get("as_of"),
            "currency": catalog.get("currency"), "source_url": catalog.get("source_url"),
            "assumptions": [
                "catalog rates are USD per million tokens",
                "the selected tier multiplier is an explicit estimate scenario",
                "long-context multipliers apply to the full qualifying request",
                "reasoning output is included in output tokens and is not charged twice",
                "cache-write input requires an explicit telemetry counter",
            ],
        },
        "coverage": {
            **index["diagnostics"],
            "candidate_records": len(selected_records), "unique_responses": len(unique),
            "duplicate_records_deduplicated": duplicate_records,
            "conflicting_response_ids_excluded": sorted(conflicting_ids),
            "records_without_response_id_excluded": missing_response_id,
            "records_without_response_id_threads": sorted(missing_response_threads),
            "invalid_timestamp_token_records": sum(
                record["thread_id"] in selected_ids for record in index["invalid_timestamp_records"]
            ),
            "invalid_timestamp_threads": sorted(invalid_timestamp_threads),
            "legacy_cumulative_only_threads": selected_cumulative_only,
            "missing_per_request_telemetry_threads": selected_missing_telemetry,
            "complete": completeness,
        },
        "total": overall,
        "per_thread": per_thread,
        "per_model": per_model,
    }
    encoded = json.dumps(output, separators=(",", ":"), ensure_ascii=False) + "\n"
    if args.output:
        try:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        except FileExistsError as exc:
            raise CliError(f"output already exists: {args.output}") from exc
        except OSError as exc:
            raise CliError(f"cannot create output {args.output}: {exc}") from exc
        compact = {
            "output": str(args.output), "threads": len(selected_ids), "active_thread_count": len(active_threads),
            "responses": overall["responses"],
            "known_cost_usd": overall["known_cost_usd"], "estimated_cost_usd": overall["estimated_cost_usd"],
            "complete": completeness,
        }
        print(json.dumps(compact, separators=(",", ":"), ensure_ascii=False))
    else:
        sys.stdout.write(encoded)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    threads = subparsers.add_parser("threads", help="list metadata-only thread usage")
    threads.add_argument("--sessions", type=Path, default=Path.home() / ".codex" / "sessions")
    threads.add_argument("--limit", type=int, default=20)
    threads.add_argument("--start")
    threads.add_argument("--end")
    threads.set_defaults(handler=command_threads)

    estimate = subparsers.add_parser("estimate", help="estimate selected thread cost")
    estimate.add_argument("--thread", action="append", required=True, help="exact root thread ID; repeatable")
    estimate.add_argument("--start", required=True, help="inclusive timezone-aware ISO timestamp")
    estimate.add_argument("--end", required=True, help="exclusive timezone-aware ISO timestamp")
    estimate.add_argument("--include-descendants", action="store_true")
    estimate.add_argument("--sessions", type=Path, default=Path.home() / ".codex" / "sessions")
    estimate.add_argument("--prices", type=Path, default=Path(__file__).resolve().parent.parent / "references" / "prices-2026-09-21.json")
    estimate.add_argument("--tier", choices=("standard", "fast", "batch", "flex"), default="standard")
    estimate.add_argument("--output", type=Path)
    estimate.set_defaults(handler=command_estimate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "limit", 1) < 0:
        parser.error("--limit must be nonnegative")
    try:
        return args.handler(args)
    except (CliError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
