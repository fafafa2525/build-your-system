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
from urllib.parse import urlencode

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

# Per-country rules:
#   local_len: valid lengths of the national number (with leading 0 for countries
#              that use trunk prefix, without it for Gulf 8-digit numbers).
#   use_trunk_zero: True when local form starts with 0 (e.g. 05xxxxxxxx).
#   mobile_prefixes: local prefixes indicating a mobile line (works on WhatsApp).
COUNTRY_RULES: dict[str, dict] = {
    "SA": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["05"]},
    "DZ": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["05", "06", "07"]},
    "MA": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["06", "07"]},
    "TN": {"local_len": [8],      "use_trunk_zero": False, "mobile_prefixes": ["2", "4", "5", "9"]},
    "EG": {"local_len": [11],     "use_trunk_zero": True,  "mobile_prefixes": ["010", "011", "012", "015"]},
    "AE": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["050", "052", "054", "055", "056", "058"]},
    "KW": {"local_len": [8],      "use_trunk_zero": False, "mobile_prefixes": ["5", "6", "9"]},
    "QA": {"local_len": [8],      "use_trunk_zero": False, "mobile_prefixes": ["3", "5", "6", "7"]},
    "BH": {"local_len": [8],      "use_trunk_zero": False, "mobile_prefixes": ["3"]},
    "OM": {"local_len": [8],      "use_trunk_zero": False, "mobile_prefixes": ["7", "9"]},
    "JO": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["077", "078", "079"]},
    "LB": {"local_len": [7, 8],   "use_trunk_zero": False, "mobile_prefixes": ["3", "70", "71", "76", "78", "79", "81"]},
    "IQ": {"local_len": [11],     "use_trunk_zero": True,  "mobile_prefixes": ["077", "078", "079", "075"]},
    "SY": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["09"]},
    "YE": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["07"]},
    "LY": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["091", "092", "093", "094"]},
    "SD": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["09"]},
    "FR": {"local_len": [10],     "use_trunk_zero": True,  "mobile_prefixes": ["06", "07"]},
    "US": {"local_len": [10],     "use_trunk_zero": False, "mobile_prefixes": []},
    "GB": {"local_len": [10, 11], "use_trunk_zero": True,  "mobile_prefixes": ["07"]},
    "TR": {"local_len": [11],     "use_trunk_zero": True,  "mobile_prefixes": ["05"]},
}

# ---------------- Apify runner ----------------

def get_active_key() -> Optional[dict]:
    data = api("GET", "/api/public/bot/keys")
    keys = data.get("keys") or []
    return keys[0] if keys else None

def build_facebook_ads_library_url(keyword: str, country: str) -> str:
    params = {
        "active_status": "active",
        "ad_type": "all",
        "country": country,
        "q": keyword,
        "search_type": "keyword_unordered",
        "media_type": "all",
    }
    return f"https://www.facebook.com/ads/library/?{urlencode(params)}"

def extract_page_urls(items: list) -> list[str]:
    urls: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        snap = it.get("snapshot") if isinstance(it.get("snapshot"), dict) else {}
        candidates = [
            it.get("pageProfileUri"), it.get("pageUrl"), it.get("page_url"),
            it.get("pageProfileUrl"), it.get("url"),
            snap.get("page_profile_uri"), snap.get("page_profile_url"),
        ]
        page_id = it.get("pageID") or it.get("page_id") or snap.get("page_id")
        if page_id:
            candidates.append(f"https://www.facebook.com/{page_id}")
        for u in candidates:
            if not u or not isinstance(u, str):
                continue
            if "facebook.com" not in u:
                continue
            if "/ads/library" in u or "/share/" in u:
                continue
            urls.add(u.strip())
    return list(urls)


def normalize_local_phone(raw: str, country: str) -> Optional[str]:
    """Strip formatting, drop country dial code, produce national canonical form."""
    if not raw:
        return None
    s = re.sub(r"[\s\-\+\(\)\.]", "", str(raw))
    if s.startswith("00"):
        s = s[2:]
    s = re.sub(r"[^\d]", "", s)
    if not s:
        return None
    dial = DIAL_BY_COUNTRY.get(country)
    rules = COUNTRY_RULES.get(country, {})
    use_zero = rules.get("use_trunk_zero", True)
    if dial and s.startswith(dial):
        s = s[len(dial):]
        if use_zero and not s.startswith("0"):
            s = "0" + s
    if len(s) < 7 or len(s) > 15:
        return None
    return s


