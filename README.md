# Ash — Local AI Terminal Interface

A browser-based tactical UI for chatting with a local AI, with an offline vector map, voice synthesis, and a Warhammer 40K aesthetic.

---

## Architecture Overview

```
Browser (localhost:5173)
  └── Ash UI (React/Vite)
        ├── Chat → LM Studio (localhost:1234)
        ├── Voice → TTS Server (localhost:8000)
        │             └── Piper TTS → RVC Bridge → Verity FX
        └── MapPanel (iframe)
              └── map.html → Tile Server (localhost:8080)
                              └── us.pmtiles (offline vector tiles)
```

---

## Requirements

### Runtime Dependencies

| Dependency | Version | Purpose |
|---|---|---|
| Node.js | 18+ | Frontend dev server (Vite) |
| npm | 9+ | Package management, `npx http-server` |
| Python | 3.10+ | TTS server (FastAPI + Piper) |
| LM Studio | latest | Local AI inference (OpenAI-compatible API) |
| JDK | 21 | Only needed if regenerating map tiles with planetiler |

### Python Packages (TTS server)

Installed via `pip install -r tech-priest-tts/requirements.txt`:

- `fastapi` + `uvicorn` — HTTP server
- `piper-tts` — neural TTS engine
- `onnxruntime` — Piper model inference
- `pydub` — audio effects (Verity FX pipeline)
- `numpy` — audio processing

### External Tools (map tiles)

Located in `C:\Users\richa\Desktop\planetpiler\`:

| File | Purpose |
|---|---|
| `planetiler.jar` | Generates `.pmtiles` from OSM data (JDK 21 required) |
| `pmtiles.exe` | Inspect/verify `.pmtiles` files |
| `us.pmtiles` | Pre-generated US vector tile archive (~10GB) |
| `us-260406.osm.pbf` | OpenStreetMap source data for US |
| `map.html` | MapLibre GL map page served to the iframe |

> **Note:** `us.pmtiles` was generated with planetiler 0.10.2 from OSM data as of 2026-04-06.
> Regenerating takes significant time and disk space.

---

## Ports

| Port | Service | Notes |
|---|---|---|
| 1234 | LM Studio | Must be started manually |
| 8000 | TTS server | Piper → RVC → Verity pipeline |
| 8080 | Tile server | Serves `map.html` + `us.pmtiles` |
| 5173 | Ash frontend | Vite dev server |

---

## Setup

### 1. Install frontend dependencies

```bash
npm install
```

### 2. Set up TTS server

```bash
cd tech-priest-tts
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Download the Piper voice model and place it at:
```
tech-priest-tts/models/en_GB-jenny_dioco-medium.onnx
tech-priest-tts/models/en_GB-jenny_dioco-medium.onnx.json
```

### 3. Set up RVC bridge (optional voice cloning)

The TTS pipeline routes audio through an RVC file bridge:
- Drop-in: `C:\rvc_bridge\input\<job>.wav`
- Pick-up: `C:\rvc_bridge\output\<job>.wav`

You must run `verity_watcher.py` (or equivalent RVC inference loop) separately to process files in that folder. Without it, TTS requests will time out after 30 seconds.

If you are not using RVC, set `tts_mode` to `browser` in `settings.json` to use the Web Speech API instead.

### 4. Configure LM Studio

- Load a model (e.g. Mistral)
- Enable the local server on `http://localhost:1234`
- Ensure the OpenAI-compatible API is active

### 5. Configure settings

Edit `settings.json`:

```json
{
  "lmstudio_url": "http://localhost:1234/v1",
  "model": "mistral",
  "tts_mode": "local",
  "tts_url": "http://localhost:8000/tts",
  "theme": "tech-priest-green"
}
```

| Key | Options | Description |
|---|---|---|
| `lmstudio_url` | any URL | LM Studio OpenAI-compatible endpoint |
| `model` | any string | Model ID loaded in LM Studio |
| `tts_mode` | `local`, `browser` | `local` uses Piper/RVC; `browser` uses Web Speech API |
| `tts_url` | any URL | TTS server endpoint (only used when `tts_mode: local`) |

---

## Starting Everything

Double-click `start.bat` from the project root. This opens three terminal windows:

| Window | Command |
|---|---|
| Ash - Tile Server | `npx http-server C:\Users\richa\Desktop\planetpiler -p 8080 --cors` |
| Ash - TTS Server | `uvicorn server:app --host 0.0.0.0 --port 8000` |
| Ash - Frontend | `npm run dev` |

Then start **LM Studio** manually and load your model.

Open `http://localhost:5173`.

> **Important:** The tile server must use `npx http-server`, not `python -m http.server`.
> Python's server uses HTTP/1.0 which does not support range requests.
> PMTiles requires HTTP range requests to read tile data without downloading the full ~10GB archive.

---

## Map Tile Notes

- The map uses [MapLibre GL JS](https://maplibre.org/) with the [PMTiles](https://protomaps.com/docs/pmtiles) protocol
- Tiles are served from `us.pmtiles` — a clustered vector tile archive covering the US
- The tactical style (dark green, scanlines, 3D buildings, red POI markers) is defined in `map.html`
- Default map center is Worcester, MA (`-71.4676, 42.7654`) at zoom 15, 58° pitch

To regenerate tiles from fresh OSM data (requires JDK 21):

```bash
cd C:\Users\richa\Desktop\planetpiler
java -jar planetiler.jar --download --area=us --output=us.pmtiles
```

---

## Voice Modes

| Mode | Description | Requirements |
|---|---|---|
| `browser` | Web Speech API (built into Chrome/Edge) | None |
| `local` | Piper TTS → RVC bridge → Verity FX | Python TTS server + RVC watcher |

The `local` pipeline:
1. **Piper** synthesizes speech from text using a neural ONNX model
2. **RVC bridge** converts the voice via file drop (requires external watcher at `C:\rvc_bridge\`)
3. **Verity FX** applies audio post-processing: high-pass filter, compression, presence boost, subtle pitch shift

---

## Project Structure

```
Project-Ash-Stack/
├── src/
│   ├── components/
│   │   ├── chat/         # ChatWindow, ChatInput, MessageItem
│   │   ├── layout/       # AppShell, Panel, AppHeader, StatusStrip
│   │   └── system/       # MapPanel, LogPanel, StatsPanel, ModelSelector, ErrorPanel
│   ├── hooks/            # useChat, useAudioController
│   ├── config/
│   ├── services/
│   ├── types/
│   └── App.tsx
├── tech-priest-tts/
│   ├── server.py         # FastAPI TTS server (Piper → RVC → Verity)
│   ├── models/           # Piper .onnx voice models
│   └── requirements.txt
├── settings.json         # Runtime config
├── start.bat             # One-click launcher
└── README.md
```
