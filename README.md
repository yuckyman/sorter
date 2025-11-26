# sorter

minimal photo/video review tool for immich.

## features

- **lazy queue** — preloads images ahead, instant switching
- **progressive loading** — thumbnail first, full res in background
- **video support** — inline playback with duration badge
- **metadata sidebar** — date, size, dims, camera, lens, exif data, location
- **camera filter** — multi-select dropdown to filter by camera model
- **logging** — track all actions and api calls
- **ascii-minimal ui** — jade green monochrome terminal aesthetic

## setup

```bash
pip install -r requirements.txt
```

copy `.env.example` to `.env.local` and add your credentials:
```bash
cp .env.example .env.local
```

```env
IMMICH_URL=http://your-immich-host:2283/api
IMMICH_API_KEY=your-api-key-here
```

run:
```bash
uvicorn backend.main:app --reload --port 8050
```

open `http://localhost:8050`

## controls

```
[←]        del      delete asset
[→]        skip     keep, move to next
[↑]        fav      mark as favorite
[↓]        archive  archive asset
[ctrl+z]   undo     undo last action, restore image to UI
```

**undo feature**: pressing `ctrl+z` reverses your last action (restores from trash, unfavorites, unarchives) and brings the previous image back to the screen so you can vote again.

## camera filter

use the camera dropdown in the header to filter assets by camera model:
- select multiple cameras (hold ctrl/cmd while clicking)
- select "all cameras" to clear filter
- queue resets when filter changes
- camera list loads lazily in background (non-blocking)

## logs

```bash
./monitor.sh
# or
tail -f logs/app_$(date +%Y%m%d).log
```

logs include: api requests, user actions, errors, asset types.

## deploy (systemd)

after pushing to github:
```bash
./deploy.sh git@github.com:username/sorter.git
```

this will:
- clone to `~/scripts/sorter` on yuckbox
- create venv and install deps
- install and start systemd service

access from any tailscale device: `http://yuckbox:8050`

manual service control:
```bash
sudo systemctl status sorter
sudo systemctl restart sorter
sudo journalctl -u sorter -f
```

## technical notes

- **connection pooling**: persistent HTTP client with connection reuse for efficiency
- **retry logic**: automatic retries with exponential backoff on timeouts
- **sequential requests**: processes requests one at a time to avoid overwhelming server
- **graceful degradation**: handles server errors and timeouts gracefully
- **auto-restart**: systemd service configured with proper restart limits and graceful shutdown

## ideas

- [x] undo last action (with UI restoration)
- [x] camera filter
- [ ] stats counter (deleted/kept/fav'd)
- [ ] filter by date range
- [ ] batch mode (grid selection)
- [ ] theme toggle
