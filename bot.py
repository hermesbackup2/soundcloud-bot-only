#!/usr/bin/env python3
import asyncio
import re
import io
import logging
import os
import subprocess
import tempfile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from services import soundcloud as sc
from config import (
    BOT_TOKEN,
    PROXY_URL,
    ALLOWED_USER_IDS,
    PAGE_SIZE,
    SEARCH_PAGE_SIZE,
)
from services.downloader import download_track_audio
from services import history
from services.queue import download_queue
from sessions import user_sessions, touch_session, cleanup_old_sessions

from logging.handlers import RotatingFileHandler
from config import LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT

# Console handler
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s"
))

# File handler with rotation
_file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s"
))

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console_handler, _file_handler],
    force=True,
)
logger = logging.getLogger(__name__)



def is_authorized(user_id: int) -> bool:
    return user_id in ALLOWED_USER_IDS


async def reject_unauthorized(update: Update) -> None:
    message = update.effective_message
    if message:
        await message.reply_text("⛔ دسترسی ندارید.")


def fmt_duration(ms: int | None) -> str:
    if not ms:
        return "—"
    seconds = int(ms) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def _download_cover(artwork_url: str, out_path: str) -> bool:
    """Download and resize cover art to 320x320 JPEG."""
    try:
        import requests
        from PIL import Image

        response = requests.get(
            artwork_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
            proxies={"http": PROXY_URL, "https": PROXY_URL},
        )
        response.raise_for_status()

        img = Image.open(io.BytesIO(response.content))
        img = img.convert("RGB")
        img.thumbnail((320, 320))
        img.save(out_path, format="JPEG", quality=85)
        return True
    except Exception:
        logger.exception("Failed to download cover")
        return False


