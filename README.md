# Ash — Local AI Terminal Interface

A browser-based tactical UI for chatting with a local AI model via LM Studio.  
Dark green-on-black terminal aesthetic. Streaming responses. Voice output via a local TTS backend.

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + TypeScript + Vite |
| AI backend | [LM Studio](https://lmstudio.ai) (OpenAI-compatible local API) |
| TTS backend | Python (tech-priest-tts) — browser-native or custom voice |

---

## Project Structure

```
ash/
├── src/                  # React/TypeScript frontend
│   ├── components/       # UI components (chat window, input, etc.)
│   ├── hooks/            # Custom hooks (useChat, useTTS, etc.)
│   ├── types/            # Shared TypeScript types
│   └── App.tsx
│
├── tech-priest-tts/      # Python TTS backend
│   ├── server.py         # Flask/FastAPI server
│   └── requirements.txt
│
├── public/               # Static assets
├── settings.json         # Runtime config (LM Studio URL, model, voice mode)
└── .env.example          # Template for any env vars
```

---

## Getting Started

### 1. Frontend

```bash
npm install
npm run dev
```

### 2. LM Studio

- Load your model (e.g. Mistral)
- Enable the local server on `http://localhost:1234`

### 3. TTS Backend (optional)

```bash
cd tech-priest-tts
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

---

## Configuration

Edit `settings.json` to point at your LM Studio instance and set voice preferences:

```json
{
  "lmstudio_url": "http://localhost:1234/v1",
  "model": "mistral",
  "tts_mode": "browser"
}
```

---

## Voice Modes

| Mode | Description |
|---|---|
| `browser` | Uses Web Speech API (no extra setup) |
| `local` | Routes through the tech-priest-tts Python backend |

---

## Notes

- `.venv/` is gitignored — run the setup steps above after cloning
- Audio output files are gitignored (`*.wav`, `*.mp3`)
- See `settings.json` for runtime tunables
