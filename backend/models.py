from __future__ import annotations

from enum import Enum
from typing import Any, Literal, TypedDict


class ActionType(str, Enum):
    DELETE = "delete"
    KEEP = "keep"
    FAV = "fav"
    ARCHIVE = "archive"


ACTION_TYPES: tuple[str, ...] = tuple(t.value for t in ActionType)
ActionLiteral = Literal["delete", "keep", "fav", "archive"]


class ActionCounts(TypedDict):
    delete: int
    keep: int
    fav: int
    archive: int


class SessionState(TypedDict):
    id: int
    counts: ActionCounts


class StatsState(TypedDict):
    lifetime: ActionCounts
    session: SessionState
    daily: dict[str, ActionCounts]


class StatsResponse(TypedDict):
    session_id: int
    session: ActionCounts
    lifetime: ActionCounts
    daily: dict[str, ActionCounts]


def default_action_counts() -> ActionCounts:
    return {"delete": 0, "keep": 0, "fav": 0, "archive": 0}


def default_stats_state() -> StatsState:
    return {
        "lifetime": default_action_counts(),
        "session": {"id": 0, "counts": default_action_counts()},
        "daily": {},
    }


class ExifInfo(TypedDict, total=False):
    model: str
    lensModel: str
    iso: int | str
    fNumber: float
    exposureTime: str
    focalLength: float
    exifImageWidth: int
    exifImageHeight: int
    fileSizeInByte: int
    city: str
    state: str
    country: str


class AssetInput(TypedDict, total=False):
    """Raw asset dict as returned by the Immich API."""
    id: str
    type: str
    duration: str
    originalFileName: str
    fileCreatedAt: str
    exifInfo: ExifInfo


class AssetMeta(TypedDict):
    filename: str
    date: str
    time: str
    size: str
    dims: str
    camera: str
    lens: str
    iso: str
    aperture: str
    shutter: str
    focal: str
    location: str


class AssetFormatted(TypedDict):
    """Formatted asset sent to the frontend."""
    id: str
    type: str
    duration: str
    thumb_url: str
    image_url: str
    video_url: str | None
    meta: AssetMeta


class NextAssetsResponse(TypedDict):
    assets: list[AssetFormatted]


class DoneResponse(TypedDict):
    done: bool


class ErrorResponse(TypedDict):
    error: str


class ActionResponse(TypedDict, total=False):
    ok: bool
    stats: StatsResponse
    error: str


class CamerasResponse(TypedDict):
    cameras: list[str]