def validate_mp3(mp3_path: str) -> bool:
    """Validate MP3 file integrity using ffmpeg."""
    if not os.path.exists(mp3_path):
        return False
    if os.path.getsize(mp3_path) < 1024:  # کمتر از ۱KB = خراب
        logger.error(f"File too small: {mp3_path}")
        return False
    try:
        result = subprocess.run(
            ['ffmpeg', '-v', 'error', '-i', mp3_path, '-f', 'null', '-'],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors='replace')[:200]
            logger.error(f"MP3 validation failed: {err}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"MP3 validation timeout: {mp3_path}")
        return False
    except Exception as e:
        logger.error(f"MP3 validation error: {e}")
        return False


def _make_square_cover(artwork_url: str, out_path: str) -> bool:
    """
    Download artwork and create a beautiful 500x500 square cover:
    - Center: original image (fit within square)
    - Background: blurred, scaled version of the image
    """
    try:
        import requests
        from PIL import Image, ImageFilter

        response = requests.get(
            artwork_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
            proxies={
                "http": PROXY_URL,
                "https": PROXY_URL,
            },
        )
        response.raise_for_status()

        img = Image.open(io.BytesIO(response.content)).convert("RGB")

        SIZE = 500
        # Scale down so the whole image fits
        img.thumbnail((SIZE, SIZE), Image.LANCZOS)

        # Blurred background: crop to square, blur
        bg = img.copy()
        w, h = bg.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        bg = bg.crop((left, top, left + side, top + side))
        bg = bg.resize((SIZE, SIZE), Image.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=20))

        # Foreground: keep aspect ratio, center on background
        fg = img.copy()
        fg.thumbnail((SIZE - 40, SIZE - 40), Image.LANCZOS)
        fw, fh = fg.size
        offset = ((SIZE - fw) // 2, (SIZE - fh) // 2)
        bg.paste(fg, offset)

        bg.save(out_path, format="JPEG", quality=90, optimize=True)
        return True

    except Exception:
        logger.exception("Failed to build square cover")
        return False


def add_cover_art_to_mp3(mp3_path: str, track_info: dict) -> str | None:
    """
    Create a beautiful square cover (blur background + centered image),
    then embed it into the MP3 via FFmpeg.
    Returns the thumbnail path, or None on failure.
    """
    title = (track_info.get("title") or "Unknown").strip() or "Unknown"
    artist = (
        (track_info.get("user") or {}).get("username")
        or "SoundCloud"
    ).strip() or "SoundCloud"

    logger.info(f"Tagging MP3: title={title!r}, artist={artist!r}")

    artwork_url = (
        track_info.get("artwork_url")
        or (track_info.get("user") or {}).get("avatar_url")
    )

    thumb_path = mp3_path + ".jpg"
    temp_out = mp3_path + ".tmp.mp3"

    # Build a beautiful square cover
    have_cover = False
    if artwork_url:
        artwork_url = artwork_url.replace("large.jpg", "t500x500.jpg")
        have_cover = _make_square_cover(artwork_url, thumb_path)

    try:
        cmd = ["ffmpeg", "-y", "-i", mp3_path]
        if have_cover:
            cmd += ["-i", thumb_path]

        cmd += [
            "-map", "0:a",
            "-c:a", "copy",
            "-map_metadata", "-1",
            "-id3v2_version", "3",
            "-metadata", f"title={title}",
            "-metadata", f"artist={artist}",
            "-metadata", f"album={artist}",
        ]

        if have_cover:
            cmd += [
                "-map", "1:v",
                "-c:v", "mjpeg",
                "-disposition:v", "attached_pic",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
            ]

        cmd.append(temp_out)

        result = subprocess.run(cmd, capture_output=True, timeout=120)

        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[-600:]
            logger.error(f"FFmpeg tagging failed: {err}")
            if os.path.exists(temp_out):
                os.remove(temp_out)
            return thumb_path if have_cover else None

        os.replace(temp_out, mp3_path)
        return thumb_path if have_cover else None

    except Exception:
        logger.exception("Failed to add cover art")
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except OSError:
                pass
        return thumb_path if have_cover else None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await reject_unauthorized(update)
        return

    text = (
        "🎵 SoundCloud Downloader Bot\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "\n"
        "Welcome! Download music from SoundCloud easily.\n"
        "\n"
        "📌 Features:\n"
        "\n"
        "🎧 Single Track:\n"
        "• Send a SoundCloud track link\n"
        "• Bot downloads and sends it with cover art\n"
        "\n"
        "📚 Playlist:\n"
        "• Send a SoundCloud playlist link\n"
        "• Select tracks you want\n"
        "• Downloads in parallel\n"
        "\n"
        "🔍 Search:\n"
        "• Send a song or artist name\n"
        "• Browse results and select\n"
        "\n"
        "📦 Multiple Links:\n"
        "• Send multiple links in one message\n"
        "• They get queued and downloaded\n"
        "\n"
        "📊 Commands:\n"
        "• /history — Your last 20 downloads\n"
        "• /stats — Your download statistics\n"
        "• /queue — Current queue status\n"
        "• /cancel — Cancel active queue\n"
        "\n"
        "⚠️ Note:\n"
        "Some tracks may be DRM protected\n"
        "and cannot be downloaded.\n"
        "\n"
        "🚀 Get started:\n"
        "Send a link or song name:"
    )
    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await reject_unauthorized(update)
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    cleanup_old_sessions()
    touch_session(uid)

    try:
        urls = extract_soundcloud_urls(text)

        if len(urls) > 1:
            await handle_multiple_tracks(update, context, urls)
            return

        if len(urls) == 1:
            url = urls[0]
            if "sets/" in url or "playlist" in url:
                await handle_playlist(update, context, url)
            else:
                await handle_single_track(update, context, url)
            return

        await handle_search(update, context, text, page=0)

    except Exception:
        logger.exception("Unhandled message error for user %s", uid)
        await update.message.reply_text(
            "❌ عملیات انجام نشد. جزئیات خطا در log ثبت شده است."
        )


async def handle_multiple_tracks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    urls: list,
):
    """Enqueue multiple SoundCloud URLs for background processing."""
    uid = update.effective_user.id
    total = len(urls)

    existing = download_queue.get_user_task(uid)
    if existing and existing.status in ("pending", "running"):
        await update.message.reply_text(
            f"⏳ صف فعال دارید (Task #{existing.task_id})\n"
            f"پیشرفت: {existing.completed + existing.failed}/{existing.total}"
        )
        return

    task_id = await download_queue.enqueue(
        user_id=uid,
        urls=urls,
        chat_id=update.effective_chat.id,
    )

    if task_id is None:
        await update.message.reply_text("❌ خطا در افزودن به صف.")
        return

    await update.message.reply_text(f"✅ {total} آهنگ در صف قرار گرفت.")

