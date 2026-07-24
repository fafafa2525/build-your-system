"""
AdsBot — Telegram bot + background worker for Facebook Ads Library scraping.

Single process runs two coroutines:
1. Telegram bot: /search, /addkey, /keys, /stats, /help
2. Worker: polls Lovable API for pending jobs, runs Apify + phone extraction,
   uploads numbers back and sends results to the requesting user on Telegram.

All state (keys, jobs, numbers, logs) lives in Lovable Cloud — this process is stateless.
"""

import asyncio
import io
import logging
import os
import re
import signal
from datetime import datetime
from typing import Any, Optional

import requests
from apify_client import ApifyClient
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------------- Configuration ----------------
load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
LOVABLE_API_URL = os.environ["LOVABLE_API_URL"].rstrip("/")
BOT_API_TOKEN = os.environ["BOT_API_TOKEN"]
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL_SECONDS", "30"))
APIFY_ACTOR = os.getenv("APIFY_FB_ADS_ACTOR", "curious_coder/facebook-ads-library-scraper")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("adsbot")

# Conversation states
CHOOSE_KEYWORD, CHOOSE_COUNTRY = range(2)

COUNTRIES = [
    ("DZ", "🇩🇿 الجزائر"), ("MA", "🇲🇦 المغرب"), ("TN", "🇹🇳 تونس"),
    ("EG", "🇪🇬 مصر"), ("SA", "🇸🇦 السعودية"), ("AE", "🇦🇪 الإمارات"),
    ("KW", "🇰🇼 الكويت"), ("QA", "🇶🇦 قطر"), ("JO", "🇯🇴 الأردن"),
    ("IQ", "🇮🇶 العراق"), ("LY", "🇱🇾 ليبيا"), ("FR", "🇫🇷 فرنسا"),
]

# ---------------- Lovable API helper ----------------

