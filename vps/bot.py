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

import actor_hub
import apify_platform
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonCommands,
    Update,
)
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

# Conversation states — Facebook flow
CHOOSE_KEYWORD, CHOOSE_COUNTRY = range(2)
# Conversation states — Google Maps flow
GM_CATEGORY, GM_CITY, GM_COUNTRY = range(10, 13)


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

def log_job(search_id: Optional[str], level: str, message: str, meta: Optional[dict] = None) -> None:
    if not search_id:
        log.info("[%s] %s", level, message)
        return
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

# NOTE: extract_phones_from_text is defined further below (country-aware version).

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

def call_actor_with_rotation(actor: str, run_input: dict, search_id: Optional[str] = None,
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
                # cheap item count via dataset info
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
            if any(t in msg.lower() for t in ["402", "429", "insufficient", "usage limit", "hard limit", "monthly usage", "monthly-usage", "unauthorized", "payment", "quota", "maximum charged results", "charged results must be greater"]):
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
    # One page can run many ads → oversample ads to get more unique pages.
    ads_target = max(max_pages * 3, max_pages)
    ads_input = {
        "urls": [{"url": search_url}],
        "count": ads_target,
        "limitPerSource": ads_target,
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
        email = p.get("email") or p.get("emailAddress")
        if not email:
            for field in ("emails", "contactEmails"):
                v = p.get(field)
                if isinstance(v, list) and v:
                    email = str(v[0]); break

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
                "website": website or None,
                "email": email or None,
            }
    return list(results.values())

# ---------------- Google Maps provider ----------------

GMAPS_ACTOR = os.getenv("APIFY_GMAPS_ACTOR", "compass/crawler-google-places")

def run_gmaps_scrape(category: str, city: str, country: str, max_results: int,
                     search_id: str, progress_cb=None) -> list[dict]:
    """
    Scrape Google Maps for a category in a city/country.
    Uses compass/crawler-google-places; rotates Apify keys via call_actor_with_rotation.
    Returns items shaped for POST /api/public/bot/numbers.
    """
    query = f"{category} in {city}, {country}" if city else f"{category} in {country}"
    if progress_cb:
        progress_cb(f"🗺️ Google Maps — البحث عن: {query}")
    log_job(search_id, "info", f"Google Maps: {query} (max={max_results})")

    run_input = {
        "searchStringsArray": [query],
        "maxCrawledPlacesPerSearch": max_results,
        "language": "ar",
        "skipClosedPlaces": True,
        "scrapeContacts": True,
    }

    def cb(status, n):
        if progress_cb:
            pct = int(min(99, (n / max(1, max_results)) * 100))
            progress_cb(f"🗺️ Google Maps — {status} — {n} نتيجة ({pct}%)")

    places = call_actor_with_rotation(GMAPS_ACTOR, run_input, search_id,
                                       timeout_secs=1200, progress_cb=cb)
    log_job(search_id, "info", f"Google Maps: تم استخراج {len(places)} نشاط")

    results: dict[str, dict] = {}
    for p in places:
        if not isinstance(p, dict):
            continue
        # Collect phone candidates
        candidates: list[str] = []
        for field in ("phone", "phoneNumber", "phoneUnformatted"):
            v = p.get(field)
            if v: candidates.append(str(v))
        for extra in (p.get("additionalInfo") or {}).get("Phone", []) or []:
            if isinstance(extra, dict):
                for v in extra.values():
                    if v: candidates.append(str(v))

        biz_name = p.get("title") or p.get("name")
        category_name = p.get("categoryName") or (p.get("categories") or [None])[0]
        addr = p.get("address")
        loc_city = p.get("city") or city
        rating = p.get("totalScore") or p.get("rating")
        reviews = p.get("reviewsCount") or p.get("reviewCount")
        lat = (p.get("location") or {}).get("lat") if isinstance(p.get("location"), dict) else p.get("latitude")
        lng = (p.get("location") or {}).get("lng") if isinstance(p.get("location"), dict) else p.get("longitude")
        website = p.get("website") or p.get("webUrl")
        gmaps_url = p.get("url") or p.get("googleMapsUrl")
        email = None
        for field in ("emails", "contactEmails"):
            v = p.get(field)
            if isinstance(v, list) and v:
                email = str(v[0]); break
        if not email:
            v = p.get("email")
            if v: email = str(v)
        claim_flag = p.get("claimThisBusiness")
        if claim_flag is None:
            claim_flag = p.get("claim_this_business")

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
                "business_name": biz_name,
                "category": category_name,
                "address": addr,
                "city": loc_city,
                "rating": rating,
                "reviews_count": reviews,
                "latitude": lat,
                "longitude": lng,
                "google_maps_url": gmaps_url,
                "website": website,
                "page_name": biz_name,
                "email": email,
                "claim_this_business": bool(claim_flag) if claim_flag is not None else None,
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
    provider = (job.get("provider") or "facebook").lower()
    city = job.get("city") or ""
    category = job.get("category") or keyword

    header_icon = "🗺️" if provider == "gmaps" else "🔎"
    header_text = f"{header_icon} {category or keyword}"
    if provider == "gmaps" and city:
        header_text += f" — {city}"

    # A single "live progress" message we keep editing as work advances.
    progress_msg = None
    if chat_id:
        try:
            progress_msg = await app.bot.send_message(
                chat_id=chat_id,
                text=f"🚀 <b>بدأ البحث</b>\n{header_text} | 🌍 {country}\n⏳ التحضير...",
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
        full = (f"⚙️ <b>{header_text}</b> | 🌍 {country}\n\n{text}")
        try:
            asyncio.run_coroutine_threadsafe(
                app.bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id,
                                          text=full, parse_mode=ParseMode.HTML),
                loop,
            )
        except Exception:
            pass

    try:
        log_job(sid, "info", f"[{provider}] بدء المهمة: '{keyword}' — {country}")
        update_job(sid, progress=5, progress_message=f"جاري تشغيل {provider}...")

        if provider == "gmaps":
            items = await loop.run_in_executor(
                None, run_gmaps_scrape, category, city, country, max_pages, sid, push_progress
            )
        else:
            items = await loop.run_in_executor(
                None, run_facebook_scrape, keyword, country, max_pages, sid, push_progress
            )

        mobiles   = [i for i in items if i.get("kind") == "mobile"]
        landlines = [i for i in items if i.get("kind") == "landline"]
        tollfree  = [i for i in items if i.get("kind") in ("tollfree", "unified")]
        no_store_mobiles = [i for i in mobiles if not i.get("has_store") and not i.get("website")]
        log_job(sid, "info",
                f"استخرج {len(items)} — 📱 جوال: {len(mobiles)} "
                f"— 📞 أرضي: {len(landlines)} "
                f"— ☎️ مجاني/موحد: {len(tollfree)}")
        update_job(sid, progress=90, progress_message=f"رفع {len(items)} رقم...")
        push_progress(f"💾 رفع {len(items)} رقم إلى قاعدة البيانات...")

        result = api("POST", "/api/public/bot/numbers",
                     json={"search_id": sid, "country": country,
                           "source": provider, "items": items})
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

MENU_TEXT = (
    "👋 <b>AdsBot — منصّة استخراج العملاء</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "اختر ما تريد من الأزرار بالأسفل 👇\n\n"
    "<b>🎯 مصادر العملاء</b>\n"
    "• مكتبة إعلانات فيسبوك — معلنون نشطون\n"
    "• Google Maps — أنشطة محلية\n"
    "• Apify Hub — أي مصدر آخر\n\n"
    "<b>✅ الجودة</b> — فحص أرقام واتساب\n"
    "<b>⚙️ منصة Apify</b> — أدوات، تشغيلات، رصيد، بيانات\n"
    "<b>🔑 المفاتيح</b> — إدارة مفاتيح Apify"
)

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 إعلانات فيسبوك", callback_data="m:search"),
            InlineKeyboardButton("🗺️ Google Maps", callback_data="m:gmaps"),
        ],
        [
            InlineKeyboardButton("✅ فحص واتساب", callback_data="m:validate"),
            InlineKeyboardButton("🧩 Apify Hub", callback_data="m:actor"),
        ],
        [
            InlineKeyboardButton("⚙️ منصة Apify", callback_data="ap:home"),
        ],
        [
            InlineKeyboardButton("🔑 المفاتيح", callback_data="m:keys"),
            InlineKeyboardButton("📦 actors حسابي", callback_data="m:myactors"),
        ],
        [
            InlineKeyboardButton("📈 الإحصائيات", callback_data="m:stats"),
            InlineKeyboardButton("🔁 آخر تشغيل", callback_data="m:lastrun"),
        ],
        [InlineKeyboardButton("❓ المساعدة", callback_data="m:help")],
    ])

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="m:home")]])

