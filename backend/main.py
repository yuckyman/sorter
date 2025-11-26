from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import sys
import os
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env.local
env_path = Path(__file__).parent.parent / ".env.local"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))
from immich_client import ImmichClient

# Setup logging
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f"app_{datetime.now().strftime("%Y%m%d")}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load config from environment
IMMICH_URL = os.getenv("IMMICH_URL")
IMMICH_API_KEY = os.getenv("IMMICH_API_KEY")

if not IMMICH_URL or not IMMICH_API_KEY:
    logger.error("Missing IMMICH_URL or IMMICH_API_KEY in .env.local")
    raise ValueError("Set IMMICH_URL and IMMICH_API_KEY in .env.local")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger.info("Starting Immich Photo Sorter application")
immich = ImmichClient(IMMICH_URL, IMMICH_API_KEY)
logger.info(f"Connected to Immich at {immich.base}")

@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI application started")
    logger.info(f"Log file: {log_dir / f'app_{datetime.now().strftime("%Y%m%d")}.log'}")

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main app interface"""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>sorter</title>
    <style>
        :root {
            --jade: #3a7d6e;
            --jade-dim: #2a5d4e;
            --jade-bright: #4a9d8e;
            --jade-muted: #1a3d2e;
            --bg: #0a0f0d;
            --bg-light: #0f1512;
            --border: #1a2d26;
            --text: #5a7d6e;
            --text-dim: #3a5d4e;
            --text-bright: #8aad9e;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace;
            background: var(--bg);
            min-height: 100vh;
            color: var(--text);
            font-size: 13px;
            line-height: 1.5;
        }
        
        .wrap {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .title { color: var(--jade); }
        .title span { color: var(--text-dim); }
        
        .main {
            display: grid;
            grid-template-columns: 1fr 200px;
            gap: 20px;
            margin-bottom: 15px;
        }
        
        .frame {
            position: relative;
            border: 1px solid var(--border);
            min-height: 55vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--bg-light);
        }
        
        .frame.loading::after {
            content: '. . .';
            color: var(--text-dim);
            letter-spacing: 4px;
        }
        
        #photo, #video {
            max-width: 100%;
            max-height: 55vh;
            object-fit: contain;
        }
        
        #video { background: #000; }
        
        .sidebar {
            border: 1px solid var(--border);
            background: var(--bg-light);
            padding: 15px;
            font-size: 11px;
        }
        
        .sidebar h3 {
            color: var(--jade);
            font-weight: normal;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }
        
        .meta-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid var(--border);
        }
        
        .meta-row:last-child { border-bottom: none; }
        
        .meta-label { color: var(--text-dim); }
        .meta-value { color: var(--text-bright); text-align: right; }
        
        .type-badge {
            display: inline-block;
            padding: 2px 6px;
            background: var(--jade-muted);
            color: var(--jade-bright);
            font-size: 10px;
            margin-top: 10px;
        }
        
        .controls {
            display: flex;
            justify-content: center;
            gap: 40px;
            padding: 15px 0;
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
            margin-bottom: 12px;
        }
        
        .ctrl {
            color: var(--text-dim);
            cursor: pointer;
            transition: color 0.1s;
            user-select: none;
        }
        
        .ctrl:hover { color: var(--jade-bright); }
        .ctrl.del:hover { color: #8a5a5a; }
        .ctrl.fav:hover { color: #9a8a5a; }
        
        .ctrl .key { color: var(--jade-dim); }
        
        .status-bar {
            color: var(--text-dim);
            font-size: 11px;
            min-height: 16px;
        }
        
        .status-bar.ok { color: var(--jade); }
        .status-bar.err { color: #8a5a5a; }
        
        .empty {
            color: var(--text-dim);
            text-align: center;
            padding: 40px;
        }
        
        .queue-ct {
            color: var(--text-dim);
            font-size: 11px;
        }
        
        .header-controls {
            display: flex;
            gap: 20px;
            align-items: center;
        }
        
        .camera-filter {
            position: relative;
        }
        
        .camera-filter label {
            color: var(--text-dim);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-right: 8px;
        }
        
        .camera-filter select {
            background: var(--bg-light);
            border: 1px solid var(--border);
            color: var(--text);
            font-family: inherit;
            font-size: 11px;
            padding: 4px 8px;
            min-width: 200px;
            max-width: 300px;
            cursor: pointer;
            max-height: 120px;
        }
        
        .camera-filter select:focus {
            outline: none;
            border-color: var(--jade);
        }
        
        .camera-filter select option {
            background: var(--bg-light);
            color: var(--text);
            padding: 4px;
        }
        
        .camera-filter select option:checked {
            background: var(--jade-muted);
            color: var(--jade-bright);
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="header">
            <div class="title">sorter <span>// immich</span></div>
            <div class="header-controls">
                <div class="camera-filter">
                    <label for="cameraSelect">camera:</label>
                    <select id="cameraSelect" multiple size="4" title="hold ctrl/cmd to select multiple">
                        <option value="">loading...</option>
                    </select>
                </div>
                <div class="queue-ct" id="queueInfo">queue: 0</div>
            </div>
        </div>
        
        <div class="main">
            <div class="frame loading" id="frame">
                <div class="empty" id="empty" style="display:none;">-- queue empty --</div>
                <img id="photo" style="display:none;" />
                <video id="video" style="display:none;" controls muted></video>
            </div>
            
            <div class="sidebar">
                <h3>metadata</h3>
                <div class="meta-row"><span class="meta-label">date</span><span class="meta-value" id="metaDate">--</span></div>
                <div class="meta-row"><span class="meta-label">time</span><span class="meta-value" id="metaTime">--</span></div>
                <div class="meta-row"><span class="meta-label">size</span><span class="meta-value" id="metaSize">--</span></div>
                <div class="meta-row"><span class="meta-label">dims</span><span class="meta-value" id="metaDims">--</span></div>
                <div class="meta-row"><span class="meta-label">camera</span><span class="meta-value" id="metaCamera">--</span></div>
                <div class="meta-row"><span class="meta-label">lens</span><span class="meta-value" id="metaLens">--</span></div>
                <div class="meta-row"><span class="meta-label">iso</span><span class="meta-value" id="metaIso">--</span></div>
                <div class="meta-row"><span class="meta-label">f/</span><span class="meta-value" id="metaAperture">--</span></div>
                <div class="meta-row"><span class="meta-label">shutter</span><span class="meta-value" id="metaShutter">--</span></div>
                <div class="meta-row"><span class="meta-label">focal</span><span class="meta-value" id="metaFocal">--</span></div>
                <div class="meta-row"><span class="meta-label">location</span><span class="meta-value" id="metaLocation">--</span></div>
                <div class="type-badge" id="typeBadge">IMAGE</div>
            </div>
        </div>
        
        <div class="controls">
            <span class="ctrl del" onclick="sendAction('delete')"><span class="key">[←]</span> del</span>
            <span class="ctrl" onclick="sendAction('keep')"><span class="key">[→]</span> skip</span>
            <span class="ctrl fav" onclick="sendAction('fav')"><span class="key">[↑]</span> fav</span>
            <span class="ctrl" onclick="sendAction('archive')"><span class="key">[↓]</span> archive</span>
        </div>
        
        <div class="status-bar" id="status"></div>
    </div>
    
    <script>
        let currentId = null;
        let imageQueue = []; // Queue of preloaded images
        const QUEUE_SIZE = 3; // Preload 3 images ahead
        let isPreloading = false;
        let selectedCameras = []; // Selected camera models for filtering
        
        function showStatus(message, type = 'info') {
            const status = document.getElementById('status');
            status.textContent = `> ${message}`;
            status.className = `status-bar ${type === 'success' ? 'ok' : type === 'error' ? 'err' : ''}`;
            setTimeout(() => { status.textContent = ''; }, 2000);
        }
        
        function setLoading(loading) {
            const frame = document.getElementById('frame');
            const empty = document.getElementById('empty');
            
            if (loading && imageQueue.length === 0) {
                frame.classList.add('loading');
                empty.style.display = 'none';
            } else {
                frame.classList.remove('loading');
            }
        }
        
        // Preload full resolution image in background
        function preloadFullImage(url) {
            return new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => resolve(img);
                img.onerror = reject;
                img.src = url;
            });
        }
        
        // Update metadata sidebar
        function updateMeta(asset) {
            const m = asset.meta || {};
            document.getElementById('metaDate').textContent = m.date || '--';
            document.getElementById('metaTime').textContent = m.time || '--';
            document.getElementById('metaSize').textContent = m.size || '--';
            document.getElementById('metaDims').textContent = m.dims || '--';
            document.getElementById('metaCamera').textContent = m.camera || '--';
            document.getElementById('metaLens').textContent = m.lens || '--';
            document.getElementById('metaIso').textContent = m.iso || '--';
            document.getElementById('metaAperture').textContent = m.aperture || '--';
            document.getElementById('metaShutter').textContent = m.shutter || '--';
            document.getElementById('metaFocal').textContent = m.focal || '--';
            document.getElementById('metaLocation').textContent = m.location || '--';
            
            // Update type badge
            let typeText = asset.type || 'IMAGE';
            if (asset.type === 'VIDEO' && asset.duration) {
                let dur = asset.duration;
                if (dur.includes(':')) {
                    const parts = dur.split(':');
                    if (parts.length === 3) {
                        const mins = parseInt(parts[1]) || 0;
                        const secs = Math.floor(parseFloat(parts[2]) || 0);
                        dur = `${mins}:${secs.toString().padStart(2, '0')}`;
                    }
                }
                typeText = `VIDEO ${dur}`;
            }
            document.getElementById('typeBadge').textContent = typeText;
            
            // Update queue counter
            document.getElementById('queueInfo').textContent = `queue: ${imageQueue.length}`;
        }
        
        // Load image or video with progressive enhancement
        function displayImage(asset) {
            const photo = document.getElementById('photo');
            const video = document.getElementById('video');
            const frame = document.getElementById('frame');
            
            // Pause and reset video if playing
            if (video && !video.paused) {
                video.pause();
                video.currentTime = 0;
            }
            
            // Hide both
            photo.style.display = 'none';
            video.style.display = 'none';
            frame.classList.remove('loading');
            
            // Update metadata
            updateMeta(asset);
            
            if (asset.type === 'VIDEO') {
                video.poster = asset.thumb_url;
                video.src = asset.video_url || asset.image_url;
                video.style.display = 'block';
                video.load();
            } else {
                photo.src = asset.thumb_url;
                photo.style.display = 'block';
                photo.style.opacity = '0.6';
                
                preloadFullImage(asset.image_url)
                    .then(() => {
                        photo.src = asset.image_url;
                        photo.style.opacity = '1';
                    })
                    .catch(() => console.warn('Failed to load full res'));
            }
        }
        
        // Load available camera models
        async function loadCameras() {
            try {
                const r = await fetch('/cameras');
                const data = await r.json();
                
                if (data.error) {
                    console.error('Error loading cameras:', data.error);
                    return;
                }
                
                const select = document.getElementById('cameraSelect');
                select.innerHTML = '<option value="">all cameras</option>';
                
                if (data.cameras && data.cameras.length > 0) {
                    data.cameras.forEach(camera => {
                        const option = document.createElement('option');
                        option.value = camera;
                        option.textContent = camera;
                        select.appendChild(option);
                    });
                } else {
                    select.innerHTML = '<option value="">no cameras found</option>';
                }
            } catch (error) {
                console.error('Error loading cameras:', error);
            }
        }
        
        // Handle camera filter change
        function onCameraFilterChange() {
            const select = document.getElementById('cameraSelect');
            selectedCameras = Array.from(select.selectedOptions)
                .map(opt => opt.value)
                .filter(v => v); // Remove empty values
            
            // Clear queue and reload when filter changes
            imageQueue = [];
            currentId = null;
            loadNext();
        }
        
        // Preload next batch of images into queue
        async function preloadQueue() {
            if (isPreloading || imageQueue.length >= QUEUE_SIZE) return;
            
            isPreloading = true;
            try {
                let url = `/next?count=${QUEUE_SIZE}`;
                if (selectedCameras.length > 0) {
                    url += `&cameras=${encodeURIComponent(selectedCameras.join(','))}`;
                }
                const r = await fetch(url);
                const data = await r.json();
                
                if (data.error) {
                    console.error('Preload error:', data.error);
                    isPreloading = false;
                    return;
                }
                
                if (data.done) {
                    isPreloading = false;
                    return;
                }
                
                // Add to queue and preload images
                const assets = data.assets || [data];
                for (const asset of assets) {
                    // Preload thumbnail immediately
                    const thumbImg = new Image();
                    thumbImg.src = asset.thumb_url;
                    
                    // Preload full resolution in background
                    preloadFullImage(asset.image_url).catch(() => {});
                    
                    imageQueue.push(asset);
                }
            } catch (error) {
                console.error('Queue preload error:', error);
            } finally {
                isPreloading = false;
            }
        }
        
        // Get next image from queue or fetch if empty
        async function loadNext() {
            // If queue has images, use them immediately (instant switch)
            if (imageQueue.length > 0) {
                const asset = imageQueue.shift();
                currentId = asset.id;
                displayImage(asset);
                
                // Trigger background preload for more images
                preloadQueue();
                return;
            }
            
            // Queue empty - clear current image before fetching
            const photo = document.getElementById('photo');
            const video = document.getElementById('video');
            photo.style.display = 'none';
            if (video && !video.paused) {
                video.pause();
                video.currentTime = 0;
            }
            video.style.display = 'none';
            document.getElementById('queueInfo').textContent = 'queue: 0';
            setLoading(true);
            
            try {
                let url = '/next';
                if (selectedCameras.length > 0) {
                    url += `?cameras=${encodeURIComponent(selectedCameras.join(','))}`;
                }
                const r = await fetch(url);
                const data = await r.json();
                
                if (data.error) {
                    showStatus(`Error: ${data.error}`, 'error');
                    setLoading(false);
                    return;
                }
                
                if (data.done) {
                    document.getElementById('empty').style.display = 'block';
                    document.getElementById('photo').style.display = 'none';
                    document.getElementById('video').style.display = 'none';
                    currentId = null;
                    setLoading(false);
                    return;
                }
                
                currentId = data.id;
                displayImage(data);
                
                // Start preloading queue for next images
                preloadQueue();
            } catch (error) {
                showStatus(`Error: ${error.message}`, 'error');
                setLoading(false);
            }
        }
        
        // Undo stack
        let lastAction = null;
        
        async function sendAction(action) {
            if (!currentId) return;
            
            const actionNames = {
                'delete': 'del',
                'keep': 'skip',
                'fav': 'fav',
                'archive': 'archive'
            };
            
            // Store for undo
            lastAction = { id: currentId, action: action };
            
            // Send action in background, don't wait
            fetch(`/action/${currentId}?action=${action}`, {
                method: 'POST'
            }).catch(error => {
                console.error('Action error:', error);
                showStatus(`Error: ${error.message}`, 'error');
            });
            
            showStatus(`${actionNames[action]} [ctrl+z undo]`, 'success');
            
            // Immediately load next (should be instant from queue)
            loadNext();
        }
        
        async function undoLast() {
            if (!lastAction) {
                showStatus('nothing to undo', 'info');
                return;
            }
            
            const { id, action } = lastAction;
            showStatus(`undoing ${action}...`, 'info');
            
            try {
                const r = await fetch(`/undo/${id}?action=${action}`, { method: 'POST' });
                const data = await r.json();
                
                if (data.error) {
                    showStatus(`undo failed: ${data.error}`, 'error');
                } else {
                    showStatus(`undone`, 'success');
                    lastAction = null;
                }
            } catch (error) {
                showStatus(`undo failed: ${error.message}`, 'error');
            }
        }
        
        document.addEventListener('keydown', e => {
            // Undo: ctrl+z or cmd+z
            if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
                e.preventDefault();
                undoLast();
                return;
            }
            
            if (e.key === 'ArrowLeft') sendAction('delete');
            if (e.key === 'ArrowRight') sendAction('keep');
            if (e.key === 'ArrowUp') sendAction('fav');
            if (e.key === 'ArrowDown') sendAction('archive');
        });
        
        // Initialize: load cameras and first image
        loadCameras();
        document.getElementById('cameraSelect').addEventListener('change', onCameraFilterChange);
        
        // Load first image and start preloading queue
        loadNext();
        preloadQueue();
    </script>
</body>
</html>
    """