def api(method: str, path: str, **kwargs) -> Any:
    """Call Lovable API with the shared bearer token."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {BOT_API_TOKEN}"
    r = requests.request(method, f"{LOVABLE_API_URL}{path}", headers=headers, timeout=30, **kwargs)
    if not r.ok:
        raise RuntimeError(f"{method} {path} → {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}

def log_job(search_id: str, level: str, message: str, meta: Optional[dict] = None) -> None:
    try:
        api("POST", "/api/public/bot/logs",
            json={"search_id": search_id, "level": level, "message": message, "meta": meta})
    except Exception as e:
        log.warning("log_job failed: %s", e)

def update_job(search_id: str, **fields) -> None:
    try:
        api("PATCH", "/api/public/bot/jobs", json={"id": search_id, **fields})
    except Exception as e:
        log.warning("update_job failed: %s", e)

def heartbeat(service: str, status: str = "online", details: Optional[dict] = None) -> None:
    try:
        api("POST", "/api/public/bot/heartbeat",
            json={"service": service, "status": status, "details": details})
    except Exception as e:
        log.warning("heartbeat failed: %s", e)

# ---------------- Auth check for Telegram commands ----------------

_allowed_ids_cache: set[int] = set()
_allowed_ids_updated_at: float = 0

async def is_allowed(user_id: int) -> bool:
    """Cache allowed IDs for 60s to avoid hammering the API."""
    global _allowed_ids_cache, _allowed_ids_updated_at
    now = asyncio.get_event_loop().time()
    if now - _allowed_ids_updated_at > 60:
        # Read from bot_settings via a public endpoint would be nicer.
        # For now: allow if the DB has no allowlist (bootstrap) OR user is in it.
        try:
            # Simple approach: fetch keys to also validate connectivity, then
            # settings via a dedicated small endpoint. We use jobs GET as a ping.
            # Real allowlist lookup: we call a lightweight settings endpoint if we add one.
            # For now, we trust config; the frontend Settings page manages this list
            # and we sync via a simple fetch below.
            r = requests.get(
                f"{LOVABLE_API_URL}/api/public/bot/settings",
                headers={"Authorization": f"Bearer {BOT_API_TOKEN}"},
                timeout=10,
            )
            if r.ok:
                data = r.json()
                ids = data.get("allowed_telegram_ids") or []
                _allowed_ids_cache = set(int(x) for x in ids)
                _allowed_ids_updated_at = now
        except Exception as e:
            log.warning("Could not fetch allowlist: %s", e)
    if not _allowed_ids_cache:
        return True  # Bootstrap: no restriction until user adds their ID
    return user_id in _allowed_ids_cache

# ---------------- Phone extraction (adapted from user's script) ----------------

PHONE_REGEX = re.compile(r"(?:(?:00|\+)?[\s\-]?)?(\d[\d\s\-]{7,20}\d)")

def extract_phones_from_text(text: str, country_dial: Optional[str] = None) -> list[str]:
    """Extract phone-like sequences and normalize."""
    if not text:
        return []
    out = set()
    for m in PHONE_REGEX.findall(text):
        digits = re.sub(r"[^\d]", "", m)
        if len(digits) < 8 or len(digits) > 15:
            continue
        # Strip country-dial prefix so all numbers for the same country compare equal
        if country_dial and digits.startswith(country_dial):
            digits = "0" + digits[len(country_dial):]
        out.add(digits)
    return list(out)

DIAL_BY_COUNTRY = {
    "DZ": "213", "MA": "212", "TN": "216", "EG": "20", "SA": "966",
    "AE": "971", "KW": "965", "QA": "974", "BH": "973", "OM": "968",
    "JO": "962", "LB": "961", "IQ": "964", "SY": "963", "YE": "967",
    "LY": "218", "SD": "249", "FR": "33", "US": "1", "GB": "44", "TR": "90",
}

# ---------------- Apify runner ----------------

def get_active_key() -> Optional[dict]:
    data = api("GET", "/api/public/bot/keys")
    keys = data.get("keys") or []
    return keys[0] if keys else None

def run_facebook_scrape(keyword: str, country: str, max_pages: int, search_id: str) -> list[dict]:
    """
    Run Apify Facebook Ads Library scraper.
    Rotates keys automatically on 402/429/insufficient credit.
    Returns a list of {'text', 'page_url', 'page_name'} items.
    """
    key = get_active_key()
    if not key:
        raise RuntimeError("لا توجد مفاتيح Apify نشطة. أضف مفتاحاً من /addkey أو من الواجهة.")

    log_job(search_id, "info", f"استخدام المفتاح: {key['label']}")

    for attempt in range(len(range(10))):  # up to 10 rotations
        try:
            client = ApifyClient(key["api_key"])
            input_data = {
                "queryString": keyword,
                "countryCode": country,
                "activeStatus": "active",
                "count": max_pages,
                "adType": "all",
            }
            log_job(search_id, "info", f"تشغيل Apify actor: {APIFY_ACTOR}")
            run = client.actor(APIFY_ACTOR).call(run_input=input_data, timeout_secs=600)
            update_job(search_id, apify_run_id=run["id"])
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            # Mark success on key
            api("PATCH", "/api/public/bot/keys", json={"id": key["id"], "increment_usage": True})
            heartbeat("apify", "online", {"actor": APIFY_ACTOR, "items": len(items)})
            return items
        except Exception as e:
            msg = str(e)
            log_job(search_id, "warn", f"خطأ في المفتاح {key['label']}: {msg[:200]}")
            # Rotate on payment/rate/auth errors
            if any(t in msg.lower() for t in ["402", "429", "insufficient", "usage limit", "unauthorized", "monthly-usage"]):
                api("PATCH", "/api/public/bot/keys",
                    json={"id": key["id"], "status": "exhausted", "last_error": msg[:500]})
                key = get_active_key()
                if not key:
                    raise RuntimeError("انتهت جميع مفاتيح Apify — أضف مفتاحاً جديداً")
                log_job(search_id, "info", f"الانتقال للمفتاح: {key['label']}")
                continue
            raise
    raise RuntimeError("فشل بعد استنفاد كل المفاتيح")

# ---------------- Worker loop ----------------

async def worker_loop(app: Application) -> None:
    log.info("Worker loop started")
    while True:
        try:
            data = api("GET", "/api/public/bot/jobs?next=1")
            job = data.get("job")
            if job:
                asyncio.create_task(process_job(app, job))
        except Exception as e:
            log.exception("Worker poll error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)

async def process_job(app: Application, job: dict) -> None:
    sid = job["id"]
    keyword = job["keyword"]
    country = job["country"]
    max_pages = job.get("max_pages") or 100
    chat_id = job.get("telegram_chat_id")

    async def notify(text: str):
        if chat_id:
            try:
                await app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            except Exception:
                pass

    try:
        log_job(sid, "info", f"بدء البحث: '{keyword}' — {country}")
        await notify(f"🚀 بدأ البحث عن <b>{keyword}</b> في <b>{country}</b>...")
        update_job(sid, progress=5, progress_message="جاري تشغيل Apify...")

        # Run in a thread so we don't block the event loop
        loop = asyncio.get_event_loop()
        items = await loop.run_in_executor(None, run_facebook_scrape, keyword, country, max_pages, sid)

        update_job(sid, progress=60, progress_message=f"معالجة {len(items)} إعلان...", pages_found=len(items))
        log_job(sid, "info", f"تم استخراج {len(items)} إعلان — بدء استخراج الأرقام")

        # Extract phones from every ad's text-y fields
        dial = DIAL_BY_COUNTRY.get(country)
        phones_agg: dict[str, dict] = {}
        for it in items:
            text_blob = " ".join([
                str(it.get("adText", "") or ""),
                str(it.get("body", "") or ""),
                str(it.get("linkDescription", "") or ""),
                str(it.get("caption", "") or ""),
                str(it.get("cta", "") or ""),
                str(it.get("pageName", "") or ""),
            ])
            for p in extract_phones_from_text(text_blob, dial):
                if p not in phones_agg:
                    phones_agg[p] = {
                        "phone": p,
                        "page_url": it.get("pageProfileUri") or it.get("pageUrl"),
                        "page_name": it.get("pageName"),
                    }

        update_job(sid, progress=80, progress_message=f"رفع {len(phones_agg)} رقم...")

        # Upload in batches
        result = api("POST", "/api/public/bot/numbers",
                     json={"search_id": sid, "country": country, "items": list(phones_agg.values())})
        new_count = result.get("new_count", 0)
        total = result.get("total", 0)

        update_job(sid, status="completed", progress=100, progress_message="مكتمل",
                   numbers_found=total, numbers_new=new_count, finished=True)
        log_job(sid, "info", f"مكتمل — {total} رقم إجمالي، {new_count} جديد")

        # Send file to user
        if chat_id and new_count > 0:
            phones_list = result.get("new_phones") or []
            file_content = "\n".join(phones_list)
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ <b>اكتمل البحث</b>\n\n"
                    f"🔎 الكلمة: <code>{keyword}</code>\n"
                    f"🌍 الدولة: {country}\n"
                    f"📄 صفحات: {len(items)}\n"
                    f"📞 أرقام جديدة: <b>{new_count}</b> / {total}"
                ),
                parse_mode=ParseMode.HTML,
            )
            if file_content:
                await app.bot.send_document(
                    chat_id=chat_id,
                    document=io.BytesIO(file_content.encode("utf-8")),
                    filename=f"{keyword}_{country}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                    caption=f"{new_count} رقم جديد",
                )
        elif chat_id:
            await notify(f"✅ اكتمل البحث — لا توجد أرقام جديدة (كل الأرقام مكررة)")

    except Exception as e:
        err = str(e)
        log.exception("Job %s failed", sid)
        log_job(sid, "error", err)
        update_job(sid, status="failed", error_message=err[:500], finished=True)
        await notify(f"❌ فشل البحث: {err[:200]}")

# ---------------- Heartbeat loop ----------------

async def heartbeat_loop() -> None:
    while True:
        try:
            heartbeat("vps", "online")
            heartbeat("telegram_bot", "online")
        except Exception as e:
            log.warning("Heartbeat error: %s", e)
        await asyncio.sleep(HEARTBEAT_INTERVAL)

# ---------------- Telegram handlers ----------------

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.message.reply_text(
            f"❌ غير مصرح لك.\n\nمعرفك: <code>{update.effective_user.id}</code>\n"
            f"أضفه من الواجهة → الإعدادات → معرفات تلجرام المسموح لها.",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        "👋 <b>مرحباً في AdsBot</b>\n\n"
        "الأوامر المتاحة:\n"
        "🔍 /search — بحث جديد في مكتبة إعلانات فيسبوك\n"
        "🔑 /addkey — إضافة مفتاح Apify\n"
        "📊 /keys — عرض حالة المفاتيح\n"
        "📈 /stats — إحصائيات\n"
        "❓ /help — المساعدة",
        parse_mode=ParseMode.HTML,
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await start_cmd(update, ctx)

# /search flow
async def search_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ غير مصرح لك.")
        return ConversationHandler.END
    await update.message.reply_text("🔎 أرسل الكلمة المفتاحية للبحث:")
    return CHOOSE_KEYWORD

async def search_keyword(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["keyword"] = update.message.text.strip()
    kb = [
        [InlineKeyboardButton(name, callback_data=f"c:{code}") for code, name in COUNTRIES[i:i+3]]
        for i in range(0, len(COUNTRIES), 3)
    ]
    await update.message.reply_text("🌍 اختر الدولة:", reply_markup=InlineKeyboardMarkup(kb))
    return CHOOSE_COUNTRY


async def search_country(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    country = q.data.split(":")[1]
    keyword = ctx.user_data.get("keyword")
    if not keyword:
        await q.edit_message_text("❌ خطأ — ابدأ من جديد بـ /search")
        return ConversationHandler.END
    resp = api("POST", "/api/public/bot/jobs", json={
        "keyword": keyword,
        "country": country,
        "telegram_chat_id": q.message.chat.id,
        "telegram_user_id": q.from_user.id,
    })
    job = resp.get("job", {})
    await q.edit_message_text(
        f"✅ تم إنشاء المهمة\n\n"
        f"🔎 <b>{keyword}</b>\n"
        f"🌍 {country}\n\n"
        f"سأرسل النتائج فور اكتمال البحث...",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END

async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("تم الإلغاء")
    return ConversationHandler.END

# /addkey
async def addkey_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ غير مصرح لك.")
        return
    if not ctx.args:
        await update.message.reply_text(
            "الاستخدام:\n<code>/addkey apify_api_XXXXXXXX [الاسم]</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    api_key = ctx.args[0].strip()
    label = " ".join(ctx.args[1:]).strip() or None
    try:
        api("POST", "/api/public/bot/keys", json={"api_key": api_key, "label": label})
        await update.message.reply_text("✅ تمت إضافة المفتاح")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

# /keys
async def keys_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ غير مصرح لك.")
        return
    data = api("GET", "/api/public/bot/keys")
    keys = data.get("keys") or []
    if not keys:
        await update.message.reply_text("لا توجد مفاتيح نشطة. أضف واحداً بـ /addkey")
        return
    lines = [f"🔑 <b>المفاتيح النشطة: {len(keys)}</b>\n"]
    for k in keys:
        lines.append(f"• <b>{k['label']}</b> — {k['usage_count']} استخدام")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ غير مصرح لك.")
        return
    await update.message.reply_text("افتح لوحة التحكم على الويب لعرض الإحصائيات الكاملة.")

# ---------------- Main ----------------

async def post_init(app: Application) -> None:
    heartbeat("vps", "online")
    heartbeat("telegram_bot", "online")
    asyncio.create_task(worker_loop(app))
    asyncio.create_task(heartbeat_loop())
    log.info("Bot ready — worker + heartbeat running")

def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("search", search_start)],
        states={
            CHOOSE_KEYWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_keyword)],
            CHOOSE_COUNTRY: [CallbackQueryHandler(search_country, pattern=r"^c:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )


    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(conv)
    app.add_handler(CommandHandler("addkey", addkey_cmd))
    app.add_handler(CommandHandler("keys", keys_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    return app

def main() -> None:
    app = build_app()
    log.info("Starting AdsBot — connecting to %s", LOVABLE_API_URL)
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=[signal.SIGINT, signal.SIGTERM])

if __name__ == "__main__":
    main()
