"""Helpers for flow step multi-media asset IDs (JSON list + legacy single id)."""

from __future__ import annotations

import json
from typing import Any

MAX_MEDIA_PER_STEP = 50


def normalize_media_ids(ids: list[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in ids or []:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= MAX_MEDIA_PER_STEP:
            break
    return out


def parse_media_asset_ids(raw: str | list[Any] | None, legacy_id: str | None = None) -> list[str]:
    """Effective ordered ids: media_asset_ids if non-empty, else [media_asset_id] if set."""
    ids: list[str] = []
    if isinstance(raw, list):
        ids = normalize_media_ids(raw)
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                ids = normalize_media_ids(parsed)
        except (json.JSONDecodeError, TypeError, ValueError):
            ids = []
    if ids:
        return ids
    if legacy_id and str(legacy_id).strip():
        return [str(legacy_id).strip()]
    return []


def dump_media_asset_ids(ids: list[Any] | None) -> str | None:
    cleaned = normalize_media_ids(ids)
    if not cleaned:
        return None
    return json.dumps(cleaned)


def apply_media_fields(
    step: Any,
    *,
    media_asset_id: str | None = None,
    media_asset_ids: list[Any] | None = None,
    ids_provided: bool = False,
    id_provided: bool = False,
) -> None:
    """Write media_asset_ids JSON + legacy media_asset_id (first item) onto a FlowStep."""
    if ids_provided:
        ids = normalize_media_ids(media_asset_ids)
    elif id_provided:
        ids = [str(media_asset_id).strip()] if media_asset_id and str(media_asset_id).strip() else []
    else:
        return
    step.media_asset_ids = dump_media_asset_ids(ids)
    step.media_asset_id = ids[0] if ids else None
