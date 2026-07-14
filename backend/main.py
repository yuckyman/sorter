from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
import sys
import os
import asyncio
import logging
import random
from pathlib import Path
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env.local"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))
from models import (
    ActionLiteral,
    ActionResponse,
    AssetFormatted,
    AssetInput,
    ExifInfo,
    StatsResponse,
    StatsState,
    default_action_counts,
    default_stats_state,
)
from immich_client import ImmichClient
from state_store import StateStore

log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

IMMICH_URL = os.getenv("IMMICH_URL")
IMMICH_API_KEY = os.getenv("IMMICH_API_KEY")

if not IMMICH_URL or not IMMICH_API_KEY:
    logger.error("Missing IMMICH_URL or IMMICH_API_KEY in .env.local")
    raise ValueError("Set IMMICH_URL and IMMICH_API_KEY in .env.local")

@asynccontextmanager
async def lifespan(app):
    logger.info("FastAPI application started")
    logger.info(f"Log file: {log_file}")
    async with stats_lock:
        state = _load_stats_no_lock()
        state["session"]["id"] = state["session"]["id"] + 1
        state["session"]["counts"] = default_action_counts()
        _write_stats_no_lock(state)
    logger.info(f"Session {state['session']['id']} started")
    yield
    logger.info("Shutting down, closing connections...")
    await immich.close()

app = FastAPI(lifespan=lifespan)
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

db_file = Path(__file__).parent.parent / "sorter.db"
state_store = StateStore(db_file)
stats_lock = asyncio.Lock()
feed_lock = asyncio.Lock()
COOLDOWN_DAYS = int(os.getenv("SORTER_SEEN_COOLDOWN_DAYS", "30"))

def _normalize_state(data: Any) -> StatsState:
    if not isinstance(data, dict):
        return default_stats_state()

    state = default_stats_state()
    lifetime = data.get("lifetime", {})
    session = data.get("session", {})
    daily = data.get("daily", {})

    for key in state["lifetime"]:
        if key in lifetime:
            state["lifetime"][key] = max(0, int(lifetime[key]))

    session_id = session.get("id", state["session"]["id"])
    state["session"]["id"] = max(0, int(session_id))

    session_counts = session.get("counts", {})
    for key in state["session"]["counts"]:
        if key in session_counts:
            state["session"]["counts"][key] = max(0, int(session_counts[key]))

    if isinstance(daily, dict):
        for day_key, day_val in daily.items():
            if not isinstance(day_key, str):
                continue
            if isinstance(day_val, dict):
                day_counts = default_action_counts()
                for key in day_counts:
                    if key in day_val:
                        day_counts[key] = max(0, int(day_val[key]))
                state["daily"][day_key] = day_counts

    return state

def _load_stats_no_lock() -> StatsState:
    try:
        data = state_store.get_state_json("stats")
        if data is None:
            return default_stats_state()
        return _normalize_state(data)
    except Exception as e:
        logger.warning(f"Failed to read stats from sqlite: {e}", exc_info=True)
        return default_stats_state()

def _write_stats_no_lock(state: StatsState) -> None:
    normalized = _normalize_state(state)
    state_store.set_state_json("stats", normalized)

async def read_stats() -> StatsResponse:
    async with stats_lock:
        state = _load_stats_no_lock()
        return {
            "session_id": state["session"]["id"],
            "session": state["session"]["counts"],
            "lifetime": state["lifetime"],
            "daily": state["daily"],
        }

async def update_stats(action: ActionLiteral, delta: int) -> StatsResponse:
    async with stats_lock:
        state = _load_stats_no_lock()
        if action in state["lifetime"]:
            state["lifetime"][action] = max(0, state["lifetime"][action] + delta)
        if action in state["session"]["counts"]:
            state["session"]["counts"][action] = max(0, state["session"]["counts"][action] + delta)
        day_key = datetime.now().strftime("%Y-%m-%d")
        day_counts = state["daily"].get(day_key)
        if not isinstance(day_counts, dict):
            day_counts = default_action_counts()
        if action in day_counts:
            day_counts[action] = max(0, day_counts[action] + delta)
        state["daily"][day_key] = day_counts
        _write_stats_no_lock(state)
        return {
            "session_id": state["session"]["id"],
            "session": state["session"]["counts"],
            "lifetime": state["lifetime"],
            "daily": state["daily"],
        }


