from __future__ import annotations

import httpx
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from models import AssetInput


class ImmichClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base = base_url.rstrip("/")
        self.root = self.base.removesuffix("/api") if self.base.endswith("/api") else self.base
        self.headers = {"x-api-key": api_key}
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
        self._camera_cache: list[str] | None = None
        # Separate lanes so proxy streaming does not starve metadata requests.
        self._metadata_semaphore = asyncio.Semaphore(3)
        self._media_semaphore = asyncio.Semaphore(2)

    def _semaphore_for(self, media: bool = False) -> asyncio.Semaphore:
        return self._media_semaphore if media else self._metadata_semaphore

    async def get_with_retry(
        self,
        url: str,
        max_retries: int = 2,
        headers: dict[str, str] | None = None,
        media: bool = False,
    ) -> httpx.Response:
        for attempt in range(max_retries + 1):
            async with self._semaphore_for(media=media):
                try:
                    r = await self.client.get(url, headers=headers)
                    r.raise_for_status()
                    return r
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError):
                    if attempt < max_retries:
                        wait_time = 0.5 * (2 ** attempt)
                        await asyncio.sleep(wait_time)
                        continue
                    raise

    @asynccontextmanager
    async def stream_with_retry(
        self,
        url: str,
        max_retries: int = 1,
        headers: dict[str, str] | None = None,
        media: bool = False,
    ):
        for attempt in range(max_retries + 1):
            semaphore = self._semaphore_for(media=media)
            await semaphore.acquire()
            try:
                async with self.client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    yield response
                    return
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError):
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                raise
            finally:
                semaphore.release()

    async def _request_with_retry(
        self, method: str, url: str, max_retries: int = 1, **kwargs: Any
    ) -> httpx.Response:
        for attempt in range(max_retries + 1):
            async with self._metadata_semaphore:
                try:
                    if method == "PUT":
                        r = await self.client.put(url, **kwargs)
                    elif method == "POST":
                        r = await self.client.post(url, **kwargs)
                    elif method == "DELETE":
                        r = await self.client.request("DELETE", url, **kwargs)
                    else:
                        r = await self.client.request(method, url, **kwargs)
                    r.raise_for_status()
                    return r
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError):
                    if attempt < max_retries:
                        wait_time = 0.3 * (2 ** attempt)
                        await asyncio.sleep(wait_time)
                        continue
                    raise

    def _extract_assets(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict) and item.get("id")]
        if isinstance(data, dict):
            for key in ("assets", "items", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict) and item.get("id")]
                if isinstance(value, dict):
                    inner = value.get("items")
                    if isinstance(inner, list):
                        return [item for item in inner if isinstance(item, dict) and item.get("id")]
            if data.get("id"):
                return [data]
        return []

    async def get_assets_page(
        self,
        page: int = 1,
        size: int = 120,
        camera_models: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        safe_page = max(1, int(page))
        safe_size = max(1, min(int(size), 250))
        camera_set = set(camera_models or [])

        payload = {
            "page": safe_page,
            "size": safe_size,
            "order": "desc",
            "isTrashed": False,
            "isArchived": False,
        }

        response = await self._request_with_retry(
            "POST",
            f"{self.base}/search/metadata",
            max_retries=1,
            json=payload,
        )
        assets = self._extract_assets(response.json())
        if camera_set:
            assets = [
                a for a in assets
                if ((a.get("exifInfo", {}) or {}).get("model") or "--") in camera_set
            ]
        return assets

    async def close(self) -> None:
        await self.client.aclose()

    def _safe_json(self, response: httpx.Response) -> dict[str, Any]:
        content = response.content or b""
        if not content:
            return {}
        try:
            return response.json()
        except Exception:
            return {}

    async def _search_random(self, size: int = 1, model: str | None = None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"size": size, "isTrashed": False, "isArchived": False, "withExif": True}
        if model:
            body["model"] = model
        r = await self._request_with_retry("POST", f"{self.base}/search/random", max_retries=1, json=body)
        data = r.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict) and item.get("id")]
        return []

    async def get_unreviewed(self, limit: int = 1) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        max_attempts = 3
        batch_size = max(limit * 2, 10)

        for _ in range(max_attempts):
            try:
                batch = await self._search_random(size=batch_size)
            except Exception:
                continue
            for item in batch:
                aid = item.get("id")
                if aid and aid not in seen_ids:
                    seen_ids.add(aid)
                    assets.append(item)
            if len(assets) >= limit:
                break

        return assets[:limit]

    async def mark_favorite(self, asset_id: str, favorite: bool = True) -> dict[str, Any]:
        r = await self._request_with_retry(
            "PUT",
            f"{self.base}/assets",
            json={"ids": [asset_id], "isFavorite": favorite},
        )
        return self._safe_json(r)

    async def archive(self, asset_id: str, archived: bool = True) -> dict[str, Any]:
        r = await self._request_with_retry(
            "PUT",
            f"{self.base}/assets",
            json={"ids": [asset_id], "isArchived": archived},
        )
        return self._safe_json(r)

    async def delete(self, asset_id: str) -> dict[str, Any]:
        r = await self._request_with_retry(
            "DELETE",
            f"{self.base}/assets",
            json={"ids": [asset_id]},
        )
        return self._safe_json(r)

    async def restore(self, asset_id: str) -> dict[str, Any]:
        r = await self._request_with_retry(
            "POST",
            f"{self.base}/trash/restore/assets",
            json={"ids": [asset_id]},
        )
        return self._safe_json(r)

    async def get_camera_models(self, sample_size: int = 8) -> list[str]:
        if self._camera_cache is not None:
            return self._camera_cache

        cameras: set[str] = set()

        async def fetch_camera() -> str | None:
            try:
                results = await self._search_random(size=1)
                asset = results[0] if results else None
                if asset:
                    exif = asset.get("exifInfo", {}) or {}
                    camera = exif.get("model")
                    if camera and camera != "--":
                        return camera
            except Exception:
                pass
            return None

        tasks = [fetch_camera() for _ in range(min(sample_size, 8))]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if result and not isinstance(result, Exception):
                cameras.add(result)

        self._camera_cache = sorted(cameras)
        return self._camera_cache

    async def get_unreviewed_filtered(
        self, limit: int = 1, camera_models: list[str] | None = None
    ) -> list[dict[str, Any]]:
        if not camera_models:
            return await self.get_unreviewed(limit=limit)

        camera_set = set(camera_models)
        matching_assets: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        max_attempts = 3
        batch_size = max(limit * 5, 20)

        for _ in range(max_attempts):
            try:
                for model in camera_set:
                    batch = await self._search_random(size=batch_size, model=model)
                    for item in batch:
                        aid = item.get("id")
                        if aid and aid not in seen_ids:
                            seen_ids.add(aid)
                            camera = (item.get("exifInfo", {}) or {}).get("model") or "--"
                            if camera in camera_set:
                                matching_assets.append(item)
                    if len(matching_assets) >= limit:
                        break
            except Exception:
                continue
            if len(matching_assets) >= limit:
                break

        return matching_assets[:limit]

    def _is_screenshot_dimension(self, width: int, height: int) -> bool:
        if not width or not height:
            return False

        iphone_screenshots = [
            (1170, 2532),
            (1284, 2778),
            (1179, 2556),
            (1290, 2796),
            (750, 1334),
            (1242, 2688),
            (828, 1792),
        ]

        for w, h in iphone_screenshots:
            if (width == w and height == h) or (width == h and height == w):
                return True

        aspect = width / height if height > 0 else 0
        if 0.4 <= aspect <= 0.6:
            return True
        if 1.6 <= aspect <= 1.8:
            return True

        return False

    async def search_smart(
        self, query: str, limit: int = 1, filter_by_dimensions: bool = False
    ) -> list[dict[str, Any]]:
        logger = logging.getLogger(__name__)

        query_map = {
            "screenshot": "screenshot of phone screen mobile device",
            "selfie": "selfie portrait photo person face front camera",
            "portrait": "portrait photo person face",
            "landscape": "landscape scenery nature outdoor view",
            "document": "document text paper scan",
        }

        improved_query = query_map.get(query.lower(), query)
        request_size = limit * 5 if filter_by_dimensions else limit

        body = {
            "query": improved_query,
            "size": request_size,
            "isArchived": False,
            "isTrashed": False,
        }

        try:
            r = await self._request_with_retry("POST", f"{self.base}/search/smart", max_retries=2, json=body)
            data = r.json()

            if isinstance(data, dict) and "items" in data:
                items = data["items"]
                if not items:
                    return []

                valid_items: list[dict[str, Any]] = []
                for item in items:
                    if not isinstance(item, dict) or not (item.get("id") or item.get("assetId")):
                        continue

                    if filter_by_dimensions and query.lower() == "screenshot":
                        exif = item.get("exifInfo", {}) or {}
                        width = exif.get("exifImageWidth")
                        height = exif.get("exifImageHeight")
                        if width and height and not self._is_screenshot_dimension(width, height):
                            continue

                    valid_items.append(item)
                    if len(valid_items) >= limit:
                        break

                return valid_items[:limit]

            if isinstance(data, dict) and "id" in data:
                return [data]

            if isinstance(data, list):
                return [item for item in data[:limit] if isinstance(item, dict) and "id" in item]

            return []
        except Exception as e:
            logger.warning(f"Smart search failed: {e}")
            return []
