"""Strict allowlist at both the host-output and HTTP boundaries."""
import math
from datetime import datetime, timezone

PROVIDERS = {"codex": "CODEX", "claude": "CLAUDE CODE"}
SLOTS = ("primary", "secondary", "tertiary")
ERRORS = {"timeout", "command_failed", "invalid_payload", "source_mismatch", "cli_missing", "output_limit"}


class PayloadError(ValueError):
    pass


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, str):
        raise PayloadError("timestamp must be ISO-8601")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PayloadError("invalid timestamp") from exc
    if dt.tzinfo is None:
        raise PayloadError("timestamp needs timezone")
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PayloadError("invalid usage")
    try:
        result = float(value)
    except OverflowError as exc:
        raise PayloadError("invalid usage") from exc
    if not math.isfinite(result) or result < 0:
        raise PayloadError("invalid usage")
    return result


def duration(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 525600:
        raise PayloadError("invalid duration")
    return value


def window(slot, used, minutes, reset):
    used = number(used)
    return {"id": slot, "used_percent": used,
            "remaining_percent": max(0.0, 100.0 - used),
            "window_minutes": duration(minutes),
            "reset_at": iso(timestamp(reset)) if reset is not None else None}


def normalize(raw, provider, now, attempted_at=None):
    # Multiple accounts require a later explicit account-selection design.
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise PayloadError("expected one provider record")
    row = raw[0]
    if row.get("provider") != provider or row.get("error") is not None:
        raise PayloadError("provider failed")
    if row.get("source") != "oauth":
        raise PayloadError("source_mismatch")
    usage = row.get("usage")
    if not isinstance(usage, dict):
        raise PayloadError("missing usage")
    sampled = timestamp(usage.get("updatedAt"))
    if (sampled - now).total_seconds() > 60:
        raise PayloadError("future timestamp")
    windows = []
    for slot in SLOTS:
        lane = usage.get(slot)
        if lane is None:
            continue
        if not isinstance(lane, dict):
            raise PayloadError("invalid lane")
        if lane.get("isSyntheticPlaceholder") is True:
            continue
        windows.append(window(slot, lane.get("usedPercent"), lane.get("windowMinutes"), lane.get("resetsAt")))
    if not windows:
        raise PayloadError("no measured windows")
    return {"name": PROVIDERS[provider], "source": "oauth", "status": "ok",
            "attempted_at": iso(attempted_at or now), "last_success_at": iso(now), "sampled_at": iso(sampled),
            "error_code": None, "windows": windows}


def failure(provider, code, now, previous=None):
    if code not in ERRORS:
        code = "invalid_payload"
    old = previous or {}
    return {"name": PROVIDERS[provider], "source": "oauth", "status": "error",
            "attempted_at": iso(now), "last_success_at": old.get("last_success_at"),
            "sampled_at": old.get("sampled_at"), "error_code": code,
            "windows": old.get("windows", [])}


def snapshot(providers, now):
    return {"schema_version": 1, "updated_at": iso(now), "providers": providers}


def validate_snapshot(raw):
    """Rebuild data; never serve arbitrary fields even from a modified file."""
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw.get("schema_version") != 1:
        raise PayloadError("unsupported schema")
    updated = iso(timestamp(raw.get("updated_at")))
    rows = raw.get("providers")
    if not isinstance(rows, dict) or set(rows) != set(PROVIDERS):
        raise PayloadError("expected codex and claude")
    cleaned = {}
    for pid, name in PROVIDERS.items():
        p = rows[pid]
        if not isinstance(p, dict) or p.get("source") != "oauth" or p.get("status") not in ("ok", "error"):
            raise PayloadError("invalid provider")
        attempt = iso(timestamp(p.get("attempted_at")))
        sample = iso(timestamp(p["sampled_at"])) if p.get("sampled_at") else None
        success = iso(timestamp(p["last_success_at"])) if p.get("last_success_at") else None
        lanes = p.get("windows")
        if not isinstance(lanes, list) or len(lanes) > 3:
            raise PayloadError("invalid windows")
        windows = []
        for lane in lanes:
            if not isinstance(lane, dict) or lane.get("id") not in SLOTS:
                raise PayloadError("invalid window")
            windows.append(window(lane["id"], lane.get("used_percent"), lane.get("window_minutes"), lane.get("reset_at")))
        if len({w["id"] for w in windows}) != len(windows):
            raise PayloadError("duplicate windows")
        error = p.get("error_code")
        if p["status"] == "ok" and (not windows or not sample or not success or error is not None):
            raise PayloadError("invalid success")
        if p["status"] == "error" and (error not in ERRORS or (windows and (not sample or not success))):
            raise PayloadError("invalid failure")
        cleaned[pid] = {"name": name, "source": "oauth", "status": p["status"],
                        "attempted_at": attempt, "last_success_at": success,
                        "sampled_at": sample, "error_code": error, "windows": windows}
    return {"schema_version": 1, "updated_at": updated, "providers": cleaned}