async def handle_single_track(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
):
    msg = await update.message.reply_text("⏳ در حال دریافت اطلاعات ترک...")

    data = await asyncio.to_thread(sc.resolve_soundcloud_url, url)
    if not data or "id" not in data:
        await msg.edit_text("❌ ترک پیدا نشد یا SoundCloud پاسخ مناسبی نداد.")
        return

    title = (data.get("title") or "Unknown").strip() or "Unknown"
    artist = (
        (data.get("user") or {}).get("username") or "SoundCloud"
    ).strip() or "SoundCloud"

    # downloading message removed

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            safe_name = "".join(c for c in title if c.isalnum() or c in " -_().").strip()[:100] or str(data.get('id', 'track'))
            mp3_path = os.path.join(tmp_dir, f"{safe_name}.mp3")
            ok, err = await asyncio.to_thread(download_track_audio, data, mp3_path)

            if not ok:
                await msg.edit_text(err or "❌ دانلود انجام نشد.")
                return

            # اعتبارسنجی فایل
            is_valid = await asyncio.to_thread(validate_mp3, mp3_path)
            if not is_valid:
                logger.error(f"Downloaded file is corrupted: {mp3_path}")
                await msg.edit_text("❌ فایل دانلود شده خراب است. دوباره تلاش کنید.")
                return

            thumb_path = await asyncio.to_thread(
                add_cover_art_to_mp3, mp3_path, data
            )

            with open(mp3_path, "rb") as audio_file:
                thumb_file = (
                    open(thumb_path, "rb")
                    if thumb_path and os.path.exists(thumb_path)
                    else None
                )
                try:
                    await update.message.reply_audio(
                        audio=audio_file,
                        title=title,
                        performer=artist,
                        duration=(data.get("duration") or 0) // 1000,
                        caption=None,
                        thumbnail=thumb_file,
                    )
                    # ثبت در تاریخچه
                    try:
                        await asyncio.to_thread(
                            history.add_download,
                            uid, data.get("id"), title, artist, url,
                            (data.get("duration") or 0),
                        )
                    except Exception:
                        logger.exception("Failed to log download")
                finally:
                    if thumb_file:
                        thumb_file.close()

            await msg.delete()

    except Exception:
        logger.exception("Single track download error")
        await msg.edit_text(
            "❌ دانلود یا ارسال فایل انجام نشد. جزئیات خطا در log ثبت شده است."
        )


async def handle_playlist(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
):
    msg = await update.message.reply_text("⏳ در حال بارگذاری پلی‌لیست...")

    title, tracks = await asyncio.to_thread(sc.get_playlist_tracks, url)
    if not tracks:
        await msg.edit_text("❌ پلی‌لیست خالی است یا یافت نشد.")
        return

    uid = update.effective_user.id
    user_sessions[uid] = {
        "tracks": tracks,
        "selected": set(),
        "page": 0,
        "playlist_title": title,
        "msg_id": msg.message_id,
        "kind": "playlist",
    }
    touch_session(uid)
    await send_playlist_page(msg, uid)