async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(
            f"❌ غير مصرح لك.\n\nمعرفك: <code>{update.effective_user.id}</code>\n"
            f"أضفه من الواجهة → الإعدادات → معرفات تلجرام المسموح لها.",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.effective_message.reply_text(
        MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb()
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return
    await update.effective_message.reply_text(
        "❓ <b>دليل الاستخدام</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔍 <b>إعلانات فيسبوك</b> — كلمة مفتاحية + دولة، يجلب المعلنين النشطين وأرقامهم وروابط صفحاتهم.\n\n"
        "🗺️ <b>Google Maps</b> — نشاط + مدينة + دولة، يجلب الأنشطة مع الهاتف والإيميل والموقع.\n\n"
        "✅ <b>فحص واتساب</b> — يتحقق من أرقام آخر بحث (نتائج محفوظة 30 يوماً).\n\n"
        "🧩 <b>Apify Hub</b> — شغّل أي Actor من متجر Apify واحفظ نتائجه في العملاء.\n\n"
        "🔑 <b>المفاتيح</b> — عرض المفاتيح، والإضافة عبر:\n"
        "<code>/addkey apify_api_XXXX الاسم</code>\n\n"
        "⚙️ <b>منصة Apify</b> — لوحة تحكم كاملة: الأدوات، التصنيفات، المفضلة، التشغيلات الجارية، الرصيد، الاستهلاك، الداتاسِت والتخزين (/apify).\n\n"
        "الأوامر: /apify /search /gmaps /validate /actor /myactors /lastrun /keys /addkey /stats /cancel",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb(),
    )

async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles simple menu buttons (non-conversation entries)."""
    q = update.callback_query
    await q.answer()
    if not await is_allowed(q.from_user.id):
        await q.edit_message_text("❌ غير مصرح لك.")
        return
    action = q.data.split(":", 1)[1]
    if action == "home":
        await q.edit_message_text(MENU_TEXT, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
    elif action == "help":
        await help_cmd(update, ctx)
    elif action == "keys":
        await keys_cmd(update, ctx)
    elif action == "stats":
        await stats_cmd(update, ctx)
    elif action == "validate":
        await validate_cmd(update, ctx)
    elif action == "myactors":
        await actor_hub.myactors_cmd(update, ctx)
    elif action == "lastrun":
        await actor_hub.lastrun_cmd(update, ctx)
    elif action == "apify":
        await apify_platform.platform_home(update, ctx)

# /search flow
async def search_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text(
        "🔍 <b>بحث مكتبة إعلانات فيسبوك</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>الخطوة 1 من 2</b> — أرسل الكلمة المفتاحية\n"
        "<i>مثال: مطاعم، عيادة أسنان، أثاث</i>\n\n"
        "/cancel للإلغاء",
        parse_mode=ParseMode.HTML,
    )
    return CHOOSE_KEYWORD

async def search_keyword(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["keyword"] = update.message.text.strip()
    kb = [
        [InlineKeyboardButton(name, callback_data=f"c:{code}") for code, name in COUNTRIES[i:i+3]]
        for i in range(0, len(COUNTRIES), 3)
    ]
    await update.message.reply_text(
        "<b>الخطوة 2 من 2</b> — 🌍 اختر الدولة:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb),
    )
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
        f"✅ <b>تم إنشاء المهمة</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔎 الكلمة: <b>{keyword}</b>\n"
        f"🌍 الدولة: {country}\n"
        f"⏳ الحالة: قيد التنفيذ…\n\n"
        f"سأرسل النتائج فور اكتمال البحث.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb(),
    )
    return ConversationHandler.END

async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "تم الإلغاء ✅", reply_markup=back_kb()
    )
    return ConversationHandler.END

# /gmaps flow — Google Maps source
async def gmaps_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text(
        "🗺️ <b>بحث Google Maps</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>الخطوة 1 من 3</b> — أرسل نوع النشاط\n"
        "<i>مثال: مطاعم، صيدلية، عسل</i>\n\n"
        "/cancel للإلغاء",
        parse_mode=ParseMode.HTML,
    )
    return GM_CATEGORY

async def gmaps_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["gm_category"] = update.message.text.strip()
    await update.message.reply_text(
        "<b>الخطوة 2 من 3</b> — 🏙️ أرسل اسم المدينة:", parse_mode=ParseMode.HTML
    )
    return GM_CITY

async def gmaps_city(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["gm_city"] = update.message.text.strip()
    kb = [
        [InlineKeyboardButton(name, callback_data=f"gc:{code}") for code, name in COUNTRIES[i:i+3]]
        for i in range(0, len(COUNTRIES), 3)
    ]
    await update.message.reply_text(
        "<b>الخطوة 3 من 3</b> — 🌍 اختر الدولة:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return GM_COUNTRY


async def gmaps_country(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    country = q.data.split(":")[1]
    category = ctx.user_data.get("gm_category")
    city = ctx.user_data.get("gm_city")
    if not category or not city:
        await q.edit_message_text("❌ خطأ — ابدأ من جديد بـ /gmaps")
        return ConversationHandler.END
    resp = api("POST", "/api/public/bot/jobs", json={
        "keyword": category,
        "country": country,
        "provider": "gmaps",
        "city": city,
        "category": category,
        "telegram_chat_id": q.message.chat.id,
        "telegram_user_id": q.from_user.id,
    })
    _ = resp.get("job", {})
    await q.edit_message_text(
        f"✅ <b>تم إنشاء مهمة Google Maps</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ النشاط: <b>{category}</b>\n"
        f"🏙️ المدينة: {city}\n"
        f"🌍 الدولة: {country}\n"
        f"⏳ الحالة: قيد التنفيذ…\n\n"
        f"سأرسل النتائج فور اكتمال البحث.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb(),
    )
    return ConversationHandler.END



# /addkey
async def addkey_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return
    if not ctx.args:
        await update.effective_message.reply_text(
            "الاستخدام:\n<code>/addkey apify_api_XXXXXXXX [الاسم]</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    api_key = ctx.args[0].strip()
    label = " ".join(ctx.args[1:]).strip() or None
    try:
        api("POST", "/api/public/bot/keys", json={"api_key": api_key, "label": label})
        await update.effective_message.reply_text("✅ تمت إضافة المفتاح", reply_markup=back_kb())
    except Exception as e:
        await update.effective_message.reply_text(f"❌ {e}")

# /keys
async def keys_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return
    data = api("GET", "/api/public/bot/keys")
    keys = data.get("keys") or []
    if not keys:
        await update.effective_message.reply_text(
            "🔑 لا توجد مفاتيح نشطة.\nأضف واحداً:\n<code>/addkey apify_api_XXXX الاسم</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_kb(),
        )
        return
    lines = [f"🔑 <b>المفاتيح النشطة: {len(keys)}</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for k in keys:
        lines.append(f"• <b>{k['label']}</b> — {k['usage_count']} استخدام")
    lines.append("\nلإضافة مفتاح: <code>/addkey apify_api_XXXX الاسم</code>")
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_kb()
    )

async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return
    await update.effective_message.reply_text(
        "📈 <b>الإحصائيات</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "افتح لوحة التحكم على الويب لعرض الإحصائيات الكاملة والعملاء والتصدير.",
        parse_mode=ParseMode.HTML,
        reply_markup=back_kb(),
    )


# ---------------- Contact Validation Engine (WhatsApp validator) ----------------

WHATSAPP_ACTOR = os.getenv("APIFY_WHATSAPP_ACTOR", "maged120/whatsapp-number-checker")
VALIDATION_TTL_DAYS = int(os.getenv("VALIDATION_TTL_DAYS", "30"))
WHATSAPP_BATCH_SIZE = int(os.getenv("WHATSAPP_BATCH_SIZE", "100"))  # actor max = 100

def to_e164(local: str, country: str) -> Optional[str]:
    """Best-effort E.164 conversion using country dial codes we already know."""
    dial = {
        "DZ": "213", "MA": "212", "TN": "216", "EG": "20", "SA": "966", "AE": "971",
        "KW": "965", "QA": "974", "JO": "962", "IQ": "964", "LY": "218", "FR": "33",
    }.get(country.upper())
    if not dial or not local:
        return None
    s = re.sub(r"\D", "", local)
    if not s:
        return None
    if s.startswith("00"):
        s = s[2:]
    if s.startswith(dial):
        return "+" + s
    # strip leading 0 for national numbers
    s = s.lstrip("0")
    return "+" + dial + s

def validate_whatsapp_batch(numbers_e164: list[str], search_id: Optional[str] = None) -> dict[str, dict]:
    """
    Returns { e164: { status: valid|invalid|error, result: {...}, cached: bool } }.
    1) Ask API for cached results (< 30 days).
    2) Only run the Apify actor for missing numbers.
    3) Upload results back to cache them.
    """
    if not numbers_e164:
        return {}
    out: dict[str, dict] = {}
    # 1. Cache lookup
    try:
        resp = api("GET", "/api/public/bot/validations",
                   params={"validator": "whatsapp", "contact_type": "phone",
                           "values": ",".join(numbers_e164)})
        cached = resp.get("cached") or {}
        missing = resp.get("missing") or numbers_e164
        for v, row in cached.items():
            out[v] = {"status": row.get("status"), "result": row.get("result") or {}, "cached": True}
    except Exception as e:
        log.warning("validation cache lookup failed: %s", e)
        missing = numbers_e164

    if not missing:
        return out

    # 2. Run Apify actor for missing
    actor_input = {
        "phone_numbers": missing,
        "proxy_configuration": {
            "useApifyProxy": True,
            "apifyProxyGroups": ["RESIDENTIAL"],
        },
    }
    log.info("whatsapp actor=%s input_count=%d sample=%s",
             WHATSAPP_ACTOR, len(missing), missing[:3])
    try:
        items = call_actor_with_rotation(
            WHATSAPP_ACTOR,
            actor_input,
            search_id or "validate",
            timeout_secs=900,
        )
        log.info("whatsapp actor returned %d dataset items", len(items or []))
        if items:
            log.info("whatsapp sample item: %s", items[0])
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"[:500]
        log.error("whatsapp actor failed: %s", err_msg)
        for v in missing:
            out[v] = {"status": "error", "result": {}, "cached": False, "error": err_msg}
        # Persist error so dashboard/logs show real cause instead of silent 'error'
        try:
            api("POST", "/api/public/bot/validations",
                json={"validator": "whatsapp", "contact_type": "phone",
                      "ttl_days": 0,
                      "items": [{"contact_value": v, "status": "error",
                                 "error_message": err_msg,
                                 "source_search_id": search_id} for v in missing]})
        except Exception as up_e:
            log.warning("failed to upload error validations: %s", up_e)
        return out

    # 3. Normalize actor output — accept a few common shapes
    def _key(item):
        for k in ("phone_number", "phoneNumber", "phone", "number", "input"):
            if item.get(k):
                return re.sub(r"\D", "", str(item[k]))
        return None
    def _valid(item):
        # maged120: {"is_registered": true/false}
        for k in ("is_registered", "isRegistered", "onWhatsApp", "on_whatsapp",
                  "exists", "isValid", "valid", "registered"):
            if k in item:
                return bool(item[k])
        return None

    result_map: dict[str, dict] = {}
    for it in items or []:
        digits = _key(it)
        if not digits:
            continue
        result_map["+" + digits] = it

    log.info("whatsapp result_map size=%d (missing=%d)", len(result_map), len(missing))

    upload_items = []
    for v in missing:
        raw = result_map.get(v)
        if raw is None:
            # No row for this number in actor output → treat as unknown/invalid
            log.info("whatsapp no result for %s → invalid", v)
            out[v] = {"status": "invalid", "result": {}, "cached": False}
            upload_items.append({"contact_value": v, "status": "invalid", "result": {},
                                 "source_search_id": search_id})
            continue
        is_valid = _valid(raw)
        if is_valid is None:
            status = "error"
            err = f"unrecognized actor output keys: {list(raw.keys())[:6]}"
            log.warning("whatsapp %s → error: %s", v, err)
            out[v] = {"status": "error", "result": raw, "cached": False, "error": err}
            upload_items.append({"contact_value": v, "status": "error", "result": raw,
                                 "error_message": err, "source_search_id": search_id})
        else:
            status = "valid" if is_valid else "invalid"
            out[v] = {"status": status, "result": raw, "cached": False}
            upload_items.append({"contact_value": v, "status": status, "result": raw,
                                 "source_search_id": search_id})

    try:
        api("POST", "/api/public/bot/validations",
            json={"validator": "whatsapp", "contact_type": "phone",
                  "ttl_days": VALIDATION_TTL_DAYS, "items": upload_items})
    except Exception as e:
        log.warning("validation upload failed: %s", e)
    return out

async def validate_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/validate — validate the phone numbers from the caller's most recent completed search."""
    if not await is_allowed(update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return
    uid = update.effective_user.id
    log.info("validate_cmd: fetching numbers for telegram_user_id=%s", uid)
    try:
        # Reuse the numbers endpoint to fetch the caller's last search numbers
        resp = api("GET", "/api/public/bot/numbers",
                   params={"telegram_user_id": uid, "limit": 500})
    except Exception as e:
        log.warning("validate_cmd: numbers fetch failed: %s", e)
        await update.effective_message.reply_text(f"⚠️ فشل جلب الأرقام: {e}")
        return
    items = resp.get("items") or []
    log.info("validate_cmd: got %d items from /numbers endpoint", len(items))
    if not items:
        await update.effective_message.reply_text(
            f"لم أجد أرقاماً حديثة لهذا الحساب (uid={uid}).\n"
            "شغّل /search أولاً وانتظر اكتماله ثم استخدم /validate.\n"
            "لو لسّا يظهر فارغ بعد بحث ناجح: انشر آخر تحديثات لوحة التحكم من زر Publish."
        )
        return

    status_msg = await update.effective_message.reply_text(
        f"🔎 جاري التحقق من {len(items)} رقم عبر واتساب…"
    )

    # Build (e164, original) pairs
    pairs = []
    for it in items:
        e164 = to_e164(it.get("phone", ""), it.get("country") or "")
        if e164:
            pairs.append((e164, it))
    if not pairs:
        await status_msg.edit_text("لا يمكن تحويل الأرقام لصيغة دولية.")
        return

    # Run in batches (actor cap = 100)
    results: dict[str, dict] = {}
    batch = WHATSAPP_BATCH_SIZE
    last_err: Optional[str] = None
    for i in range(0, len(pairs), batch):
        chunk = [p[0] for p in pairs[i:i+batch]]
        r = await asyncio.to_thread(validate_whatsapp_batch, chunk, None)
        results.update(r)
        for v in r.values():
            if v.get("status") == "error" and v.get("error"):
                last_err = v["error"]
        cached_n = sum(1 for v in results.values() if v.get("cached"))
        valid_n = sum(1 for v in results.values() if v.get("status") == "valid")
        try:
            await status_msg.edit_text(
                f"🔎 التحقق: {len(results)}/{len(pairs)} — ✅ {valid_n} صالح — 💾 {cached_n} من الكاش"
            )
        except Exception:
            pass

    valid_pairs = [(e, it) for (e, it) in pairs
                   if results.get(e, {}).get("status") == "valid"]
    invalid_n = sum(1 for v in results.values() if v.get("status") == "invalid")
    err_n = sum(1 for v in results.values() if v.get("status") == "error")

    if not valid_pairs:
        msg = f"انتهى التحقق: 0 صالح / {invalid_n} غير مسجّل / {err_n} خطأ."
        if last_err:
            msg += f"\n\n⚠️ سبب الأخطاء:\n{last_err[:400]}"
        await status_msg.edit_text(msg)
        return

    # Build TSV of valid-only
    header = "phone\te164\tpage_url\tpage_name\n"
    lines = [header]
    for e164, it in valid_pairs:
        lines.append(f"{it.get('phone','')}\t{e164}\t{it.get('page_url','')}\t{it.get('page_name','')}\n")
    buf = io.BytesIO("".join(lines).encode("utf-8"))
    buf.name = f"whatsapp_valid_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.tsv"

    await status_msg.edit_text(
        f"✅ {len(valid_pairs)} رقم واتساب مؤكّد / {invalid_n} غير مسجّل / {err_n} خطأ."
    )
    await update.message.reply_document(document=buf, filename=buf.name)


# ---------------- Main ----------------

async def post_init(app: Application) -> None:
    heartbeat("vps", "online")
    heartbeat("telegram_bot", "online")
    asyncio.create_task(worker_loop(app))
    asyncio.create_task(heartbeat_loop())
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "القائمة الرئيسية"),
            BotCommand("search", "بحث إعلانات فيسبوك"),
            BotCommand("gmaps", "بحث Google Maps"),
            BotCommand("validate", "فحص أرقام واتساب"),
            BotCommand("apify", "⚙️ منصة Apify"),
            BotCommand("actor", "Apify Actor Hub"),
            BotCommand("myactors", "actors حسابي"),
            BotCommand("lastrun", "آخر تشغيل"),
            BotCommand("keys", "المفاتيح"),
            BotCommand("addkey", "إضافة مفتاح"),
            BotCommand("stats", "الإحصائيات"),
            BotCommand("help", "المساعدة"),
            BotCommand("cancel", "إلغاء العملية"),
        ])
        await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)
    log.info("Bot ready — worker + heartbeat running")

