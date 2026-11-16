# 🎬 ClipNest

**Telegram bot jo link ko video/audio file mein badal deta hai — apna self-hosted downloader.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-21%2B-2CA5E0?logo=telegram&logoColor=white)](https://python-telegram-bot.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-6d5efc.svg)](LICENSE)

ClipNest ek chhota, clean downloader hai jo do frontends share karta hai:

- 🤖 **Telegram bot** — link bhejo, quality chuno, file chat mein aa jaati hai
- 🌐 **Web app** — wahi engine, browser se use karne ke liye (optional)

Dono `yt-dlp` (YouTube, Instagram, X/Twitter, Facebook, TikTok, Vimeo, Reddit +
1000 aur sites) aur ek direct-media engine (`.mp4`, `.webm`, `.mp3` links) use
karte hain.

> ⚖️ **Zaroori:** Sirf wahi content download karein jiska aapko haq hai — apna
> content, Creative Commons, public domain, ya jiske liye platform ne permission
> di ho. Platform ki terms aur copyright laws ka palan karna aapki zimmedari hai.

---

## ✨ Telegram bot features

- 🔗 **Link probe** — download se pehle title, thumbnail, duration, uploader aur saari qualities
- 🎚️ **Quality menu** — 144p se 4K tak, ya sirf 🎵 MP3 (audio)
- ⚡ **Quick download** — aapki default quality ek tap mein
- 📊 **Live progress** — percentage, speed, ETA aur queue position
- 🛑 **Cancel** — ek download ya `/cancel` se saare
- 🔁 **Retry** — fail hui download/upload ko bina link dobara bheje retry karein
- ⚙️ **Per-user settings** — default quality aur document mode, restart ke baad bhi saved
- 💾 **Restart-safe buttons** — probe cards disk par save hote hain, deploy ke baad bhi kaam karte hain
- 🖼️ **Video thumbnail** — ffmpeg se preview thumbnail
- 📎 **Document fallback** — video upload fail ho to file document ke roop mein
- 🧹 **Auto cleanup** — TTL ke baad files aur probes khud delete
- 🔒 **Allowlist + rate limit + SSRF guard**
- 📈 **Local Bot API support** — 50 MB ki limit 2 GB tak
- 🌐 **Webhook ya long polling** — production deployment ke liye
- 👥 **Groups + forum topics** — requester ke card par sirf wahi buttons
- 🇮🇳 **Hindi/Hinglish UI**

---

## 🚀 Quick start (5 minute)

### 1. Bot token lein

Telegram mein [@BotFather](https://t.me/BotFather) ko `/newbot` bhejein, naam aur
username chunein, aur token copy karein (`123456789:AA...`).

### 2. Repo clone karein

```bash
git clone https://github.com/gintokisakata918-prog/Tg-downloder-.git
cd Tg-downloder-
cp .env.example .env
```

`.env` mein token daalein:

```env
CLIPNEST_TELEGRAM_BOT_TOKEN=123456789:AAExampleToken

# Optional: sirf apne aap ko ijazat dein (apna ID bot mein /id se dekhein)
# CLIPNEST_TELEGRAM_ALLOWED_USERS=123456789
```

### 3. Chalayein

Requirements: Python 3.11+, [uv](https://github.com/astral-sh/uv), aur `ffmpeg`
(quality merge / MP3 / thumbnail ke liye).

```bash
# Ubuntu/Debian
sudo apt install -y ffmpeg

uv sync --extra bot
uv run clipnest-bot
```

Bas! Telegram mein apne bot ko `/start` bhejein, phir koi bhi video link paste
karein.

### 4. 24/7 Docker (recommended)

```bash
cp .env.example .env
# .env mein CLIPNEST_TELEGRAM_BOT_TOKEN daalein

docker compose --profile bot up -d --build
docker compose --profile bot logs -f clipnest-bot
```

Web app bhi chahiye to:

```bash
docker compose --profile bot up -d --build   # bot + web, dono
```

Web app: [http://localhost:8000](http://localhost:8000)

---

## 🤖 Bot commands

| Command | Kaam |
| --- | --- |
| link bhejein | Title + quality buttons (144p–4K, MP3) |
| ⚡ Quick | Aapki default quality turant download |
| 🎵 MP3 | Sirf audio nikaalo |
| 🛑 Cancel | Chal raha download rok do |
| `/start` | Welcome + main menu |
| `/settings` | Default quality aur document mode |
| `/status` | Active downloads, queue, disk free, uptime |
| `/cancel` | Apne saare active downloads cancel |
| `/id` | Apna Telegram user ID (allowlist ke liye) |
| `/privacy` | Data aur cleanup info |
| `/help` | Madad |

### Flow

```
Link bheja  →  probe (title/thumb/qualities)  →  quality chuni
            →  queue + live progress           →  Telegram upload
            →  file chat mein
```

---

## 📦 File size limits (important)

| Setup | Max upload |
| --- | --- |
| Normal Telegram Bot API (default) | **50 MB** |
| Self-hosted [local Bot API server](https://github.com/tdlib/telegram-bot-api) | **2 GB** (aapka config) |

50 MB se badi video ke liye bot card par chhoti quality (480p/360p) chunein.
`⚠️` wale buttons limit se badi ho sakti hain.

### Local Bot API server (2 GB)

1. [my.telegram.org](https://my.telegram.org) → API development tools se
   `api_id` aur `api_hash` lein.
2. `.env` mein daalein:

```env
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef

CLIPNEST_TELEGRAM_API_BASE_URL=http://telegram-bot-api:8081
CLIPNEST_TELEGRAM_MAX_UPLOAD_MB=2000
```

3. Compose se dono chalayein:

```bash
docker compose --profile bot --profile local-api up -d --build
```

Bot automatically local mode use karega aur bade files bhej sakega.
Bina Docker ke local server chalayein to base URL
`http://127.0.0.1:8081` rakhein.

> Local Bot API server ke liye `api_id`/`api_hash` chahiye. Bot token ke saath
> kabhi public repo mein commit na karein.

---

## ⚙️ Configuration

Saari settings `.env` se aati hain (prefix `CLIPNEST_`).

### Telegram

| Variable | Default | Matlab |
| --- | --- | --- |
| `CLIPNEST_TELEGRAM_BOT_TOKEN` | – | BotFather token (bot ke liye zaroori) |
| `CLIPNEST_TELEGRAM_ALLOWED_USERS` | – | Allowed user IDs, comma separated (khali = sab) |
| `CLIPNEST_TELEGRAM_MAX_UPLOAD_MB` | `50` | Upload limit (local API ke saath badhayein) |
| `CLIPNEST_TELEGRAM_STRICT_SIZE` | `false` | Estimated size limit se badi ho to download na karein |
| `CLIPNEST_TELEGRAM_QUALITY_LIMIT` | `8` | Card par max quality buttons |
| `CLIPNEST_TELEGRAM_GENERATE_THUMBNAIL` | `true` | ffmpeg se video thumbnail |
| `CLIPNEST_TELEGRAM_PROGRESS_INTERVAL_SECONDS` | `4` | Progress update interval |
| `CLIPNEST_TELEGRAM_UPLOAD_TIMEOUT_SECONDS` | `1800` | Bade upload ka timeout |
| `CLIPNEST_TELEGRAM_PROBE_TTL_MINUTES` | `120` | Quality buttons kitni der valid |
| `CLIPNEST_TELEGRAM_USERS_FILE` | `./data/bot_users.json` | Per-user settings |
| `CLIPNEST_TELEGRAM_PROBES_FILE` | `./data/bot_probes.json` | Probe buttons |
| `CLIPNEST_TELEGRAM_API_BASE_URL` | – | Local Bot API server ka URL |
| `CLIPNEST_TELEGRAM_WEBHOOK_URL` | – | Webhook base URL (khali = polling) |
| `CLIPNEST_TELEGRAM_WEBHOOK_SECRET` | – | Webhook secret path/token |
| `CLIPNEST_TELEGRAM_WEBHOOK_LISTEN` | `0.0.0.0` | Webhook bind address |
| `CLIPNEST_TELEGRAM_WEBHOOK_PORT` | `8080` | Webhook port |

### Download engine

| Variable | Default | Matlab |
| --- | --- | --- |
| `CLIPNEST_DOWNLOAD_DIR` | `./downloads` | Files kahan rakhein |
| `CLIPNEST_MAX_CONCURRENT_DOWNLOADS` | `2` | Ek saath kitne downloads |
| `CLIPNEST_JOB_TTL_MINUTES` | `60` | Kitne minute baad file auto-delete |
| `CLIPNEST_MAX_FILESIZE_MB` | `2048` | Engine-level max file size |
| `CLIPNEST_MAX_DURATION_SECONDS` | `10800` | Max video length (3 ghante) |
| `CLIPNEST_COOKIES_FILE` | – | Netscape cookies (private/age-restricted content) |
| `CLIPNEST_ALLOW_PRIVATE_HOSTS` | `false` | Local network links (sirf testing) |
| `CLIPNEST_RATE_LIMIT_PER_10MIN` | `20` | Per-user/IP requests (0 = off) |
| `CLIPNEST_REQUEST_TIMEOUT_SECONDS` | `30` | Upstream timeout |

---

## 🌐 Production deployment

### Webhook mode (recommended)

Long polling ke bajaye webhook use karein — kam latency, kam resource.

1. Bot ke liye HTTPS domain ready karein (Caddy/Nginx + Let's Encrypt).
2. `.env`:

```env
CLIPNEST_TELEGRAM_WEBHOOK_URL=https://bot.example.com
CLIPNEST_TELEGRAM_WEBHOOK_SECRET=mera-secret-123
CLIPNEST_TELEGRAM_WEBHOOK_PORT=8080
```

3. Reverse proxy `https://bot.example.com/mera-secret-123` ko
   `http://127.0.0.1:8080/mera-secret-123` par forward karein.
4. Bot restart karein. Startup par Telegram webhook register ho jayega.

Caddy example:

```caddyfile
bot.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

> Webhook URL **https** hona chahiye. Secret mein sirf `A-Z a-z 0-9 _ -` use karein.

### systemd (VPS)

`/etc/systemd/system/clipnest-bot.service`:

```ini
[Unit]
Description=ClipNest Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=clipnest
WorkingDirectory=/opt/clipnest
EnvironmentFile=/opt/clipnest/.env
ExecStart=/opt/clipnest/.venv/bin/clipnest-bot
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clipnest-bot
sudo journalctl -u clipnest-bot -f
```

### Docker

```bash
docker compose --profile bot up -d --build
```

- Files: `./downloads`
- Settings/probes: `./data`
- Logs: `docker compose logs -f clipnest-bot`

---

## 🩺 Troubleshooting

| Problem | Fix |
| --- | --- |
| Bot reply nahi karta | Token sahi hai? `docker compose logs` dekhein. Allowlist mein apna ID hai? |
| Group mein link kaam nahi karta | BotFather → `/mybots` → Bot Settings → Group Privacy → **Turn off**, phir bot ko group se remove karke dobara add karein |
| "Yeh button purana ho gaya" | Probe TTL (default 2h) khatam ya bot restart + data delete. Link dobara bhejein |
| File 50 MB se badi | Chhoti quality chunein, ya local Bot API server setup karein |
| Video player mein nahi khulti | `/settings` → Document mode on |
| Instagram/private content fail | `CLIPNEST_COOKIES_FILE` set karein (apne logged-in session ki cookies) |
| `ffmpeg not found` | `sudo apt install ffmpeg` (MP3/merge/thumbnail ke liye zaroori) |
| `Conflict: terminated by other getUpdates` | Ek hi token par do bot instances chal rahe hain — ek band karein |
| Webhook set nahi ho raha | URL https hai? Secret valid hai? Port reachable hai? |
| Disk full | `CLIPNEST_JOB_TTL_MINUTES` kam karein; `downloads/` check karein |

---

## 🔒 Security notes

- Default mein koi authentication nahi — public bot ke liye
  `CLIPNEST_TELEGRAM_ALLOWED_USERS` **zaroor** set karein.
- Sirf `http://`/`https://` accept hote hain; private/loopback/link-local IPs block.
- Rate limit per Telegram user (aur web par per IP) lagti hai.
- Downloaded files job-id folders mein rehti hain aur TTL ke baad delete hoti hain.
- Cookies aur bot token sensitive hain — `.env`, `data/` aur `downloads/` ko
  git mein commit na karein (default `.gitignore` mein hain).
- Bot ko root se na chalayein; Docker image non-root `appuser` use karti hai.

## ⚖️ Legal

Yeh tool sirf personal/authorized use ke liye hai. Aap jo download karte hain
uske rights aapki zimmedari hain. DRM bypass, paid content piracy, ya kisi aur
ki private content access karna allowed nahi hai.

---

## 🧩 Web app + API (optional)

Wahi engine browser se:

```bash
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

- App: [http://localhost:8000](http://localhost:8000)
- API docs: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)

| Method | Endpoint | Kaam |
| --- | --- | --- |
| `GET` | `/api/health` | Health + active jobs |
| `POST` | `/api/info` | Link metadata + formats |
| `POST` | `/api/download` | Naya download job (202) |
| `GET` | `/api/jobs/{id}` | Job status / progress |
| `GET` | `/api/jobs/{id}/file` | Finished file |
| `POST` | `/api/jobs/{id}/cancel` | Cancel |
| `DELETE` | `/api/jobs/{id}` | Job + file delete |

`format_id` sirf `v<height>` (`v720`, `v1080`) ya `original` accept karta hai.
Audio ke liye `{"audio_only": true}` bhejein.

---

## 🏗️ Project structure

```
clipnest/
├── app/
│   ├── bot/
│   │   ├── core.py        # handlers, queue, progress, retry
│   │   ├── delivery.py    # video/audio/document upload + thumbnail
│   │   ├── keyboards.py   # inline/reply keyboards + callback data
│   │   ├── store.py       # restart-safe user settings + probes
│   │   └── texts.py       # Hindi/Hinglish UI text + formatting
│   ├── telegram_bot.py    # entry point (compatible wrapper)
│   ├── main.py            # FastAPI web app
│   ├── config.py          # env-driven settings
│   ├── jobs.py            # job manager (queue + progress + cleanup)
│   ├── security.py        # URL validation + SSRF guard
│   └── engines/
│       ├── direct.py      # plain media URLs
│       └── ytdlp.py       # yt-dlp wrapper
├── static/                # web UI (no build step)
├── tests/                 # offline tests (no network)
├── Dockerfile
└── docker-compose.yaml
```

Naya engine add karna ho to `BaseEngine` implement karein
(`can_handle`, `probe`, `download`) aur `ClipNestBot`/`create_app()` ki
engines list mein daal dein — UI aur queue automatic kaam karenge.

---

## 🧪 Development

```bash
uv sync --extra dev
uv run ruff format .
uv run ruff check .
uv run pytest
```

Tests network use nahi karte — fake engine inject hota hai, stores `tmp_path`
mein likhte hain. CI har push/PR par lint + format + tests chalata hai.

---

## 🗺️ Roadmap

- [ ] Playlist / multiple links ek saath
- [ ] Subtitle download
- [ ] Per-user download history
- [ ] Inline mode (`@bot <link>` kisi bhi chat mein)
- [ ] Admin broadcast / usage stats

---

## 📄 License

[MIT](LICENSE) © 2026 **Kamui**

Agar ClipNest kaam ka laga to repo ko ek ⭐ zaroor dein!
