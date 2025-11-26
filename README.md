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
[ctrl+z]   undo     undo last action
```

## camera filter

use the camera dropdown in the header to filter assets by camera model:
- select multiple cameras (hold ctrl/cmd while clicking)
- select "all cameras" to clear filter
- queue resets when filter changes

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

## ideas

- [x] undo last action
- [ ] stats counter (deleted/kept/fav'd)
- [ ] filter by date range or camera
- [ ] batch mode (grid selection)
- [ ] theme toggle
