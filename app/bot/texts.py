"""Bot ke saare user-facing texts aur chhote formatting helpers.

Yeh module deliberately `python-telegram-bot` import nahi karta, taaki ise
offline test kiya ja sake aur web app bhi helpers reuse kar sake.
"""

from __future__ import annotations

import re

from app.schemas import FormatOption, MediaInfo

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Reply-keyboard buttons (private chats only).
MENU_LINK = "🔗 Link bhejein"
MENU_SETTINGS = "⚙️ Settings"
MENU_STATUS = "📊 Status"
MENU_HELP = "❓ Help"
MENU_CANCEL = "🛑 Cancel"
MENU_BUTTONS = {MENU_LINK, MENU_SETTINGS, MENU_STATUS, MENU_HELP, MENU_CANCEL}

QUALITY_CHOICES: tuple[tuple[str, str], ...] = (
    ("best", "Best available"),
    ("1080", "1080p"),
    ("720", "720p"),
    ("480", "480p"),
    ("360", "360p"),
    ("audio", "MP3 (audio)"),
)
QUALITY_KEYS = {key for key, _ in QUALITY_CHOICES}
QUALITY_LABELS = dict(QUALITY_CHOICES)

WELCOME = (
    "🎬 <b>ClipNest bot</b>\n\n"
    "Mujhe koi bhi video link bhejein — YouTube, Instagram, X/Twitter, "
    "Facebook, TikTok, Vimeo, Reddit, ya seedha <code>.mp4</code> link.\n\n"
    "Main title aur quality options dikhaunga. Aap quality chunenge, aur file "
    "yahin chat mein aa jaayegi.\n\n"
    "⬇️ Shuru karne ke liye neeche <b>Link bhejein</b> dabayein ya link paste karein.\n\n"
    "⚖️ Sirf wahi content download karein jiska aapko haq hai."
)

HELP = (
    "<b>Kaise use karein</b>\n"
    "1️⃣ Link chat mein paste karke bhejein.\n"
    "2️⃣ Title, duration aur quality buttons dikhenge.\n"
    "3️⃣ Quality (144p-4K) ya 🎵 MP3 chunein.\n"
    "4️⃣ Progress live update hoga, phir file chat mein aa jayegi.\n\n"
    "<b>Commands</b>\n"
    "/start — bot shuru karein\n"
    "/settings — default quality aur document mode\n"
    "/status — active downloads aur queue\n"
    "/cancel — apne saare downloads rok dein\n"
    "/id — apna Telegram user ID\n"
    "/privacy — data aur cleanup info\n"
    "/help — yeh madad\n\n"
    "<b>Tips</b>\n"
    "• Telegram cloud par ek file max <b>50 MB</b> tak jaati hai. Badi video ke liye "
    "chhoti quality chunein.\n"
    "• Self-hosted local Bot API server ke saath yeh limit 2 GB tak badh sakti hai.\n"
    "• ⚠️ wale quality buttons upload limit se badi ho sakti hain.\n"
    "• Group mein bot ko link padhne ke liye BotFather se privacy mode off karein.\n\n"
    "⚖️ Sirf apna, Creative Commons, public domain ya permitted content download karein."
)

PRIVACY = (
    "<b>Privacy aur data</b>\n"
    "• Bot sirf woh links dekhta hai jo aap use bhejte hain (private chat mein).\n"
    "• Downloaded files server par sirf thodi der (default 60 minute) rehti hain, "
    "phir automatically delete ho jaati hain.\n"
    "• Aapki settings (default quality, document mode) ek JSON file mein server par "
    "save hoti hain — koi analytics ya third-party tracking nahi.\n"
    "• Bot token aur cookies kabhi share na karein.\n\n"
    "Server admin hi data ka zimmedar hai. Apna instance public karne se pehle "
    "allowlist aur rate limit zaroor set karein."
)

