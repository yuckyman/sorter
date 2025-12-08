from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
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
log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
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
    logger.info(f"Log file: {log_file}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down, closing connections...")
    await immich.close()

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
    <link rel="icon" type="image/x-icon" href="/favicon.ico" />
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
            grid-template-columns: 1fr 220px;
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
            width: 100%;
            height: auto;
            max-height: 65vh;
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
            transition: opacity 0.3s ease;
        }
        
        .status-bar.ok { color: var(--jade); }
        .status-bar.err { color: #8a5a5a; }
        .status-bar.fading {
            animation: statusFade 1.2s steps(8, end) forwards;
        }
        
        @keyframes statusFade {
            0% { opacity: 1; }
            40% { opacity: 0.9; }
            60% { opacity: 0.6; }
            80% { opacity: 0.3; }
            100% { opacity: 0; }
        }
        
        .history {
            margin-top: 10px;
            border: 1px solid var(--border);
            background: var(--bg-light);
            padding: 12px;
            font-size: 11px;
        }
        
        .history h3 {
            color: var(--jade);
            font-weight: normal;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }
        
        .history-list {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        
        .history-entry {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 4px 6px;
            border: 1px dashed var(--border);
            color: var(--text-dim);
            font-family: inherit;
        }
        
        .history-entry.success { color: var(--jade); border-color: var(--jade-dim); }
        .history-entry.error { color: #8a5a5a; border-color: #8a5a5a33; }
        
        .history-time { font-size: 10px; color: var(--text-dim); }
        .history-text { font-size: 11px; color: var(--text-bright); }
        .history-empty { color: var(--text-dim); font-style: italic; }
        
        @media (max-width: 768px) {
            .wrap {
                padding: 12px 12px 24px;
            }
            
            .header {
                flex-direction: column;
                align-items: flex-start;
                gap: 6px;
            }
            
            .main {
                display: block;
            }
            
            .frame {
                min-height: 60vh;
                margin-bottom: 18px;
            }
            
            .sidebar {
                margin-top: 18px;
            }
            
            .controls {
                flex-wrap: wrap;
                gap: 16px;
                position: sticky;
                bottom: 0;
                background: var(--bg-light);
                padding: 18px 12px;
                z-index: 5;
            }
            
            .ctrl {
                flex: 1 1 calc(50% - 16px);
                border: 1px solid var(--border);
                padding: 12px 0;
                text-align: center;
                border-radius: 4px;
            }
            
            #photo, #video {
                max-height: calc(100vh - 220px);
            }
        }
        
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
        
        .smart-filter {
            position: relative;
        }
        
        .smart-filter label {
            color: var(--text-dim);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-right: 8px;
        }
        
        .smart-filter select {
            background: var(--bg-light);
            border: 1px solid var(--border);
            color: var(--text);
            font-family: inherit;
            font-size: 11px;
            padding: 4px 8px;
            min-width: 150px;
            max-width: 200px;
            cursor: pointer;
        }
        
        .smart-filter select:focus {
            outline: none;
            border-color: var(--jade);
        }
        
        .smart-filter select option {
            background: var(--bg-light);
            color: var(--text);
            padding: 4px;
        }
        
        .smart-filter select option:checked {
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
                <div class="smart-filter">
                    <label for="smartSelect">type:</label>
                    <select id="smartSelect" title="filter by image type">
                        <option value="">all</option>
                        <option value="screenshot">screenshot</option>
                        <option value="selfie">selfie</option>
                        <option value="portrait">portrait</option>
                        <option value="landscape">landscape</option>
                        <option value="document">document</option>
                    </select>
                </div>
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
        
        <div class="history">
            <h3>history</h3>
            <div class="history-list" id="historyList">
                <div class="history-empty">no decisions yet</div>
            </div>
        </div>
    </div>
    
    <script>
        let currentId = null;
        let imageQueue = []; // Queue of preloaded images
        const QUEUE_SIZE = 3; // Preload 3 images ahead
        let isPreloading = false;
        let selectedCameras = []; // Selected camera models for filtering
        let selectedSmartQuery = null; // Selected smart search query (screenshot, selfie, etc.)
        let seenAssetIds = new Set(); // Track seen assets to prevent duplicates
        let statusTimer = null;
        let fadeTimer = null;
        
        function showStatus(message, type = 'info') {
            const status = document.getElementById('status');
            
            if (statusTimer) clearTimeout(statusTimer);
            if (fadeTimer) clearTimeout(fadeTimer);
            
            status.className = 'status-bar';
            status.classList.remove('ok', 'err', 'fading');
            if (type === 'success') status.classList.add('ok');
            if (type === 'error') status.classList.add('err');
            
            status.textContent = `> ${message}`;
            status.style.opacity = '1';
            
            statusTimer = setTimeout(() => {
                status.classList.add('fading');
                fadeTimer = setTimeout(() => {
                    status.textContent = '';
                    status.className = 'status-bar';
                }, 1200);
            }, 5000);
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
        
        // Handle smart filter change
        function onSmartFilterChange() {
            const select = document.getElementById('smartSelect');
            selectedSmartQuery = select.value || null;
            
            // Clear queue and seen IDs when filter changes
            imageQueue = [];
            seenAssetIds.clear();
            currentId = null;
            currentAsset = null;
            lastAction = null;  // Clear undo history too
            loadNext();
        }
        
        // Handle camera filter change
        function onCameraFilterChange() {
            const select = document.getElementById('cameraSelect');
            selectedCameras = Array.from(select.selectedOptions)
                .map(opt => opt.value)
                .filter(v => v); // Remove empty values
            
            // Clear queue and seen IDs when filter changes
            imageQueue = [];
            seenAssetIds.clear();
            currentId = null;
            currentAsset = null;
            lastAction = null;  // Clear undo history too
            loadNext();
        }
        
        // Preload next batch of images into queue
        async function preloadQueue() {
            if (isPreloading || imageQueue.length >= QUEUE_SIZE) return;
            
            isPreloading = true;
            try {
                let url = `/next?count=${QUEUE_SIZE}`;
                if (selectedSmartQuery) {
                    url += `&smart_query=${encodeURIComponent(selectedSmartQuery)}`;
                } else if (selectedCameras.length > 0) {
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
                
                // Add to queue and preload images (deduplicate)
                const assets = data.assets || [data];
                for (const asset of assets) {
                    // Skip if we've already seen this asset
                    if (seenAssetIds.has(asset.id)) {
                        continue;
                    }
                    seenAssetIds.add(asset.id);
                    
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
                currentAsset = asset;  // Store for undo
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
                const params = [];
                if (selectedSmartQuery) {
                    params.push(`smart_query=${encodeURIComponent(selectedSmartQuery)}`);
                } else if (selectedCameras.length > 0) {
                    params.push(`cameras=${encodeURIComponent(selectedCameras.join(','))}`);
                }
                if (params.length > 0) {
                    url += '?' + params.join('&');
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
                    currentAsset = null;
                    setLoading(false);
                    return;
                }
                
                // Track seen asset
                if (!seenAssetIds.has(data.id)) {
                    seenAssetIds.add(data.id);
                }
                
                currentId = data.id;
                currentAsset = data;  // Store for undo
                displayImage(data);
                
                // Start preloading queue for next images
                preloadQueue();
            } catch (error) {
                showStatus(`Error: ${error.message}`, 'error');
                setLoading(false);
            }
        }
        
        // Undo stack - stores full asset data for restoration
        let lastAction = null;
        let currentAsset = null;  // Store current asset for undo
        
        async function sendAction(action) {
            if (!currentId || !currentAsset) return;
            
            const actionNames = {
                'delete': 'del',
                'keep': 'skip',
                'fav': 'fav',
                'archive': 'archive'
            };
            
            // Store full asset data for undo (so we can restore the UI)
            lastAction = { 
                asset: currentAsset,
                action: action 
            };
            
            const actionLabel = actionNames[action] || action;
            
            // Send action in background, don't wait
            fetch(`/action/${currentId}?action=${action}`, {
                method: 'POST'
            }).catch(error => {
                console.error('Action error:', error);
                showStatus(`Error: ${error.message}`, 'error');
            });
            
            showStatus(`${actionLabel} [ctrl+z undo]`, 'success');
            
            // Immediately load next (should be instant from queue)
            loadNext();
        }
        
        async function undoLast() {
            if (!lastAction) {
                showStatus('nothing to undo', 'info');
                return;
            }
            
            const { asset, action } = lastAction;
            showStatus(`undoing ${action}...`, 'info');
            
            try {
                const r = await fetch(`/undo/${asset.id}?action=${action}`, { method: 'POST' });
                const data = await r.json();
                
                if (data.error) {
                    showStatus(`undo failed: ${data.error}`, 'error');
                } else {
                    // Put current image back into queue front
                    if (currentAsset) {
                        imageQueue.unshift(currentAsset);
                    }
                    
                    // Restore the undone asset to the UI
                    currentId = asset.id;
                    currentAsset = asset;
                    displayImage(asset);
                    
                    showStatus(`undone - vote again`, 'success');
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
        
        // Initialize: load first image immediately, cameras in background
        document.getElementById('smartSelect').addEventListener('change', onSmartFilterChange);
        document.getElementById('cameraSelect').addEventListener('change', onCameraFilterChange);
        
        // Load first image immediately (don't wait for cameras)
        loadNext();
        
        // Load cameras in background (non-blocking)
        setTimeout(() => loadCameras(), 100);
    </script>
</body>
</html>
    """

@app.get("/favicon.ico")
async def favicon():
    """Serve favicon"""
    favicon_path = Path(__file__).parent.parent / "frontend" / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    return {"error": "favicon not found"}, 404

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

@app.get("/smart-search-status")
async def smart_search_status():
    """Check if smart search is available and working"""
    try:
        logger.info("Checking smart search availability")
        # Try a simple test query
        test_results = await immich.search_smart(query="test", limit=1, filter_by_dimensions=False)
        return {
            "available": True,
            "working": len(test_results) >= 0,  # Even empty results means it's working
            "message": "Smart search is available"
        }
    except Exception as e:
        logger.warning(f"Smart search check failed: {e}")
        return {
            "available": False,
            "working": False,
            "error": str(e),
            "message": "Smart search may not be available or configured"
        }

@app.get("/next")
async def next_image(count: int = 1, cameras: str = None, smart_query: str = None):
    """Get next image(s) - supports batch loading for queue, camera filtering, and smart search"""
    try:
        # Smart search takes priority if provided
        if smart_query:
            logger.info(f"Fetching {count} asset(s) using smart search: '{smart_query}'")
            # Use dimension filtering for screenshots to improve accuracy
            filter_by_dims = smart_query.lower() == "screenshot"
            assets = await immich.search_smart(query=smart_query, limit=count, filter_by_dimensions=filter_by_dims)
        else:
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
        
        # Log first asset structure for debugging
        if assets and len(assets) > 0:
            logger.info(f"First asset keys: {list(assets[0].keys()) if isinstance(assets[0], dict) else 'not a dict'}")
            logger.info(f"First asset sample: {str(assets[0])[:200] if isinstance(assets[0], dict) else assets[0]}")
        
        # Always return consistent format with metadata
        def format_asset(asset):
            if not asset or not isinstance(asset, dict):
                logger.error(f"Invalid asset format: {type(asset)}, value: {asset}")
                raise ValueError(f"Invalid asset: expected dict, got {type(asset)}")
            
            if "id" not in asset:
                logger.error(f"Asset missing 'id' field. Available keys: {list(asset.keys())}")
                logger.error(f"Asset content: {asset}")
                raise ValueError(f"Asset missing 'id' field. Available keys: {list(asset.keys())}")
            
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
    logger.debug(f"Proxying {size} for asset {asset_id}")
    try:
        # Use retry logic for proxy requests too
        r = await immich.get_with_retry(f"{immich.base}/assets/{asset_id}/{size}", max_retries=1)
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