@app.get("/", response_class=HTMLResponse)
async def root():
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
            height: 100vh;
            overflow: hidden;
            color: var(--text);
            font-size: 13px;
            line-height: 1.5;
        }
        
        .wrap {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }
        
        .header {
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        
        .title { color: var(--jade); }
        .title span { color: var(--text-dim); }
        
        .main {
            display: grid;
            grid-template-columns: 1fr 220px;
            gap: 20px;
            margin-bottom: 15px;
            flex: 1;
            min-height: 0;
        }
        
        .frame {
            position: relative;
            border: 1px solid var(--border);
            height: 100%;
            min-height: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--bg-light);
            overflow: hidden;
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

        .stats-panel {
            color: var(--text-dim);
            font-size: 11px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            min-width: 180px;
        }

        .stats-title {
            text-transform: uppercase;
            letter-spacing: 1px;
            font-size: 10px;
            color: var(--text-dim);
        }

        .stats-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .stats-item .value {
            color: var(--text-bright);
            margin-left: 4px;
        }

        .heatmap {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .heatmap-row {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .heatmap-label {
            width: 32px;
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-dim);
            display: inline-block;
            text-align: right;
        }

        .heatmap-bar {
            display: flex;
            gap: 2px;
        }

        .heatmap-cell {
            width: 8px;
            height: 8px;
            background: var(--jade-muted);
            border: 1px solid var(--border);
            opacity: 0.2;
        }

        .heatmap-row.delete .heatmap-cell { background: #5a3030; border-color: #4a2626; }
        
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
                <div class="stats-panel" id="statsLifetime">
                    <div class="stats-title">session <span id="sessionId">0</span></div>
                    <div class="stats-row">
                        <span class="stats-item">del <span class="value" id="statSessionDelete">0</span></span>
                        <span class="stats-item">keep <span class="value" id="statSessionKeep">0</span></span>
                        <span class="stats-item">fav <span class="value" id="statSessionFav">0</span></span>
                        <span class="stats-item">arch <span class="value" id="statSessionArchive">0</span></span>
                    </div>
                </div>
                <div class="stats-panel" id="statsLifetime">
                    <div class="stats-title">lifetime</div>
                    <div class="stats-row">
                        <span class="stats-item">del <span class="value" id="statLifetimeDelete">0</span></span>
                        <span class="stats-item">keep <span class="value" id="statLifetimeKeep">0</span></span>
                        <span class="stats-item">fav <span class="value" id="statLifetimeFav">0</span></span>
                        <span class="stats-item">arch <span class="value" id="statLifetimeArchive">0</span></span>
                    </div>
                    <div class="heatmap" id="heatmapLifetime"></div>
                </div>
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
        const ACTION_NAMES = { 'delete': 'del', 'keep': 'skip', 'fav': 'fav', 'archive': 'archive' };
        let currentId = null;
        let imageQueue = [];
        const TARGET_QUEUE_SIZE = 35;
        const QUEUE_REFILL_BATCH = 5;
        const QUEUE_REFILL_DELAY_MS = 1000;
        const THUMB_PRELOAD_LIMIT = 20;
        const QUEUE_REFILL_ERROR_DELAY_MS = 1800;
        const FULL_RES_PRELOAD_LIMIT = 1;
        let isPreloading = false;
        let preloadRetryTimer = null;
        let selectedCameras = [];
        let selectedSmartQuery = null;
        let queuedAssetIds = new Set();
        let preloadedFullRes = new Set();
        let statusTimer = null;
        let fadeTimer = null;
        let displayGeneration = 0;
        let stats = {
            session_id: 0,
            session: { delete: 0, keep: 0, fav: 0, archive: 0 },
            lifetime: { delete: 0, keep: 0, fav: 0, archive: 0 },
            daily: {}
        };
        
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

        const heatmapWindowDays = 28;

        function parseDateString(dateStr) {
            const [year, month, day] = dateStr.split('-').map(n => parseInt(n, 10));
            return new Date(year, (month || 1) - 1, day || 1);
        }

        function formatDateKey(dateObj) {
            const y = dateObj.getFullYear();
            const m = String(dateObj.getMonth() + 1).padStart(2, '0');
            const d = String(dateObj.getDate()).padStart(2, '0');
            return `${y}-${m}-${d}`;
        }

        function renderLifetimeHeatmap() {
            const container = document.getElementById('heatmapLifetime');
            if (!container) return;
            container.innerHTML = '';

            const daily = stats.daily || {};
            const today = new Date();
            const todayKey = formatDateKey(today);

            const allKeys = Object.keys(daily);
            const maxKey = allKeys.length > 0
                ? allKeys.reduce((a, b) => (a > b ? a : b))
                : todayKey;

            const maxDate = parseDateString(maxKey);
            const startDate = new Date(today);
            const defaultEnd = new Date(startDate);
            defaultEnd.setDate(defaultEnd.getDate() + heatmapWindowDays - 1);
            if (maxDate > defaultEnd) {
                const shiftedStart = new Date(maxDate);
                shiftedStart.setDate(maxDate.getDate() - (heatmapWindowDays - 1));
                startDate.setTime(shiftedStart.getTime());
            }

            const dates = [];
            for (let i = 0; i < heatmapWindowDays; i++) {
                const day = new Date(startDate);
                day.setDate(startDate.getDate() + i);
                dates.push(formatDateKey(day));
            }

            const keepValues = dates.map(key => (daily[key]?.keep || 0));
            const deleteValues = dates.map(key => (daily[key]?.delete || 0));
            const maxValue = Math.max(...keepValues, ...deleteValues, 1);

            const bands = [
                { key: 'keep', label: 'keep', className: 'keep' },
                { key: 'delete', label: 'del', className: 'delete' }
            ];

            bands.forEach(band => {
                const row = document.createElement('div');
                row.className = `heatmap-row ${band.className}`;

                const label = document.createElement('span');
                label.className = 'heatmap-label';
                label.textContent = band.label;

                const bar = document.createElement('div');
                bar.className = 'heatmap-bar';

                dates.forEach((key, idx) => {
                    const cell = document.createElement('span');
                    cell.className = 'heatmap-cell';
                    const value = daily[key]?.[band.key] || 0;
                    if (value > 0) {
                        const intensity = 0.2 + 0.8 * (value / maxValue);
                        cell.style.opacity = Math.min(1, intensity);
                    } else {
                        cell.style.opacity = 0.1;
                    }
                    if (idx === 0) {
                        cell.title = `${key} (start) ${band.label}: ${value}`;
                    } else if (idx === dates.length - 1) {
                        cell.title = `${key} (end) ${band.label}: ${value}`;
                    } else {
                        cell.title = `${key} ${band.label}: ${value}`;
                    }
                    bar.appendChild(cell);
                });

                row.appendChild(label);
                row.appendChild(bar);
                container.appendChild(row);
            });
        }

        function renderStats() {
            document.getElementById('sessionId').textContent = stats.session_id || 0;

            document.getElementById('statSessionDelete').textContent = stats.session.delete || 0;
            document.getElementById('statSessionKeep').textContent = stats.session.keep || 0;
            document.getElementById('statSessionFav').textContent = stats.session.fav || 0;
            document.getElementById('statSessionArchive').textContent = stats.session.archive || 0;

            document.getElementById('statLifetimeDelete').textContent = stats.lifetime.delete || 0;
            document.getElementById('statLifetimeKeep').textContent = stats.lifetime.keep || 0;
            document.getElementById('statLifetimeFav').textContent = stats.lifetime.fav || 0;
            document.getElementById('statLifetimeArchive').textContent = stats.lifetime.archive || 0;

            renderLifetimeHeatmap();
        }

        function updateStatsLocal(action, delta) {
            if (!stats || !stats.session || !stats.lifetime) return;
            if (action in stats.session) {
                stats.session[action] = Math.max(0, (stats.session[action] || 0) + delta);
            }
            if (action in stats.lifetime) {
                stats.lifetime[action] = Math.max(0, (stats.lifetime[action] || 0) + delta);
            }
            const todayKey = formatDateKey(new Date());
            stats.daily = stats.daily || {};
            const dayCounts = typeof stats.daily[todayKey] === 'object'
                ? stats.daily[todayKey]
                : { delete: 0, keep: 0, fav: 0, archive: 0 };
            if (action in dayCounts) {
                dayCounts[action] = Math.max(0, (dayCounts[action] || 0) + delta);
            }
            stats.daily[todayKey] = dayCounts;
            renderStats();
        }

        function applyServerStats(serverStats) {
            if (!serverStats) return;
            stats = {
                session_id: serverStats.session_id || stats.session_id || 0,
                session: serverStats.session || stats.session,
                lifetime: serverStats.lifetime || stats.lifetime,
                daily: serverStats.daily || stats.daily
            };
            renderStats();
        }

        async function fetchStats() {
            try {
                const r = await fetch('/stats');
                const data = await r.json();
                if (!data || data.error) return;
                applyServerStats(data);
            } catch (error) {
                showStatus(`Failed to load stats: ${error.message}`, 'error');
            }
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
        
        function preloadFullImage(url) {
            return new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => resolve(img);
                img.onerror = reject;
                img.src = url;
            });
        }
        
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
            
            document.getElementById('queueInfo').textContent = `queue: ${imageQueue.length}`;
        }
        
        function displayImage(asset) {
            const photo = document.getElementById('photo');
            const video = document.getElementById('video');
            const frame = document.getElementById('frame');
            
            const thisGeneration = ++displayGeneration;
            
            if (video && !video.paused) {
                video.pause();
                video.currentTime = 0;
            }
            
            photo.style.display = 'none';
            video.style.display = 'none';
            frame.classList.remove('loading');
            
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
                        if (thisGeneration === displayGeneration) {
                            photo.src = asset.image_url;
                            photo.style.opacity = '1';
                        }
                    })
                    .catch(() => console.warn('Failed to load full res'));
            }
        }
        
        async function loadCameras() {
            try {
                const r = await fetch('/cameras');
                const data = await r.json();
                
                if (data.error) {
                    showStatus(`Error loading cameras: ${data.error}`, 'error');
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
                showStatus(`Error loading cameras: ${error.message}`, 'error');
            }
        }
        
        function resetFeed() {
            imageQueue = [];
            queuedAssetIds.clear();
            preloadedFullRes.clear();
            currentId = null;
            currentAsset = null;
            lastAction = null;
            if (preloadRetryTimer) {
                clearTimeout(preloadRetryTimer);
                preloadRetryTimer = null;
            }
            loadNext();
        }

        function onSmartFilterChange() {
            selectedSmartQuery = document.getElementById('smartSelect').value || null;
            resetFeed();
        }
        
        function onCameraFilterChange() {
            selectedCameras = Array.from(document.getElementById('cameraSelect').selectedOptions)
                .map(opt => opt.value)
                .filter(v => v);
            resetFeed();
        }

        function buildNextUrl(count) {
            let url = `/next?count=${count}`;
            if (selectedSmartQuery) {
                url += `&smart_query=${encodeURIComponent(selectedSmartQuery)}`;
            } else if (selectedCameras.length > 0) {
                url += `&cameras=${encodeURIComponent(selectedCameras.join(','))}`;
            }
            return url;
        }

        function scheduleQueueRefill(delayMs = QUEUE_REFILL_DELAY_MS) {
            if (preloadRetryTimer) return;
            preloadRetryTimer = setTimeout(() => {
                preloadRetryTimer = null;
                preloadQueue();
            }, delayMs);
        }
        
        async function preloadQueue() {
            if (isPreloading || imageQueue.length >= TARGET_QUEUE_SIZE) return;
            
            isPreloading = true;
            try {
                const needed = Math.min(QUEUE_REFILL_BATCH, TARGET_QUEUE_SIZE - imageQueue.length);
                if (needed <= 0) return;

                const url = buildNextUrl(needed);
                const r = await fetch(url);
                const data = await r.json();
                
                if (data.error) {
                    showStatus(`Preload error: ${data.error}`, 'error');
                    scheduleQueueRefill(QUEUE_REFILL_ERROR_DELAY_MS);
                    return;
                }
                
                if (data.done) {
                    return;
                }
                
                const assets = data.assets || [data];
                let added = 0;
                for (const asset of assets) {
                    if (!asset || !asset.id || queuedAssetIds.has(asset.id) || currentId === asset.id) {
                        continue;
                    }
                    queuedAssetIds.add(asset.id);
                    added += 1;
                    
                    if (imageQueue.length < THUMB_PRELOAD_LIMIT) {
                        const thumbImg = new Image();
                        thumbImg.src = asset.thumb_url;
                    }
                    
                    if (asset.type !== 'VIDEO' && imageQueue.length <= FULL_RES_PRELOAD_LIMIT) {
                        if (!preloadedFullRes.has(asset.id)) {
                            preloadedFullRes.add(asset.id);
                            setTimeout(() => {
                                preloadFullImage(asset.image_url).catch(() => console.debug('Background full-res preload failed'));
                            }, 50 * imageQueue.length);
                        }
                    }
                    
                    imageQueue.push(asset);
                }
                
                if (imageQueue.length < TARGET_QUEUE_SIZE) {
                    if (added === 0) {
                        scheduleQueueRefill(QUEUE_REFILL_ERROR_DELAY_MS);
                    } else {
                        scheduleQueueRefill();
                    }
                }
            } catch (error) {
                showStatus(`Queue error: ${error.message}`, 'error');
                scheduleQueueRefill(QUEUE_REFILL_ERROR_DELAY_MS);
            } finally {
                isPreloading = false;
            }
        }
        
        async function loadNext() {
            preloadQueue();
            
            if (imageQueue.length > 0) {
                const asset = imageQueue.shift();
                queuedAssetIds.delete(asset.id);
                currentId = asset.id;
                currentAsset = asset;
                displayImage(asset);
                scheduleQueueRefill();
                return;
            }
            
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
            preloadedFullRes.clear();
            queuedAssetIds.clear();
            
            try {
                const neededNow = Math.max(QUEUE_REFILL_BATCH, 4);
                const url = buildNextUrl(neededNow);
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
                    queuedAssetIds.clear();
                    currentId = null;
                    currentAsset = null;
                    setLoading(false);
                    return;
                }
                
                const assets = data.assets || [data];
                if (!assets || assets.length === 0) {
                    setLoading(false);
                    return;
                }

                const first = assets[0];
                const rest = assets.slice(1);

                for (const asset of rest) {
                    if (!asset || !asset.id || queuedAssetIds.has(asset.id) || currentId === asset.id) continue;
                    queuedAssetIds.add(asset.id);
                    if (imageQueue.length < THUMB_PRELOAD_LIMIT) {
                        const thumbImg = new Image();
                        thumbImg.src = asset.thumb_url;
                    }
                    imageQueue.push(asset);
                }

                currentId = first.id;
                currentAsset = first;
                displayImage(first);

                scheduleQueueRefill();
            } catch (error) {
                showStatus(`Error: ${error.message}`, 'error');
                setLoading(false);
                scheduleQueueRefill(QUEUE_REFILL_ERROR_DELAY_MS);
            }
        }
        
        let lastAction = null;
        let currentAsset = null;
        
        function addHistoryEntry(action, asset) {
            const historyList = document.getElementById('historyList');
            const emptyMsg = historyList.querySelector('.history-empty');
            
            if (emptyMsg) {
                emptyMsg.remove();
            }
            
            const entry = document.createElement('div');
            entry.className = 'history-entry success';
            
            const now = new Date();
            const timeStr = now.toLocaleTimeString('en-US', { 
                hour12: false, 
                hour: '2-digit', 
                minute: '2-digit',
                second: '2-digit'
            });
            
            const actionLabel = ACTION_NAMES[action] || action;
            const filename = asset?.meta?.filename || asset?.id?.slice(0, 8) || 'unknown';
            
            entry.innerHTML = `
                <span class="history-text">${actionLabel}: ${filename}</span>
                <span class="history-time">${timeStr}</span>
            `;
            
            historyList.insertBefore(entry, historyList.firstChild);
            
            const entries = historyList.querySelectorAll('.history-entry');
            if (entries.length > 10) {
                entries[entries.length - 1].remove();
            }
        }
        
        async function sendAction(action) {
            if (!currentId || !currentAsset) return;
            
            lastAction = { 
                asset: currentAsset,
                action: action 
            };
            
            const actionLabel = ACTION_NAMES[action] || action;
            
            addHistoryEntry(action, currentAsset);

            updateStatsLocal(action, 1);
            
            (async () => {
                try {
                    const r = await fetch(`/action/${currentId}?action=${action}`, { method: 'POST' });
                    const data = await r.json();
                    if (!r.ok || data.error) {
                        updateStatsLocal(action, -1);
                        showStatus(`failed: ${data.error || `http ${r.status}`}`, 'error');
                        fetchStats();
                        return;
                    }
                    applyServerStats(data.stats);
                } catch (error) {
                    updateStatsLocal(action, -1);
                    showStatus(`Error: ${error.message}`, 'error');
                    fetchStats();
                }
            })();
            
            showStatus(`${actionLabel} [ctrl+z undo]`, 'success');
            
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
                    if (currentAsset) {
                        imageQueue.unshift(currentAsset);
                    }
                    
                    currentId = asset.id;
                    currentAsset = asset;
                    displayImage(asset);
                    
                    showStatus(`undone - vote again`, 'success');
                    lastAction = null;
                    updateStatsLocal(action, -1);
                    applyServerStats(data.stats);
                }
            } catch (error) {
                showStatus(`undo failed: ${error.message}`, 'error');
            }
        }
        
        document.addEventListener('keydown', e => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
                e.preventDefault();
                undoLast();
                return;
            }
            
            if (e.key === 'ArrowLeft') { e.preventDefault(); sendAction('delete'); }
            if (e.key === 'ArrowRight') { e.preventDefault(); sendAction('keep'); }
            if (e.key === 'ArrowUp') { e.preventDefault(); sendAction('fav'); }
            if (e.key === 'ArrowDown') { e.preventDefault(); sendAction('archive'); }
        });
        
        document.getElementById('smartSelect').addEventListener('change', onSmartFilterChange);
        document.getElementById('cameraSelect').addEventListener('change', onCameraFilterChange);
        
        loadNext();

        fetchStats();
        
        setTimeout(() => loadCameras(), 100);
    </script>
