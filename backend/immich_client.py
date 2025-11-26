import httpx
import asyncio

class ImmichClient:
    def __init__(self, base_url, api_key):
        self.base = base_url.rstrip("/")
        self.headers = {"x-api-key": api_key}
        # Reuse single client with connection pooling for efficiency
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(60.0, connect=15.0),  # 60s total, 15s connect (increased for slow responses)
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),  # Reduced to avoid overwhelming server
        )
        self._camera_cache = None
        # Semaphore to limit concurrent requests (reduced to avoid overwhelming server)
        self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests
    
    async def get_with_retry(self, url, max_retries=2):
        """Get with retry logic and semaphore limiting"""
        for attempt in range(max_retries + 1):
            async with self._semaphore:
                try:
                    r = await self.client.get(url)
                    r.raise_for_status()
                    return r
                except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                    if attempt < max_retries:
                        wait_time = 0.5 * (2 ** attempt)  # Exponential backoff: 0.5s, 1s
                        await asyncio.sleep(wait_time)
                        continue
                    raise
                except Exception:
                    raise
    
    async def _request_with_retry(self, method, url, max_retries=1, **kwargs):
        """Generic request with retry logic for PUT/POST/DELETE"""
        for attempt in range(max_retries + 1):
            async with self._semaphore:
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
                except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                    if attempt < max_retries:
                        wait_time = 0.3 * (2 ** attempt)  # Shorter backoff for actions
                        await asyncio.sleep(wait_time)
                        continue
                    raise
                except Exception:
                    raise
    
    async def close(self):
        """Close the client connection pool"""
        await self.client.aclose()

    async def get_unreviewed(self, limit=1):
        # use the random endpoint which works with this Immich version
        # fetch multiple in parallel if limit > 1
        if limit == 1:
            r = await self.get_with_retry(f"{self.base}/assets/random")
            data = r.json()
            # random endpoint returns a single asset or list
            if isinstance(data, list):
                return data[:limit]
            else:
                return [data]  # wrap single asset in list
        else:
            # Fetch multiple random assets sequentially to avoid overwhelming server
            # Process one at a time with small delays
            assets = []
            seen_ids = set()
            
            for i in range(limit * 2):  # Try up to 2x limit to account for duplicates
                if len(assets) >= limit:
                    break
                
                try:
                    r = await self.get_with_retry(f"{self.base}/assets/random")
                    data = r.json()
                    asset = data if isinstance(data, dict) else data[0] if isinstance(data, list) else None
                    if asset and asset.get("id") not in seen_ids:
                        assets.append(asset)
                        seen_ids.add(asset["id"])
                except Exception:
                    # If we get an error, wait a bit before retrying
                    await asyncio.sleep(0.3)
                    continue
                
                # Small delay between requests
                if len(assets) < limit:
                    await asyncio.sleep(0.2)
            
            return assets[:limit]

    async def mark_favorite(self, asset_id, favorite=True):
        r = await self._request_with_retry(
            "PUT",
            f"{self.base}/assets",
            json={"ids": [asset_id], "isFavorite": favorite},
        )
        return r.json()

    async def archive(self, asset_id, archived=True):
        r = await self._request_with_retry(
            "PUT",
            f"{self.base}/assets",
            json={"ids": [asset_id], "isArchived": archived},
        )
        return r.json()

    async def delete(self, asset_id):
        r = await self._request_with_retry(
            "DELETE",
            f"{self.base}/assets",
            json={"ids": [asset_id]},
        )
        return r.json()

    async def restore(self, asset_id):
        """Restore asset from trash"""
        r = await self._request_with_retry(
            "POST",
            f"{self.base}/trash/restore/assets",
            json={"ids": [asset_id]},
        )
        return r.json()

    async def get_camera_models(self, sample_size=8):
        """Get unique camera models by sampling assets (cached, lazy-loaded)"""
        if self._camera_cache is not None:
            return self._camera_cache
        
        # Very conservative: process one at a time with delays
        total_samples = min(sample_size, 8)
        cameras = set()
        
        for i in range(total_samples):
            try:
                r = await self.get_with_retry(f"{self.base}/assets/random")
                data = r.json()
                asset = data if isinstance(data, dict) else data[0] if isinstance(data, list) else None
                if asset:
                    exif = asset.get("exifInfo", {}) or {}
                    camera = exif.get("model")
                    if camera and camera != "--":
                        cameras.add(camera)
            except Exception:
                # If we hit errors, stop early rather than continuing
                break
            
            # Delay between each request
            if i < total_samples - 1:
                await asyncio.sleep(0.3)
        
        self._camera_cache = sorted(list(cameras))
        return self._camera_cache

    async def get_unreviewed_filtered(self, limit=1, camera_models=None):
        """Get unreviewed assets, optionally filtered by camera models"""
        if not camera_models or len(camera_models) == 0:
            return await self.get_unreviewed(limit=limit)
        
        # Fetch sequentially one at a time to avoid overwhelming server
        max_attempts = limit * 10  # Try up to 10x limit attempts
        matching_assets = []
        seen_ids = set()
        attempts = 0
        
        while len(matching_assets) < limit and attempts < max_attempts:
            attempts += 1
            try:
                r = await self.get_with_retry(f"{self.base}/assets/random")
                data = r.json()
                asset = data if isinstance(data, dict) else data[0] if isinstance(data, list) else None
                
                if asset and asset.get("id") not in seen_ids:
                    seen_ids.add(asset.get("id"))
                    exif = asset.get("exifInfo", {}) or {}
                    camera = exif.get("model") or "--"
                    
                    if camera in camera_models:
                        matching_assets.append(asset)
            except Exception:
                # On error, wait a bit before retrying
                await asyncio.sleep(0.3)
                continue
            
            # Delay between requests
            if len(matching_assets) < limit:
                await asyncio.sleep(0.25)
        
        return matching_assets[:limit]