def classify_phone(local: str, country: str) -> str:
    """Return one of: mobile | landline | tollfree | unified | invalid."""
    if not local:
        return "invalid"
    if local.startswith(("0800", "800", "9200")):
        return "tollfree"
    if local.startswith(("0920", "0900", "0700")):
        return "unified"
    rules = COUNTRY_RULES.get(country)
    if not rules:
        return "mobile" if 8 <= len(local) <= 12 else "invalid"
    if len(local) not in rules["local_len"]:
        return "invalid"
    for pref in rules["mobile_prefixes"]:
        if local.startswith(pref):
            return "mobile"
    return "landline"


def extract_phones_from_text(text: str, country: str) -> list[str]:
    """Fallback: scan free-text (about/bio) for phone-like sequences."""
    if not text:
        return []
    out: set[str] = set()
    for m in re.findall(r"\+?\d[\d\s\-\(\)\.]{6,20}\d", str(text)):
        norm = normalize_local_phone(m, country)
        if norm:
            out.add(norm)
    return list(out)

def call_actor_with_rotation(actor: str, run_input: dict, search_id: str,
                             timeout_secs: int = 900,
                             progress_cb=None) -> list:
    """Run an Apify actor, rotating keys on quota/auth errors.
    progress_cb(status, items_count) is called every few seconds while the run is live."""
    key = get_active_key()
    if not key:
        raise RuntimeError("لا توجد مفاتيح Apify نشطة. أضف مفتاحاً من /addkey أو من الواجهة.")
    import time as _time
    for _ in range(10):
        try:
            log_job(search_id, "info", f"Apify actor: {actor} — key: {key['label']}")
            client = ApifyClient(key["api_key"])
            # Start async so we can poll and stream progress back to the user.
            run = client.actor(actor).start(run_input=run_input, timeout_secs=timeout_secs)
            run_id = run["id"]
            dataset_id = run["defaultDatasetId"]
            deadline = _time.time() + timeout_secs
            last_status = ""
            while _time.time() < deadline:
                info = client.run(run_id).get()
                status = info.get("status", "")
                stats = info.get("stats") or {}
                # cheap item count via dataset info
                ds_info = client.dataset(dataset_id).get() or {}
                item_count = ds_info.get("itemCount", 0)
                if progress_cb and status != last_status:
                    try: progress_cb(status, item_count)
                    except Exception: pass
                    last_status = status
                elif progress_cb:
                    try: progress_cb(status, item_count)
                    except Exception: pass
                if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                    break
                _time.sleep(6)
            info = client.run(run_id).get()
            if info.get("status") != "SUCCEEDED":
                raise RuntimeError(f"Apify run {info.get('status')}: {info.get('statusMessage','')}")
            items = list(client.dataset(dataset_id).iterate_items())
            api("PATCH", "/api/public/bot/keys", json={"id": key["id"], "increment_usage": True})
            heartbeat("apify", "online", {"actor": actor, "items": len(items)})
            return items
        except Exception as e:
            msg = str(e)
            log_job(search_id, "warn", f"خطأ في {key['label']}: {msg[:200]}")
            if any(t in msg.lower() for t in ["402", "429", "insufficient", "usage limit", "unauthorized", "monthly-usage", "payment"]):
                api("PATCH", "/api/public/bot/keys",
                    json={"id": key["id"], "status": "exhausted", "last_error": msg[:500]})
                key = get_active_key()
                if not key:
                    raise RuntimeError("انتهت جميع مفاتيح Apify — أضف مفتاحاً جديداً")
                log_job(search_id, "info", f"الانتقال للمفتاح: {key['label']}")
                continue
            raise
    raise RuntimeError("فشل بعد استنفاد كل المفاتيح")

