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

    def _is_screenshot_dimension(self, width, height):
        """Check if dimensions match common screenshot resolutions"""
        if not width or not height:
            return False
        
        # Common iPhone screenshot dimensions (portrait)
        iphone_screenshots = [
            (1170, 2532),   # iPhone 13/14 Pro
            (1284, 2778),   # iPhone 14 Pro Max
            (1179, 2556),   # iPhone 15/16 Pro
            (1290, 2796),   # iPhone 15/16 Pro Max
            (750, 1334),    # iPhone SE
            (1242, 2688),   # iPhone XS Max
            (828, 1792),    # iPhone XR
        ]
        
        # Check exact match or swapped (landscape screenshots)
        for w, h in iphone_screenshots:
            if (width == w and height == h) or (width == h and height == w):
                return True
        
        # Check aspect ratio (most iPhone screenshots are ~19.5:9 or 16:9)
        aspect = width / height if height > 0 else 0
        if 0.4 <= aspect <= 0.6:  # Portrait screenshots (tall)
            return True
        if 1.6 <= aspect <= 1.8:  # Landscape screenshots (wide)
            return True
        
        return False
    
    async def search_smart(self, query: str, limit: int = 1, filter_by_dimensions: bool = False):
        """Search assets using Immich's smart search (CLIP-based semantic search)"""
        import logging
        logger = logging.getLogger(__name__)
        
        # Improve query terms for better CLIP model understanding
        query_map = {
            "screenshot": "screenshot of phone screen mobile device",
            "selfie": "selfie portrait photo person face front camera",
            "portrait": "portrait photo person face",
            "landscape": "landscape scenery nature outdoor view",
            "document": "document text paper scan"
        }
        
        # Use improved query if available, otherwise use original
        improved_query = query_map.get(query.lower(), query)
        logger.info(f"Smart search query: '{query}' -> '{improved_query}'")
        
        try:
            # Use the searchSmart endpoint with POST and a body
            # Try /search/smart first, fall back to /search-smart if needed
            search_urls = [
                f"{self.base}/search/smart",
                f"{self.base}/search-smart"
            ]
            
            # Request more results if we need to filter by dimensions
            request_size = limit * 5 if filter_by_dimensions else limit
            
            body = {
                "query": improved_query,
                "size": request_size,
                "isArchived": False,
                "isTrashed": False
            }
            
            last_error = None
            for search_url in search_urls:
                try:
                    logger.info(f"Smart search request: {search_url} with query: {query}")
                    r = await self._request_with_retry("POST", search_url, max_retries=2, json=body)
                    data = r.json()
                    
                    logger.info(f"Smart search response type: {type(data)}, keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
                    
                    # searchSmart returns a dict with items array or count/items structure
                    if isinstance(data, dict):
                        if "items" in data:
                            items = data["items"]
                            logger.info(f"Found {len(items)} items in response")
                            if len(items) == 0:
                                logger.info("Smart search returned empty items array")
                                return []
                            
                            # Log first item structure for debugging
                            if items and len(items) > 0:
                                first_item = items[0]
                                logger.info(f"First item type: {type(first_item)}, keys: {list(first_item.keys()) if isinstance(first_item, dict) else 'not a dict'}")
                            
                            # Ensure items are valid assets with id field
                            valid_items = []
                            for item in items:
                                if isinstance(item, dict):
                                    # Check for id in various possible locations
                                    asset_id = item.get("id") or item.get("assetId")
                                    if not asset_id:
                                        logger.warning(f"Item missing id field, keys: {list(item.keys())}")
                                        continue
                                    
                                    # If filtering by dimensions (for screenshots), check dimensions
                                    if filter_by_dimensions and query.lower() == "screenshot":
                                        exif = item.get("exifInfo", {}) or {}
                                        width = exif.get("exifImageWidth")
                                        height = exif.get("exifImageHeight")
                                        
                                        if width and height:
                                            if self._is_screenshot_dimension(width, height):
                                                valid_items.append(item)
                                                logger.info(f"Found screenshot match: {width}x{height}")
                                            else:
                                                logger.debug(f"Skipping non-screenshot dimensions: {width}x{height}")
                                        else:
                                            # If no EXIF, include it anyway (might be a screenshot)
                                            valid_items.append(item)
                                    else:
                                        # No dimension filtering, include all valid items
                                        valid_items.append(item)
                                    
                                    # Stop when we have enough
                                    if len(valid_items) >= limit:
                                        break
                                else:
                                    logger.warning(f"Item is not a dict: {type(item)}")
                            
                            if valid_items:
                                logger.info(f"Returning {len(valid_items)} valid assets from smart search (filtered from {len(items)} items)")
                                return valid_items[:limit]
                            else:
                                logger.warning("No valid assets found in items array")
                        elif "id" in data:
                            # Single asset returned as dict
                            logger.info("Single asset returned from smart search")
                            return [data]
                        elif "count" in data:
                            count = data.get("count", 0)
                            logger.info(f"Smart search returned count: {count}")
                            if count == 0:
                                return []
                    
                    if isinstance(data, list):
                        # Direct list of assets
                        valid_items = [item for item in data[:limit] if isinstance(item, dict) and "id" in item]
                        if valid_items:
                            logger.info(f"Returning {len(valid_items)} valid assets from list response")
                            return valid_items
                    
                    # If we got here, the response format is unexpected
                    logger.warning(f"Smart search returned unexpected format: {data}")
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f"Smart search failed for {search_url}: {e}")
                    continue
            
            # If all attempts failed, log and fall back
            if last_error:
                logger.error(f"Smart search failed with error: {last_error}")
            else:
                logger.warning(f"Smart search returned unexpected format, falling back to random")
            return await self.get_unreviewed(limit=limit)
        except Exception as e:
            logger.error(f"Smart search error: {e}", exc_info=True)
            # If smart search fails, fall back to random
            # This handles cases where smart search isn't available or query fails
            return await self.get_unreviewed(limit=limit)