def build_playlist_keyboard(session: dict) -> InlineKeyboardMarkup:
    tracks = session["tracks"]
    selected = session["selected"]
    page = session["page"]

    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(tracks))
    total_pages = max(1, (len(tracks) + PAGE_SIZE - 1) // PAGE_SIZE)

    keyboard = []
    for idx in range(start, end):
        track = tracks[idx]
        title = track.get("title", "Track")
        duration = fmt_duration(track.get("duration"))
        icon = "✅" if idx in selected else "⬜️"
        keyboard.append([
            InlineKeyboardButton(
                f"{icon} {idx + 1}. {title[:30]} ({duration})",
                callback_data=f"toggle:{idx}",
            )
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data="page:prev"))
    nav.append(InlineKeyboardButton(
        f"📄 {page + 1}/{total_pages}", callback_data="noop"
    ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data="page:next"))
    keyboard.append(nav)

    all_selected = len(selected) == len(tracks)
    keyboard.append([
        InlineKeyboardButton(
            "🔲 لغو انتخاب همه" if all_selected else "☑️ انتخاب همه",
            callback_data="toggle:all",
        ),
        InlineKeyboardButton("🔄 بازنشانی", callback_data="reset"),
    ])
    keyboard.append([
        InlineKeyboardButton(
            f"⬇️ دانلود انتخاب‌شده‌ها ({len(selected)})",
            callback_data="download",
        )
    ])
    keyboard.append([
        InlineKeyboardButton("❌ انصراف", callback_data="cancel")
    ])

    return InlineKeyboardMarkup(keyboard)


async def send_playlist_page(msg, uid: int):
    session = user_sessions.get(uid)
    if not session:
        return

    text = (
        f"📂 {session['playlist_title']}\n"
        f"تعداد کل: {len(session['tracks'])} ترک\n"
        f"انتخاب‌شده: {len(session['selected'])} ترک\n"
        f"\n"
        f"⚠️ برخی آهنگ‌ها ممکن است DRM protected باشند و قابل دانلود نباشند.\n"
        f"\n"
        f"لطفاً آهنگ‌های مورد نظر را انتخاب کنید:"
    )
    try:
        await msg.edit_text(
            text,
            reply_markup=build_playlist_keyboard(session),
        )
    except Exception:
        logger.exception("Failed to refresh playlist page")


async def handle_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
    page: int = 0,
):
    uid = update.effective_user.id
    msg = await update.message.reply_text(
        f"🔍 در حال جستجو برای: {query}..."
    )

    tracks, has_more = await asyncio.to_thread(
        sc.search_tracks,
        query,
        page * SEARCH_PAGE_SIZE,
        SEARCH_PAGE_SIZE,
    )

    if not tracks:
        await msg.edit_text("❌ نتیجه‌ای پیدا نشد.")
        return

    user_sessions[uid] = {
        "tracks": tracks,
        "selected": set(),
        "page": page,
        "query": query,
        "playlist_title": f"نتیجه جستجو: {query}",
        "msg_id": msg.message_id,
        "kind": "search",
        "has_more": has_more,
    }
    touch_session(uid)
    await send_search_page(msg, uid)