@app.get("/cameras")
async def get_cameras():
    """Get list of available camera models"""
    try:
        logger.info("Fetching camera models")
        cameras = await immich.get_camera_models()
        logger.info(f"Found {len(cameras)} unique camera models")
        return {"cameras": cameras}
    except Exception as e:
        logger.error(f"Error fetching cameras: {e}", exc_info=True)
        return {"error": str(e), "cameras": []}

@app.get("/next")
async def next_image(count: int = 1, cameras: str = None):
    """Get next image(s) - supports batch loading for queue and camera filtering"""
    try:
        camera_list = None
        if cameras:
            camera_list = [c.strip() for c in cameras.split(",") if c.strip()]
            logger.info(f"Fetching {count} asset(s) filtered by cameras: {camera_list}")
        else:
            logger.info(f"Fetching {count} asset(s) from Immich")
        
        if camera_list:
            assets = await immich.get_unreviewed_filtered(limit=count, camera_models=camera_list)
        else:
            assets = await immich.get_unreviewed(limit=count)
        
        if not assets or len(assets) == 0:
            logger.info("No more assets available")
            return {"done": True}
        
        # Always return consistent format with metadata
        def format_asset(asset):
            exif = asset.get("exifInfo", {}) or {}
            return {
                "id": asset["id"],
                "type": asset.get("type", "IMAGE"),
                "duration": asset.get("duration", "0:00:00.00000"),
                "thumb_url": f"/proxy/{asset['id']}/thumbnail",
                "image_url": f"/proxy/{asset['id']}/original",
                "video_url": f"/proxy/{asset['id']}/original" if asset.get("type") == "VIDEO" else None,
                "meta": {
                    "filename": asset.get("originalFileName", "--"),
                    "date": asset.get("fileCreatedAt", "")[:10] if asset.get("fileCreatedAt") else "--",
                    "time": asset.get("fileCreatedAt", "")[11:16] if asset.get("fileCreatedAt") else "--",
                    "size": f"{(exif.get('fileSizeInByte', 0) or 0) / 1024 / 1024:.1f} MB" if exif.get('fileSizeInByte') else "--",
                    "dims": f"{exif.get('exifImageWidth', '--')}x{exif.get('exifImageHeight', '--')}" if exif.get('exifImageWidth') else "--",
                    "camera": exif.get("model", "--") or "--",
                    "lens": exif.get("lensModel", "--") or "--",
                    "iso": str(exif.get("iso", "--")) if exif.get("iso") else "--",
                    "aperture": str(exif.get("fNumber", "--")) if exif.get("fNumber") else "--",
                    "shutter": exif.get("exposureTime", "--") or "--",
                    "focal": f"{exif.get('focalLength', '--')}mm" if exif.get("focalLength") else "--",
                    "location": exif.get("city", "") or exif.get("state", "") or exif.get("country", "") or "--",
                }
            }
        
        formatted_assets = [format_asset(asset) for asset in assets]
        
        asset_types = [a["type"] for a in formatted_assets]
        logger.info(f"Returning {len(formatted_assets)} asset(s): {asset_types}")
        
        if count == 1:
            # For single requests, return the asset directly (backward compatible)
            return formatted_assets[0]
        else:
            # For batch requests, return array
            return {"assets": formatted_assets}
    except Exception as e:
        logger.error(f"Error fetching assets: {e}", exc_info=True)
        return {"error": str(e), "type": type(e).__name__}