def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("search", search_start),
                      CallbackQueryHandler(search_start, pattern=r"^m:search$")],
        states={
            CHOOSE_KEYWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_keyword)],
            CHOOSE_COUNTRY: [CallbackQueryHandler(search_country, pattern=r"^c:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    gmaps_conv = ConversationHandler(
        entry_points=[CommandHandler("gmaps", gmaps_start),
                      CallbackQueryHandler(gmaps_start, pattern=r"^m:gmaps$")],
        states={
            GM_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, gmaps_category)],
            GM_CITY:     [MessageHandler(filters.TEXT & ~filters.COMMAND, gmaps_city)],
            GM_COUNTRY:  [CallbackQueryHandler(gmaps_country, pattern=r"^gc:")],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(conv)
    app.add_handler(gmaps_conv)

    app.add_handler(CommandHandler("addkey", addkey_cmd))
    app.add_handler(CommandHandler("keys", keys_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("validate", validate_cmd))

    # ---- Universal Apify Actor Hub (additive, does not touch existing flows) ----
    actor_hub.init(
        api=api,
        call_actor=call_actor_with_rotation,
        get_active_key=get_active_key,
        is_allowed=is_allowed,
        countries=COUNTRIES,
        cancel_cmd=cancel_cmd,
    )
    actor_hub.register(app)

    # ---- Apify Platform (Layer 1): full Apify control panel ----
    apify_platform.init(
        api=api,
        call_actor=call_actor_with_rotation,
        get_active_key=get_active_key,
        is_allowed=is_allowed,
        countries=COUNTRIES,
    )
    apify_platform.register(app)

    # Menu buttons last so conversation entry points (m:search / m:gmaps / m:actor) win
    app.add_handler(CallbackQueryHandler(menu_cb, pattern=r"^m:"))
    return app

def main() -> None:
    app = build_app()
    log.info("Starting AdsBot — connecting to %s", LOVABLE_API_URL)
    app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=[signal.SIGINT, signal.SIGTERM])

if __name__ == "__main__":
    main()