PRIVATE_ONLY = "⛔ Yeh bot private hai. Apne user ID ke saath admin se allow karwayein."
RATE_LIMITED = (
    "🚦 Bahut zyada requests. 10 minute mein {limit} allowed hain — thodi der baad try karein."
)
NO_LINK = (
    "🔗 Mujhe ek video link bhejein — jaise "
    "<code>https://youtu.be/...</code> ya <code>https://example.com/clip.mp4</code>."
)
PROBE_STARTED = "🔍 Link check kar raha hoon…"
PROBE_GONE = "⌛ Yeh button purana ho gaya (ya bot restart hua). Link dobara bhejein."
ALREADY_USED = "⏳ Is link ka download pehle hi select ho chuka hai. Naya link bhejein."
NOT_YOURS = "🔒 Yeh card kisi aur ne banaya hai. Apna link bhejein."
UNKNOWN_BUTTON = "Yeh button ab valid nahi hai. Link dobara bhejein."
NO_ENGINE = "❌ Is link ke liye koi downloader available nahi hai."
PROBE_FAILED = "❌ Link check nahi ho paya. Link sahi hai na? Dobara koshish karein."
UNEXPECTED = "❌ Kuch gadbad ho gayi. Dobara koshish karein."


def extract_url(text: str) -> str | None:
    """Message text se pehla HTTP(S) link nikaalo."""
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(").,;!\"'")


def parse_allowed_users(raw: str) -> set[int]:
    """`"123, 456;789"` jaisi string ko user-id set mein badlo."""
    allowed: set[int] = set()
    for chunk in (raw or "").replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            allowed.add(int(chunk))
    return allowed