</body>
</html>
    """

@app.get("/favicon.ico")
async def favicon():
    favicon_path = Path(__file__).parent.parent / "frontend" / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    return {"error": "favicon not found"}, 404

@app.get("/cameras")
async def get_cameras():
    try:
        logger.info("Fetching camera models")
        cameras = await immich.get_camera_models()
        logger.info(f"Found {len(cameras)} unique camera models")
        return {"cameras": cameras}
    except Exception as e:
        logger.error(f"Error fetching cameras: {e}", exc_info=True)
        return {"error": str(e), "cameras": []}

@app.get("/stats")
async def get_stats():
    return await read_stats()

def _feed_key(cameras: str | None = None, smart_query: str | None = None) -> str:
    if smart_query:
        return f"smart:{smart_query.strip().lower()}"
    if cameras:
        normalized = ",".join(sorted(c.strip() for c in cameras.split(",") if c.strip()))
        return f"camera:{normalized}" if normalized else "all"
    return "all"

def _format_asset(asset: AssetInput) -> AssetFormatted:
    if not asset or not isinstance(asset, dict):
        logger.error(f"Invalid asset format: {type(asset)}, value: {asset}")
        raise ValueError(f"Invalid asset: expected dict, got {type(asset)}")
    if "id" not in asset:
        logger.error(f"Asset missing 'id' field. Available keys: {list(asset.keys())}")
        raise ValueError(f"Asset missing 'id' field. Available keys: {list(asset.keys())}")
    exif: ExifInfo = asset.get("exifInfo", {}) or {}  # type: ignore[assignment]
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
        },
    }

@app.get("/next")
async def next_image(count: int = 1, cameras: str | None = None, smart_query: str | None = None):
    try:
        requested = max(1, min(int(count), 24))
        camera_list = [c.strip() for c in cameras.split(",") if c.strip()] if cameras else []
        feed_key = _feed_key(cameras=cameras, smart_query=smart_query)
        selected_assets = []
        selected_ids = set()

        async with feed_lock:
            if smart_query:
                logger.info(f"Fetching {requested} asset(s) using smart search feed '{feed_key}'")
                filter_by_dims = smart_query.lower() == "screenshot"
                fetch_size = max(requested * 4, 24)
                candidates = await immich.search_smart(
                    query=smart_query,
                    limit=fetch_size,
                    filter_by_dimensions=filter_by_dims,
                )
                candidate_ids = [asset.get("id") for asset in candidates if isinstance(asset, dict) and asset.get("id")]
                unseen_ids = set(state_store.filter_unseen(candidate_ids, COOLDOWN_DAYS))
                random.shuffle(candidates)
                for asset in candidates:
                    asset_id = asset.get("id")
                    if asset_id in unseen_ids and asset_id not in selected_ids:
                        selected_assets.append(asset)
                        selected_ids.add(asset_id)
                    if len(selected_assets) >= requested:
                        break
            else:
                start_page = state_store.get_feed_cursor(feed_key)
                page = start_page
                max_page_fetches = 12
                target_pool = max(requested * 3, 24)
                candidate_pool = []

                for _ in range(max_page_fetches):
                    try:
                        page_assets = await immich.get_assets_page(
                            page=page,
                            size=100,
                            camera_models=camera_list or None,
                        )
                    except Exception as exc:
                        logger.warning(f"Deterministic paging failed for '{feed_key}' on page {page}: {exc}")
                        page_assets = []
                    page += 1
                    if not page_assets:
                        continue
                    candidate_pool.extend(page_assets)
                    if len(candidate_pool) >= target_pool:
                        break

                state_store.set_feed_cursor(feed_key, page)

                if not candidate_pool:
                    fallback_limit = max(requested * 2, 12)
                    if camera_list:
                        candidate_pool = await immich.get_unreviewed_filtered(limit=fallback_limit, camera_models=camera_list)
                    else:
                        candidate_pool = await immich.get_unreviewed(limit=fallback_limit)

                candidate_ids = [asset.get("id") for asset in candidate_pool if isinstance(asset, dict) and asset.get("id")]
                unseen_ids = set(state_store.filter_unseen(candidate_ids, COOLDOWN_DAYS))
                random.shuffle(candidate_pool)
                for asset in candidate_pool:
                    asset_id = asset.get("id")
                    if asset_id in unseen_ids and asset_id not in selected_ids:
                        selected_assets.append(asset)
                        selected_ids.add(asset_id)
                    if len(selected_assets) >= requested:
                        break

            if selected_assets:
                state_store.mark_seen([asset["id"] for asset in selected_assets if isinstance(asset, dict) and asset.get("id")])

        if not selected_assets:
            logger.info("No more assets available")
            return {"done": True}

        formatted_assets = [_format_asset(asset) for asset in selected_assets]
        asset_types = [a["type"] for a in formatted_assets]
        logger.info(f"Returning {len(formatted_assets)} asset(s): {asset_types}")
        
        if requested == 1:
            return formatted_assets[0]
        else:
            return {"assets": formatted_assets}
    except Exception as e:
        logger.error(f"Error fetching assets: {e}", exc_info=True)
        return {"error": str(e), "type": type(e).__name__}

@app.get("/proxy/{asset_id}/{size}")
async def proxy_image(asset_id: str, size: str, request: Request):
    logger.debug(f"Proxying {size} for asset {asset_id}")
    upstream_url = f"{immich.base}/assets/{asset_id}/{size}"
    request_headers = {}
    range_header = request.headers.get("range")
    if range_header:
        request_headers["range"] = range_header

    stream_context = None
    try:
        stream_context = immich.stream_with_retry(
            upstream_url,
            max_retries=1,
            headers=request_headers or None,
            media=True,
        )
        upstream = await stream_context.__aenter__()
        content_type = upstream.headers.get("content-type", "application/octet-stream")
        if size == "original" and "video" not in content_type.lower() and not content_type.startswith("image/"):
            content_type = "video/mp4"

        response_headers = {}
        passthrough_headers = ("accept-ranges", "content-range", "content-length", "etag", "last-modified", "cache-control")
        for key in passthrough_headers:
            value = upstream.headers.get(key)
            if value:
                response_headers[key] = value

        async def stream_body():
            try:
                async for chunk in upstream.aiter_bytes():
                    if chunk:
                        yield chunk
            finally:
                if stream_context is not None:
                    await stream_context.__aexit__(None, None, None)

        logger.debug(f"Streaming {size} for {asset_id}: {content_type}")
        return StreamingResponse(
            stream_body(),
            status_code=upstream.status_code,
            media_type=content_type,
            headers=response_headers,
        )
    except Exception as e:
        if stream_context is not None:
            await stream_context.__aexit__(type(e), e, e.__traceback__)
        logger.error(f"Error proxying {size} for {asset_id}: {e}", exc_info=True)
        raise

@app.post("/admin/seen/reset")
async def reset_seen_assets():
    state_store.clear_seen()
    return {"ok": True}

@app.post("/action/{asset_id}")
async def action(asset_id: str, action: ActionLiteral) -> ActionResponse:
    logger.info(f"Action '{action}' on asset {asset_id}")
    try:
        updated_stats = None
        if action == "delete":
            await immich.delete(asset_id)
            logger.info(f"Deleted asset {asset_id}")
            updated_stats = await update_stats(action, 1)
        elif action == "fav":
            await immich.mark_favorite(asset_id, True)
            logger.info(f"Favorited asset {asset_id}")
            updated_stats = await update_stats(action, 1)
        elif action == "archive":
            await immich.archive(asset_id, True)
            logger.info(f"Archived asset {asset_id}")
            updated_stats = await update_stats(action, 1)
        elif action == "keep":
            logger.info(f"Kept asset {asset_id}")
            updated_stats = await update_stats(action, 1)
        else:
            logger.warning(f"Unknown action: {action} for asset {asset_id}")
            return {"error": "unknown action"}
        return {"ok": True, "stats": updated_stats}
    except Exception as e:
        logger.error(f"Error performing action '{action}' on {asset_id}: {e}", exc_info=True)
        return {"error": str(e), "type": type(e).__name__}

@app.post("/undo/{asset_id}")
async def undo_action(asset_id: str, action: ActionLiteral) -> ActionResponse:
    logger.info(f"Undo '{action}' on asset {asset_id}")
    try:
        updated_stats = None
        if action == "delete":
            await immich.restore(asset_id)
            logger.info(f"Restored asset {asset_id} from trash")
            updated_stats = await update_stats(action, -1)
        elif action == "fav":
            await immich.mark_favorite(asset_id, False)
            logger.info(f"Unfavorited asset {asset_id}")
            updated_stats = await update_stats(action, -1)
        elif action == "archive":
            await immich.archive(asset_id, False)
            logger.info(f"Unarchived asset {asset_id}")
            updated_stats = await update_stats(action, -1)
        elif action == "keep":
            updated_stats = await update_stats(action, -1)
        else:
            return {"error": "unknown action"}
        return {"ok": True, "stats": updated_stats}
    except Exception as e:
        logger.error(f"Error undoing '{action}' on {asset_id}: {e}", exc_info=True)
        return {"error": str(e), "type": type(e).__name__}