@app.get("/proxy/{asset_id}/{size}")
async def proxy_image(asset_id: str, size: str):
    """Proxy images/videos through backend to add API key authentication"""
    import httpx
    logger.debug(f"Proxying {size} for asset {asset_id}")
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{immich.base}/assets/{asset_id}/{size}",
                headers=immich.headers,
                timeout=30.0,
            )
            r.raise_for_status()
            from fastapi.responses import Response
            
            # Determine content type from response headers or size parameter
            content_type = r.headers.get("content-type", "image/jpeg")
            content_length = len(r.content)
            if size == "original":
                # For original, check if it might be a video
                # Immich typically serves videos with video/* content type
                if "video" in content_type.lower():
                    content_type = content_type
                elif not content_type.startswith("image/"):
                    # Fallback: check file extension or assume video for large files
                    content_type = "video/mp4"  # Common video format
            
            logger.debug(f"Serving {size} for {asset_id}: {content_type}, {content_length} bytes")
            return Response(content=r.content, media_type=content_type)
    except Exception as e:
        logger.error(f"Error proxying {size} for {asset_id}: {e}", exc_info=True)
        raise

@app.post("/action/{asset_id}")
async def action(asset_id: str, action: str):
    logger.info(f"Action '{action}' on asset {asset_id}")
    try:
        if action == "delete":
            await immich.delete(asset_id)
            logger.info(f"Deleted asset {asset_id}")
        elif action == "fav":
            await immich.mark_favorite(asset_id, True)
            logger.info(f"Favorited asset {asset_id}")
        elif action == "archive":
            await immich.archive(asset_id, True)
            logger.info(f"Archived asset {asset_id}")
        elif action == "keep":
            # keep does nothing, just moves to next
            logger.info(f"Kept asset {asset_id}")
            pass
        else:
            logger.warning(f"Unknown action: {action} for asset {asset_id}")
            return {"error": "unknown action"}
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error performing action '{action}' on {asset_id}: {e}", exc_info=True)
        return {"error": str(e), "type": type(e).__name__}

@app.post("/undo/{asset_id}")
async def undo_action(asset_id: str, action: str):
    """Undo a previous action"""
    logger.info(f"Undo '{action}' on asset {asset_id}")
    try:
        if action == "delete":
            await immich.restore(asset_id)
            logger.info(f"Restored asset {asset_id} from trash")
        elif action == "fav":
            await immich.mark_favorite(asset_id, False)
            logger.info(f"Unfavorited asset {asset_id}")
        elif action == "archive":
            await immich.archive(asset_id, False)
            logger.info(f"Unarchived asset {asset_id}")
        elif action == "keep":
            # nothing to undo
            pass
        else:
            return {"error": "unknown action"}
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error undoing '{action}' on {asset_id}: {e}", exc_info=True)
        return {"error": str(e), "type": type(e).__name__}