def format_size(num: float | None) -> str:
    if not num or num <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} GB"


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "-"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def progress_bar(percent: float, width: int = 12) -> str:
    filled = max(0, min(width, round(percent / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def quality_from_pref(pref: str) -> tuple[str | None, bool]:
    """User preference ko `(format_id, audio_only)` mein badlo."""
    pref = (pref or "best").strip().lower()
    if pref == "audio":
        return None, True
    if pref == "best" or pref not in QUALITY_KEYS:
        return None, False
    return f"v{pref}", False


def quality_label(
    option: FormatOption,
    *,
    limit_bytes: int,
    default_id: str | None = None,
) -> str:
    label = option.label
    if option.filesize:
        label += f" · {format_size(option.filesize)}"
    if option.filesize and limit_bytes and option.filesize > limit_bytes:
        label += " ⚠️"
    if option.id == default_id:
        label = f"• {label}"
    return truncate(label, 60)


def info_caption(
    info: MediaInfo,
    *,
    limit_mb: int,
    default_quality: str = "best",
    strict_size: bool = False,
) -> str:
    """Probe result ka caption (photo captions ke liye 1024 se chhota)."""
    lines = [f"🎬 <b>{escape_html(info.title)}</b>"]
    meta: list[str] = []
    if info.uploader:
        meta.append(f"👤 {escape_html(truncate(info.uploader, 80))}")
    if info.duration:
        meta.append(f"⏱ {format_duration(info.duration)}")
    if info.engine:
        meta.append(f"⚙️ {escape_html(info.engine)}")
    if meta:
        lines.append(" · ".join(meta))

    if info.formats:
        lines.append("")
        lines.append(f"🎚 Quality chunein (Telegram limit: {limit_mb} MB):")
        oversized = any(
            option.filesize and option.filesize > limit_mb * 1024 * 1024 for option in info.formats
        )
        if oversized:
            note = "⚠️ = file limit se badi ho sakti hai."
            if strict_size:
                note += " Aise option download nahi honge."
            lines.append(note)
        label = QUALITY_LABELS.get(default_quality, default_quality)
        lines.append(f"⚡ Quick button aapki default quality ({escape_html(label)}) use karega.")
    else:
        lines.append("")
        lines.append("Quality list khali hai — original file try karein.")

    return "\n".join(lines)


def settings_text(default_quality: str, send_as_document: bool) -> str:
    label = QUALITY_LABELS.get(default_quality, default_quality)
    doc = "On 📎" if send_as_document else "Off 🎬"
    return (
        "<b>⚙️ Settings</b>\n\n"
        f"🎚 Default quality: <b>{escape_html(label)}</b>\n"
        f"📎 Document mode: <b>{doc}</b>\n\n"
        "Default quality woh option hai jo <b>⚡ Quick</b> button use karta hai.\n"
        "Document mode on karne par video file player preview ke bajaye document "
        "ke roop mein aayegi (quality same rehti hai)."
    )


def progress_text(job, label: str, queue_position: int = 0) -> str:
    title = truncate(job.title or "Download", 120)
    lines = [
        f"⬇️ <b>{escape_html(title)}</b>",
        f"{progress_bar(job.progress)} {job.progress:.0f}%",
    ]
    detail = [f"🎚 {escape_html(label)}"]
    if job.speed:
        detail.append(f"⚡ {format_size(job.speed)}/s")
    if job.eta:
        detail.append(f"⏳ {format_duration(job.eta)}")
    lines.append(" · ".join(detail))

    if job.status == "queued":
        if queue_position > 1:
            lines.append(f"⏸ Queue mein — position {queue_position}")
        else:
            lines.append("⏸ Queue mein — bas shuru hone wala hai")
    elif job.status == "running":
        lines.append("📥 Download chal raha hai…")
    return "\n".join(lines)


def uploading_text(job) -> str:
    title = truncate(job.title or "File", 120)
    return (
        f"✅ <b>{escape_html(title)}</b>\n"
        "Download poora hua — Telegram par bhej raha hoon…\n"
        f"📦 {format_size(job.filesize)}"
    )


def delivered_text(job) -> str:
    title = truncate(job.title or "File", 120)
    return (
        f"✅ <b>{escape_html(title)}</b>\n"
        f"File bhej di gayi · {format_size(job.filesize)}\n"
        "Naya link bhejein jab chahein."
    )


def cancelled_text(job) -> str:
    title = truncate(job.title or "Download", 120)
    return f"🛑 <b>{escape_html(title)}</b>\nDownload cancel ho gaya."


def failed_text(job) -> str:
    title = truncate(job.title or "Download", 120)
    reason = truncate(job.error or "unknown error", 300)
    return (
        f"❌ <b>{escape_html(title)}</b>\n"
        f"Fail hua: {escape_html(reason)}\n"
        "Link ya quality badal kar dobara try karein."
    )


def upload_failed_text(error: str | None) -> str:
    reason = truncate(error or "Telegram ne file accept nahi ki", 300)
    return (
        "❌ File bhej nahi paya.\n"
        f"Reason: {escape_html(reason)}\n"
        "File server par kuch der ke liye saved hai — Retry kar sakte hain."
    )


def too_big_text(size: int, limit_mb: int, local_mode: bool = False) -> str:
    lines = [
        f"⚠️ File {format_size(size)} ki hai — Telegram limit {limit_mb} MB hai.",
        "Chhoti quality (jaise 480p ya 360p) chun kar dobara bhejein.",
    ]
    if not local_mode:
        lines.append(
            "💡 Badi files ke liye admin local Bot API server chala sakta hai (limit 2 GB tak)."
        )
    return "\n".join(lines)


def status_text(
    *,
    version: str,
    uptime_seconds: float,
    active_jobs: int,
    my_jobs: int,
    ttl_minutes: int,
    disk_free: int | None,
    limit_mb: int,
    local_mode: bool,
) -> str:
    hours, rest = divmod(int(uptime_seconds), 3600)
    minutes = rest // 60
    uptime = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    lines = [
        "<b>📊 Bot status</b>",
        f"🧩 Version: {version}",
        f"⏱ Uptime: {uptime}",
        f"🔄 Active downloads (sab users): {active_jobs}",
        f"👤 Aapke active jobs: {my_jobs}",
        f"🧹 File TTL: {ttl_minutes} min",
        f"📦 Upload limit: {limit_mb} MB" + (" (local API)" if local_mode else ""),
    ]
    if disk_free is not None:
        lines.append(f"💾 Disk free: {format_size(disk_free)}")
    return "\n".join(lines)


def escape_html(text: str) -> str:
    """HTML parse_mode ke liye minimum escaping (titles user-controlled hote hain)."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