async def send_search_page(msg, uid: int):
    session = user_sessions.get(uid)
    if not session:
        return

    text = (
        f"🔎 **{session['playlist_title']}**\n"
        f"انتخاب‌شده: {len(session['selected'])}\n\n"
        "برای دانلود، آهنگ‌ها را انتخاب کنید:"
    )
    try:
        await msg.edit_text(
            text,
            reply_markup=build_search_keyboard(session),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Failed to refresh search page")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    if not is_authorized(uid):
        await q.edit_message_text("⛔ دسترسی ندارید.")
        return

    touch_session(uid)
    session = user_sessions.get(uid)

    if q.data == "noop":
        return

    if q.data == "cancel":
        user_sessions.pop(uid, None)
        await q.edit_message_text("❌ عملیات لغو شد.")
        return

    if not session:
        await q.edit_message_text(
            "❌ نشست منقضی شده است. لطفاً دوباره لینک یا جستجو بفرستید."
        )
        return

    data = q.data
    tracks = session["tracks"]
    selected = session["selected"]

    if data.startswith("toggle:"):
        value = data.split(":", 1)[1]

        if value == "all":
            if len(selected) == len(tracks):
                selected.clear()
            else:
                selected.clear()
                selected.update(range(len(tracks)))

        else:
            idx = int(value)
            if 0 <= idx < len(tracks):
                if idx in selected:
                    selected.remove(idx)
                else:
                    selected.add(idx)

    elif data == "reset":
        selected.clear()
        session["page"] = 0

    elif data == "page:prev":
        session["page"] = max(0, session["page"] - 1)

    elif data == "page:next":
        total_pages = max(1, (len(tracks) + PAGE_SIZE - 1) // PAGE_SIZE)
        session["page"] = min(total_pages - 1, session["page"] + 1)

    elif data == "search:prev":
        if session["page"] > 0:
            await handle_search(
                update, context, session["query"], session["page"] - 1,
            )
        return

    elif data == "search:next":
        if session.get("has_more"):
            await handle_search(
                update, context, session["query"], session["page"] + 1,
            )
        return

    elif data == "download":
        if not selected:
            await q.answer("هیچ آهنگی انتخاب نشده!", show_alert=True)
            return

        # پاک کردن پیام لیست قبل از شروع دانلود
        logger.info(f"Trying to delete message {q.message.message_id} in chat {q.message.chat_id}")
        try:
            await q.message.delete()
            logger.info(f"✅ Message {q.message.message_id} deleted")
        except Exception as e:
            logger.exception(f"❌ Failed to delete message: {e}")
        
        await download_selected(q, session, uid, sorted(selected))
        return

    if session.get("kind") == "search":
        await send_search_page(q.message, uid)
    else:
        await send_playlist_page(q.message, uid)


async def download_selected(q, session: dict, uid: int, indices: list[int]):
    """Download selected tracks in parallel (max 3 concurrent)."""
    total = len(indices)
    sent = [0]
    failed = []
    drm_tracks = []

    # start message removed

    semaphore = asyncio.Semaphore(3)
    completed = [0]

    async def process_one(position: int, idx: int):
        async with semaphore:
            track = session["tracks"][idx]
            title = (track.get("title") or f"track_{track.get('id')}").strip()
            artist = ((track.get("user") or {}).get("username") or "SoundCloud").strip()

            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    safe_name = "".join(c for c in title if c.isalnum() or c in " -_().").strip()[:100] or str(track.get("id", position))
                    mp3_path = os.path.join(tmp_dir, f"{safe_name}.mp3")

                    ok, err = await asyncio.to_thread(download_track_audio, track, mp3_path)
                    if not ok:
                        failed.append(f"{title} ({err})")
                        return

                    is_valid = await asyncio.to_thread(validate_mp3, mp3_path)
                    if not is_valid:
                        failed.append(f"{title} (❌ فایل خراب)")
                        return

                    thumb_path = await asyncio.to_thread(add_cover_art_to_mp3, mp3_path, track)

                    with open(mp3_path, "rb") as audio_file:
                        thumb_file = open(thumb_path, "rb") if thumb_path and os.path.exists(thumb_path) else None
                        try:
                            await q.message.reply_audio(
                                audio=audio_file, title=title, performer=artist,
                                duration=(track.get("duration") or 0) // 1000,
                                caption=None, thumbnail=thumb_file,
                            )
                            sent[0] += 1
                        finally:
                            if thumb_file:
                                thumb_file.close()
            except Exception:
                logger.exception("Download failed for user=%s track=%s", uid, track.get("id"))
                failed.append(f"{title} (❌ خطای غیرمنتظره)")
            finally:
                completed[0] += 1

    tasks = [process_one(i, idx) for i, idx in enumerate(indices, 1)]
    await asyncio.gather(*tasks, return_exceptions=True)

    summary = f"✅ {sent[0]}/{total} آهنگ ارسال شد"
    if drm_tracks:
        summary += f"\n\n🔐 DRM protected: {len(drm_tracks)}"
        for d in drm_tracks[:5]:
            summary += f"\n  • {d[:80]}"
        if len(drm_tracks) > 5:
            summary += f"\n  ... و {len(drm_tracks) - 5} مورد دیگر"
    if failed:
        summary += f"\n\n❌ ناموفق: {len(failed)}"
        for f in failed[:5]:
            summary += f"\n  • {f[:80]}"
        if len(failed) > 5:
            summary += f"\n  ... و {len(failed) - 5} خطای دیگر"

    await q.message.reply_text(summary)
    user_sessions.pop(uid, None)



# ============ History / Stats Handlers ============

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await reject_unauthorized(update)
        return

    rows = history.get_user_history(uid, limit=20)
    if not rows:
        await update.message.reply_text("📭 تاریخچه خالی است.")
        return

    lines = ["📜 ۲۰ دانلود آخر شما:\n"]
    for i, r in enumerate(rows, 1):
        title = (r.get("title") or "Unknown")[:60]
        artist = (r.get("artist") or "Unknown")[:30]
        lines.append(f"{i}. {artist} - {title}")

    await update.message.reply_text("\n".join(lines))


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await reject_unauthorized(update)
        return

    s = history.get_user_stats(uid)

    text = (
        "📊  Your Download Statistics\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📥  Total downloads    :  {s['total']}\n"
        f"📅  Today              :  {s['today']}\n"
        f"📆  This week          :  {s['week']}\n"
        f"🗓️  This month         :  {s['month']}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    await update.message.reply_text(text)


async def queue_processor(task):
    """Process a QueueTask: download all URLs, send them, log to history."""
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)

    sem = asyncio.Semaphore(3)

    async def process_one(position, url):
        if task.cancel_requested:
            return
        async with sem:
            try:
                data = await asyncio.to_thread(sc.resolve_soundcloud_url, url)
                if not data or "id" not in data:
                    task.failed += 1
                    logger.warning(f"Task #{task.task_id}: track not found: {url}")
                    return

                title = (data.get("title") or "Unknown").strip() or "Unknown"
                artist = ((data.get("user") or {}).get("username") or "SoundCloud").strip() or "SoundCloud"

                with tempfile.TemporaryDirectory() as tmp_dir:
                    safe_name = "".join(
                        c for c in title if c.isalnum() or c in " -_()."
                    ).strip()[:100] or str(data.get("id", "track"))
                    mp3_path = os.path.join(tmp_dir, f"{safe_name}.mp3")

                    ok, err = await asyncio.to_thread(
                        download_track_audio, data, mp3_path
                    )
                    if not ok:
                        task.failed += 1
                        if "DRM" in str(err) or "🔐" in str(err):
                            task.drm_protected = getattr(task, 'drm_protected', []) + [title]
                        logger.warning(f"Task #{task.task_id}: download failed: {err}")
                        return

                    is_valid = await asyncio.to_thread(validate_mp3, mp3_path)
                    if not is_valid:
                        task.failed += 1
                        return

                    thumb_path = await asyncio.to_thread(
                        add_cover_art_to_mp3, mp3_path, data
                    )

                    with open(mp3_path, "rb") as audio_file:
                        thumb_file = (
                            open(thumb_path, "rb")
                            if thumb_path and os.path.exists(thumb_path)
                            else None
                        )
                        try:
                            await bot.send_audio(
                                chat_id=task.chat_id,
                                audio=audio_file,
                                title=title,
                                performer=artist,
                                duration=(data.get("duration") or 0) // 1000,
                                caption=None,
                                thumbnail=thumb_file,
                            )
                            task.completed += 1
                            try:
                                await asyncio.to_thread(
                                    history.add_download,
                                    task.user_id, data.get("id"), title, artist,
                                    url, (data.get("duration") or 0),
                                )
                            except Exception:
                                logger.exception("History log failed")
                        finally:
                            if thumb_file:
                                thumb_file.close()
            except Exception:
                logger.exception(f"Task #{task.task_id}: error on {url}")
                task.failed += 1

    # Progress updater (فقط پیام وضعیت رو آپدیت می‌کنه، پیام جدید نمی‌فرسته)
    status_msg = None
    try:
        status_msg = await bot.send_message(
            chat_id=task.chat_id,
            text=f"📥 {task.total} لینک دریافت شد.\n⏳ در حال دانلود...",
        )
    except Exception:
        logger.exception("Failed to send status message")

    async def progress_updater():
        while task.status == "running":
            try:
                if status_msg:
                    done = task.completed + task.failed
                    await bot.edit_message_text(
                        chat_id=task.chat_id,
                        message_id=status_msg.message_id,
                        text=(
                            f"📊 پیشرفت: {done}/{task.total}\n"
                            f"✅ موفق: {task.completed}\n"
                            f"❌ ناموفق: {task.failed}"
                        ),
                    )
            except Exception:
                pass
            await asyncio.sleep(3)

    progress_task = asyncio.create_task(progress_updater())
    try:
        tasks = [process_one(i, url) for i, url in enumerate(task.urls, 1)]
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        task.status = "done"
        await asyncio.sleep(0.5)
        progress_task.cancel()

    # خلاصه نهایی
    try:
        summary = f"✅ {task.completed}/{task.total} آهنگ ارسال شد"
        drm_list = getattr(task, 'drm_protected', [])
        if drm_list:
            summary += f"\n\n🔐 DRM protected: {len(drm_list)}"
            for d in drm_list[:5]:
                summary += f"\n  • {d[:80]}"
            if len(drm_list) > 5:
                summary += f"\n  ... و {len(drm_list) - 5} مورد دیگر"
        non_drm_failed = task.failed - len(drm_list)
        if non_drm_failed > 0:
            summary += f"\n\n❌ ناموفق: {non_drm_failed}"

        if status_msg:
            try:
                await bot.edit_message_text(
                    chat_id=task.chat_id,
                    message_id=status_msg.message_id,
                    text=summary,
                )
            except Exception:
                await bot.send_message(chat_id=task.chat_id, text=summary)
        else:
            await bot.send_message(chat_id=task.chat_id, text=summary)
    except Exception:
        logger.exception("Failed to send final summary")



async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await reject_unauthorized(update)
        return
    task = download_queue.get_user_task(uid)
    if not task:
        await update.message.reply_text("📭 صف شما خالی است.")
        return
    text = (
        f"📊 صف شما:\n"
        f"🆔 Task #{task.task_id}\n"
        f"وضعیت: {task.status}\n"
        f"پیشرفت: {task.completed + task.failed}/{task.total}\n"
        f"✅ موفق: {task.completed}\n"
        f"❌ ناموفق: {task.failed}\n"
    )
    if task.status == "pending":
        pos = download_queue.queue_position(uid) or 0
        text += f"📍 موقعیت: {pos + 1}\n"
    text += "\nبرای لغو: /cancel"
    await update.message.reply_text(text)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await reject_unauthorized(update)
        return
    ok = download_queue.cancel(uid)
    if ok:
        await update.message.reply_text("✅ درخواست لغو ثبت شد.")
    else:
        await update.message.reply_text("📭 صف فعالی ندارید.")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(60)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("queue", queue_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # راه‌اندازی queue
    download_queue.set_processor(queue_processor)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(download_queue.start())

    logger.info("SoundCloud bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()