def run_facebook_scrape(keyword: str, country: str, max_pages: int, search_id: str,
                        progress_cb=None) -> list[dict]:
    """
    Two-stage scrape:
      1) Ads Library → collect Facebook page URLs of active ads
      2) apify/facebook-pages-scraper → phone + website per page
    """
    search_url = build_facebook_ads_library_url(keyword, country)
    log_job(search_id, "info", f"المرحلة 1/2: فتح مكتبة الإعلانات — {search_url}")
    if progress_cb: progress_cb("🔗 المرحلة 1/2: فتح مكتبة إعلانات فيسبوك...")
    ads_input = {
        "urls": [{"url": search_url}],
        "count": max_pages,
        "limitPerSource": max_pages,
        "scrapeAdDetails": False,
    }

    def ads_cb(status, n):
        if progress_cb:
            progress_cb(f"🔗 المرحلة 1/2: مكتبة الإعلانات — {status} — {n} إعلان حتى الآن")

    ads = call_actor_with_rotation("curious_coder/facebook-ads-library-scraper", ads_input, search_id,
                                   progress_cb=ads_cb)
    page_urls = extract_page_urls(ads)
    log_job(search_id, "info", f"تم استخراج {len(page_urls)} رابط صفحة فريد من {len(ads)} إعلان")
    update_job(search_id, progress=40,
               progress_message=f"جُمعت {len(page_urls)} صفحة — استخراج الأرقام...",
               pages_found=len(page_urls))
    if progress_cb:
        progress_cb(f"✅ المرحلة 1/2 انتهت — {len(ads)} إعلان → {len(page_urls)} صفحة فريدة\n\n📞 المرحلة 2/2: فحص الصفحات لاستخراج الأرقام...")
    if not page_urls:
        return []

    pages_input = {
        "startUrls": [{"url": u} for u in page_urls],
        "scrapeAbout": True,
        "maxResults": len(page_urls),
    }

    def pages_cb(status, n):
        if progress_cb:
            pct = int(min(99, (n / max(1, len(page_urls))) * 100))
            progress_cb(f"📞 المرحلة 2/2: {status} — {n}/{len(page_urls)} صفحة ({pct}%)")

    pages = call_actor_with_rotation("apify/facebook-pages-scraper", pages_input, search_id,
                                     timeout_secs=1200, progress_cb=pages_cb)
    log_job(search_id, "info", f"المرحلة 2/2: تم فحص {len(pages)} صفحة")

    results: dict[str, dict] = {}
    for p in pages:
        if not isinstance(p, dict):
            continue
        candidates: list[str] = []
        for field in ("phone", "phoneNumber", "phone_number"):
            v = p.get(field)
            if v:
                candidates.append(str(v))
        for field in ("about", "info", "bio", "description", "categories", "address"):
            v = p.get(field)
            if isinstance(v, str) and v:
                candidates.extend(extract_phones_from_text(v, country))
            elif isinstance(v, list):
                candidates.extend(extract_phones_from_text(" ".join(str(x) for x in v), country))

        website = p.get("website") or ""
        has_store = bool(website) and "facebook.com" not in str(website).lower()
        page_url = p.get("pageUrl") or p.get("url") or p.get("facebookUrl")
        page_name = p.get("title") or p.get("pageName") or p.get("name")

        for raw in candidates:
            phone = normalize_local_phone(raw, country)
            if not phone:
                continue
            kind = classify_phone(phone, country)
            if kind == "invalid":
                continue
            if phone in results:
                continue
            results[phone] = {
                "phone": phone,
                "kind": kind,
                "page_url": page_url,
                "page_name": page_name,
                "has_store": has_store,
            }
    return list(results.values())



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

    # A single "live progress" message we keep editing as work advances.
    progress_msg = None
    if chat_id:
        try:
            progress_msg = await app.bot.send_message(
                chat_id=chat_id,
                text=f"🚀 <b>بدأ البحث</b>\n🔎 {keyword} | 🌍 {country}\n⏳ التحضير...",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    loop = asyncio.get_event_loop()
    last_edit = {"text": "", "at": 0.0}
    import time as _time

    def push_progress(text: str):
        """Thread-safe: schedules a telegram edit from the worker thread."""
        if not progress_msg:
            return
        now = _time.time()
        if text == last_edit["text"] or now - last_edit["at"] < 3:
            return
        last_edit["text"] = text
        last_edit["at"] = now
        full = (f"⚙️ <b>{keyword}</b> | 🌍 {country}\n\n{text}")
        try:
            asyncio.run_coroutine_threadsafe(
                app.bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id,
                                          text=full, parse_mode=ParseMode.HTML),
                loop,
            )
        except Exception:
            pass

    try:
        log_job(sid, "info", f"بدء البحث: '{keyword}' — {country}")
        update_job(sid, progress=5, progress_message="جاري تشغيل Apify...")

        items = await loop.run_in_executor(
            None, run_facebook_scrape, keyword, country, max_pages, sid, push_progress
        )

        mobiles   = [i for i in items if i.get("kind") == "mobile"]
        landlines = [i for i in items if i.get("kind") == "landline"]
        tollfree  = [i for i in items if i.get("kind") in ("tollfree", "unified")]
        no_store_mobiles = [i for i in mobiles if not i.get("has_store")]
        log_job(sid, "info",
                f"استخرج {len(items)} — 📱 جوال: {len(mobiles)} "
                f"(بدون متجر: {len(no_store_mobiles)}) — 📞 أرضي: {len(landlines)} "
                f"— ☎️ مجاني/موحد: {len(tollfree)}")
        update_job(sid, progress=90, progress_message=f"رفع {len(items)} رقم...")
        push_progress(f"💾 رفع {len(items)} رقم إلى قاعدة البيانات...")

        result = api("POST", "/api/public/bot/numbers",
                     json={"search_id": sid, "country": country, "items": items})
        new_count = result.get("new_count", 0)
        total = result.get("total", 0)

        update_job(sid, status="completed", progress=100, progress_message="مكتمل",
                   numbers_found=total, numbers_new=new_count, finished=True)
        log_job(sid, "info", f"مكتمل — {total} رقم إجمالي، {new_count} جديد")

        # Build output file: phone + page URL + page name (TSV, opens as table in Excel).
        header = "phone\tpage_url\tpage_name\thas_store\n"
        lines = [
            f"{i['phone']}\t{i.get('page_url') or ''}\t{(i.get('page_name') or '').replace(chr(9),' ')}\t{'1' if i.get('has_store') else '0'}"
            for i in mobiles
        ]
        tsv_bytes = (header + "\n".join(lines)).encode("utf-8")

        if chat_id:
            summary = (
                f"✅ <b>اكتمل البحث</b>\n\n"
                f"🔎 الكلمة: <code>{keyword}</code>\n"
                f"🌍 الدولة: {country}\n"
                f"📄 صفحات مفحوصة: {len(items) and (job.get('pages_found') or '—')}\n"
                f"📱 جوال (واتساب): <b>{len(mobiles)}</b>\n"
                f"   ↳ بدون متجر خارجي: {len(no_store_mobiles)}\n"
                f"📞 أرضي: {len(landlines)}\n"
                f"☎️ مجاني/موحّد: {len(tollfree)}\n"
                f"🆕 جديد في قاعدة البيانات: <b>{new_count}</b>"
            )
            try:
                if progress_msg:
                    await app.bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id,
                                                    text=summary, parse_mode=ParseMode.HTML)
                else:
                    await app.bot.send_message(chat_id=chat_id, text=summary, parse_mode=ParseMode.HTML)
            except Exception:
                await app.bot.send_message(chat_id=chat_id, text=summary, parse_mode=ParseMode.HTML)
            if mobiles:
                await app.bot.send_document(
                    chat_id=chat_id,
                    document=io.BytesIO(tsv_bytes),
                    filename=f"{keyword}_{country}_{datetime.now().strftime('%Y%m%d_%H%M')}.tsv",
                    caption=f"📱 {len(mobiles)} رقم جوال + روابط الصفحات",
                )

    except Exception as e:
        err = str(e)
        log.exception("Job %s failed", sid)
        log_job(sid, "error", err)
        update_job(sid, status="failed", error_message=err[:500], finished=True)
        if chat_id:
            try:
                await app.bot.send_message(chat_id=chat_id, text=f"❌ فشل البحث: {err[:200]}")
            except Exception:
                pass


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
