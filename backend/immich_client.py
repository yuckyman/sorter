import httpx
import asyncio

class ImmichClient:
    def __init__(self, base_url, api_key):
        self.base = base_url.rstrip("/")
        self.headers = {"x-api-key": api_key}

    async def get_unreviewed(self, limit=1):
        # use the random endpoint which works with this Immich version
        # fetch multiple in parallel if limit > 1
        if limit == 1:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{self.base}/assets/random",
                    headers=self.headers,
                    timeout=10.0,
                )
            r.raise_for_status()
            data = r.json()
            # random endpoint returns a single asset or list
            if isinstance(data, list):
                return data[:limit]
            else:
                return [data]  # wrap single asset in list
        else:
            # Fetch multiple random assets in parallel
            async with httpx.AsyncClient() as client:
                tasks = [
                    client.get(
                        f"{self.base}/assets/random",
                        headers=self.headers,
                        timeout=10.0,
                    )
                    for _ in range(limit)
                ]
                responses = await asyncio.gather(*tasks)
            
            assets = []
            seen_ids = set()
            for r in responses:
                r.raise_for_status()
                data = r.json()
                asset = data if isinstance(data, dict) else data[0] if isinstance(data, list) else None
                if asset and asset.get("id") not in seen_ids:
                    assets.append(asset)
                    seen_ids.add(asset["id"])
            
            return assets

    async def mark_favorite(self, asset_id, favorite=True):
        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"{self.base}/assets",
                json={"ids": [asset_id], "isFavorite": favorite},
                headers=self.headers,
            )
        return r.json()

    async def archive(self, asset_id, archived=True):
        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"{self.base}/assets",
                json={"ids": [asset_id], "isArchived": archived},
                headers=self.headers,
            )
        return r.json()

    async def delete(self, asset_id):
        async with httpx.AsyncClient() as client:
            r = await client.request(
                "DELETE",
                f"{self.base}/assets",
                json={"ids": [asset_id]},
                headers=self.headers,
            )
        return r.json()

    async def restore(self, asset_id):
        """Restore asset from trash"""
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base}/trash/restore/assets",
                json={"ids": [asset_id]},
                headers=self.headers,
            )
        return r.json()

    async def get_camera_models(self, sample_size=100):
        """Get unique camera models by sampling assets"""
        async with httpx.AsyncClient() as client:
            # Fetch a sample of assets to discover camera models
            tasks = [
                client.get(
                    f"{self.base}/assets/random",
                    headers=self.headers,
                    timeout=10.0,
                )
                for _ in range(min(sample_size, 100))
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        cameras = set()
        for r in responses:
            if isinstance(r, Exception):
                continue
            try:
                r.raise_for_status()
                data = r.json()
                asset = data if isinstance(data, dict) else data[0] if isinstance(data, list) else None
                if asset:
                    exif = asset.get("exifInfo", {}) or {}
                    camera = exif.get("model")
                    if camera and camera != "--":
                        cameras.add(camera)
            except:
                continue
        
        return sorted(list(cameras))

    async def get_unreviewed_filtered(self, limit=1, camera_models=None):
        """Get unreviewed assets, optionally filtered by camera models"""
        if not camera_models or len(camera_models) == 0:
            return await self.get_unreviewed(limit=limit)
        
        # Filter by fetching random assets until we get matching cameras
        max_attempts = limit * 20  # reasonable limit to avoid infinite loops
        attempts = 0
        matching_assets = []
        seen_ids = set()
        
        async with httpx.AsyncClient() as client:
            while len(matching_assets) < limit and attempts < max_attempts:
                attempts += 1
                try:
                    r = await client.get(
                        f"{self.base}/assets/random",
                        headers=self.headers,
                        timeout=10.0,
                    )
                    r.raise_for_status()
                    data = r.json()
                    asset = data if isinstance(data, dict) else data[0] if isinstance(data, list) else None
                    
                    if asset and asset.get("id") not in seen_ids:
                        seen_ids.add(asset.get("id"))
                        exif = asset.get("exifInfo", {}) or {}
                        camera = exif.get("model") or "--"
                        
                        if camera in camera_models:
                            matching_assets.append(asset)
                except:
                    continue
        
        return matching_assets[:limit]
