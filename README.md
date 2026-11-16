# 🎬 ClipNest

**Apna self-hosted video downloader — link chipkao, quality chuno, file save karo.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-6d5efc.svg)](LICENSE)
[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gintokisakata918-prog/clipnest/blob/main/colab.ipynb)

ClipNest ek chhota, clean web app hai jo video links ko metadata + download job mein badal deta hai.
Backend do engines par kaam karta hai:

- **yt-dlp engine** — 1000+ sites (YouTube, Instagram, X/Twitter, Facebook, TikTok, Vimeo, etc.)
- **Direct engine** — seedhe media URLs (`.mp4`, `.webm`, `.mp3` …) bina kisi extra processing ke

Frontend vanilla HTML/CSS/JS hai — koi build step nahi, koi heavy framework nahi.

> ⚖️ **Zaroori:** Sirf wahi content download karein jiska aapko haq hai (apna content, Creative Commons,
> public domain) ya jiske liye platform ne permission di ho. Platform ki terms of service aur copyright
> laws ka palan karna aapki zimmedari hai.

---

## ✨ Features

- 🔗 **Link probe** — download shuru karne se pehle title, thumbnail, duration aur available qualities dikhata hai
- 🎚️ **Quality selection** — 144p se 4K tak, ya sirf audio (MP3)
- 📊 **Live progress** — percentage, speed aur ETA real-time update
- 🛑 **Cancel** — chal raha download beech mein rok sakte hain
- 🧹 **Auto cleanup** — purani files TTL ke baad khud delete ho jaati hain
- 🔒 **SSRF guard** — private/loopback addresses block, sirf HTTP(S)
- 🚦 **Rate limiting** — per-IP sliding window
- 🐳 **Docker ready** — `docker compose up` aur bas
- 🌐 **Hindi UI** — poora interface Hindi mein

---

## 🚀 Quick start

### ☁️ Google Colab (fastest try)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/gintokisakata918-prog/clipnest/blob/main/colab.ipynb)

Notebook kholiye → **Runtime → Run all**. Do-teen minute mein ek public
`https://....trycloudflare.com` link mil jayega, koi server ki zaroorat nahi.

> Colab session temporary hota hai (disconnect / ~12 ghante tak). Permanent hosting ke liye
> Docker ya VPS use karein.

### Docker (recommended)

```bash
git clone https://github.com/gintokisakata918-prog/clipnest.git
cd clipnest
cp .env.example .env

docker compose up -d --build
```

Ab kholiye: **http://localhost:8000**

### Local development

Requirements: Python 3.11+, [uv](https://github.com/astral-sh/uv), aur `ffmpeg` (quality merge / MP3 ke liye).

```bash
git clone https://github.com/gintokisakata918-prog/clipnest.git
cd clipnest

uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --reload
```

App: http://localhost:8000 · API docs: http://localhost:8000/api/docs

---

## ⚙️ Configuration

Saari settings environment variables se control hoti hain (prefix `CLIPNEST_`) ya `.env` file se.

| Variable | Default | Matlab |
| --- | --- | --- |
| `CLIPNEST_DOWNLOAD_DIR` | `./downloads` | Downloaded files kahan rakhein |
| `CLIPNEST_MAX_CONCURRENT_DOWNLOADS` | `2` | Ek saath kitne downloads |
| `CLIPNEST_JOB_TTL_MINUTES` | `60` | Kitne minute baad file auto-delete |
| `CLIPNEST_MAX_FILESIZE_MB` | `2048` | Ek file ka max size (MB) |
| `CLIPNEST_MAX_DURATION_SECONDS` | `10800` | Max video length (3 ghante) |
| `CLIPNEST_COOKIES_FILE` | – | Netscape format cookies file (private content ke liye) |
| `CLIPNEST_ALLOW_PRIVATE_HOSTS` | `false` | Local network links allow karein? (sirf testing) |
| `CLIPNEST_RATE_LIMIT_PER_10MIN` | `20` | Per-IP requests ki limit (0 = off) |
| `CLIPNEST_REQUEST_TIMEOUT_SECONDS` | `30` | Upstream request timeout |

---

## 🧩 API

| Method | Endpoint | Kaam |
| --- | --- | --- |
| `GET` | `/api/health` | Health + active jobs |
| `POST` | `/api/info` | Link ka metadata aur formats |
| `POST` | `/api/download` | Naya download job (202) |
| `GET` | `/api/jobs/{id}` | Job status / progress |
| `GET` | `/api/jobs/{id}/file` | Finished file download |
| `POST` | `/api/jobs/{id}/cancel` | Job cancel |
| `DELETE` | `/api/jobs/{id}` | Job + file delete |

Example:

```bash
# 1) Link check karo
curl -s -X POST http://localhost:8000/api/info \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/video"}'

# 2) Download shuru karo
curl -s -X POST http://localhost:8000/api/download \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/video","format_id":"v1080"}'
# => {"id":"a1b2c3d4e5f6","status":"queued", ...}

# 3) Progress dekho
curl -s http://localhost:8000/api/jobs/a1b2c3d4e5f6

# 4) File lo
curl -OJ http://localhost:8000/api/jobs/a1b2c3d4e5f6/file
```

`format_id` sirf `v<height>` pattern accept karta hai (jaise `v720`, `v1080`) — random strings reject ho jaate hain.
Audio ke liye `{"audio_only": true}` bhejein.

---

## 🏗️ Project structure

```
clipnest/
├── app/
│   ├── main.py          # FastAPI app, routes, rate limiting, janitor
│   ├── config.py        # env-driven settings
│   ├── jobs.py          # job manager (queue + progress + cleanup)
│   ├── schemas.py       # request/response models
│   ├── security.py      # URL validation + SSRF guard
│   └── engines/
│       ├── base.py      # engine interface
│       ├── direct.py    # plain media URLs
│       └── ytdlp.py     # yt-dlp wrapper
├── static/              # Hindi web UI (no build step)
├── tests/               # offline API tests
└── Dockerfile
```

Naya engine add karna ho to `BaseEngine` implement karein (`can_handle`, `probe`, `download`) aur
`create_app()` ki `engines` list mein daal dein — baaki sab automatic hai.

---

## 🧪 Development

```bash
uv run ruff format .
uv run ruff check --fix .
uv run pytest
```

Tests network use nahi karte — ek fake engine inject hota hai, isliye CI mein bhi fast chalte hain.

---

## 🔒 Security notes

- Sirf `http://` aur `https://` accept hote hain; private, loopback aur link-local IPs block hain.
- Koi authentication nahi hai — ise public internet par bina reverse proxy + auth ke na chalayein.
- Downloaded files `downloads/` mein job-id folders mein rehti hain aur TTL ke baad delete hoti hain.
- Cookies file mein sensitive data hota hai — use volume se bahar commit na karein.

---

## 📄 License

[MIT](LICENSE) © 2026 **Kamui**

---

<p align="center">Agar ClipNest kaam ka laga to ek ⭐ zaroor dein!</p>
