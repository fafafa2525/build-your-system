"""
Apify Platform — Layer 1
========================
لوحة تحكم Apify كاملة داخل تلجرام:

  📦 Actors   🔎 Discover  ⭐ Featured  ❤️ Favorites  🕘 Recent
  📂 Categories  ▶️ Running Jobs  📊 Usage  💰 Balance  🔑 API Keys
  📄 Datasets  🧹 Storage  📥 Imports  📤 Exports  🤖 Templates

هذه الطبقة عامة تماماً: تدير Apify نفسه (actors, runs, datasets, storage,
usage, keys). طبقة الأعمال (Meta / Google Maps / …) تبقى في bot.py وتستهلك
الـ actors المسجّلة هنا.

الاعتماديات تُحقن من bot.py عبر init().
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests
from apify_client import ApifyClient
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import actor_hub

log = logging.getLogger("apify_platform")

_D: dict[str, Any] = {}


def init(*, api, call_actor, get_active_key, is_allowed, countries) -> None:
    _D.update(api=api, call_actor=call_actor, get_active_key=get_active_key,
              is_allowed=is_allowed, countries=countries)


PAGE = 8
APIFY_API = "https://api.apify.com/v2"

CATEGORIES: list[tuple[str, str]] = [
    ("meta", "🅵 Meta"), ("google", "🔵 Google"), ("maps", "🗺️ Maps"),
    ("tiktok", "🎵 TikTok"), ("instagram", "📸 Instagram"), ("linkedin", "💼 LinkedIn"),
    ("ecommerce", "🛒 Ecommerce"), ("social", "💬 Social"), ("leads", "🎯 Leads"),
    ("seo", "🔍 SEO"), ("email", "✉️ Email"), ("phone", "📱 Phone"),
    ("jobs", "🧑‍💼 Jobs"), ("news", "📰 News"), ("monitoring", "📡 Monitoring"),
    ("reviews", "⭐ Reviews"), ("video", "🎬 Video"), ("ai", "🤖 AI"), ("other", "📦 Other"),
]
CAT_LABEL = dict(CATEGORIES)

FEATURED_SETS: list[tuple[str, str]] = [
    ("leads", "🎯 أفضل استخراج عملاء"),
    ("stable", "🛡️ الأكثر استقراراً"),
    ("cheap", "💸 الأرخص"),
    ("ai", "🤖 أفضل AI"),
]


# ---------------- helpers ----------------

def _client() -> ApifyClient:
    key = _D["get_active_key"]()
    if not key:
        raise RuntimeError("لا توجد مفاتيح Apify نشطة. أضف مفتاحاً من قسم 🔑 المفاتيح.")
    return ApifyClient(key["api_key"])


def _token() -> str:
    key = _D["get_active_key"]()
    if not key:
        raise RuntimeError("لا توجد مفاتيح Apify نشطة.")
    return key["api_key"]


def _rest(path: str) -> dict:
    r = requests.get(f"{APIFY_API}{path}", headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
    r.raise_for_status()
    return (r.json() or {}).get("data") or {}


def _reg_get(resource: str, params: Optional[dict] = None) -> list[dict]:
    qs = {"resource": resource, **(params or {})}
    return _D["api"]("GET", "/api/public/bot/apify", params=qs).get("items") or []


def _reg_post(resource: str, body: dict) -> dict:
    return _D["api"]("POST", f"/api/public/bot/apify?resource={resource}", json=body).get("item") or {}


def _reg_patch(resource: str, body: dict) -> dict:
    return _D["api"]("PATCH", f"/api/public/bot/apify?resource={resource}", json=body).get("item") or {}


def _reg_delete(resource: str, params: dict) -> None:
    _D["api"]("DELETE", "/api/public/bot/apify", params={"resource": resource, **params})


def _fmt_dt(v: Optional[str]) -> str:
    if not v:
        return "—"
    try:
        return str(v)[:16].replace("T", " ")
    except Exception:
        return "—"


def _nav(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    kb = [list(r) for r in rows]
    kb.append([InlineKeyboardButton("⬅️ منصة Apify", callback_data="ap:home"),
               InlineKeyboardButton("🏠 الرئيسية", callback_data="m:home")])
    return InlineKeyboardMarkup(kb)


async def _show(update: Update, text: str, kb: InlineKeyboardMarkup) -> None:
    q = update.callback_query
    if q:
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except Exception:
            pass
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ---------------- home ----------------

HOME_TEXT = (
    "⚙️ <b>منصة Apify</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "كل ما تحتاجه لإدارة Apify من مكان واحد — بدون فتح الموقع.\n"
    "<i>الأدوات · الاستكشاف · التشغيلات · البيانات · الاستهلاك · المفاتيح</i>"
)


def home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Actors", callback_data="ap:acts:0"),
         InlineKeyboardButton("🔎 Discover", callback_data="ap:disc")],
        [InlineKeyboardButton("⭐ Featured", callback_data="ap:feat"),
         InlineKeyboardButton("❤️ Favorites", callback_data="ap:fav")],
        [InlineKeyboardButton("🕘 Recent", callback_data="ap:rec"),
         InlineKeyboardButton("📂 Categories", callback_data="ap:cats")],
        [InlineKeyboardButton("▶️ Running Jobs", callback_data="ap:jobs:all"),
         InlineKeyboardButton("🤖 Templates", callback_data="ap:tpl")],
        [InlineKeyboardButton("📊 Usage", callback_data="ap:usage"),
         InlineKeyboardButton("💰 Balance", callback_data="ap:bal")],
        [InlineKeyboardButton("📄 Datasets", callback_data="ap:ds:0"),
         InlineKeyboardButton("🧹 Storage", callback_data="ap:st")],
        [InlineKeyboardButton("📥 Imports", callback_data="ap:imp"),
         InlineKeyboardButton("📤 Exports", callback_data="ap:exp")],
        [InlineKeyboardButton("🔑 API Keys", callback_data="ap:keys")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="m:home")],
    ])


async def platform_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _D["is_allowed"](update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return
    if update.callback_query:
        await update.callback_query.answer()
    await _show(update, HOME_TEXT, home_kb())


# ---------------- actor lists ----------------

def _actor_rows(items: list[dict], page: int, back: str) -> InlineKeyboardMarkup:
    start = page * PAGE
    chunk = items[start:start + PAGE]
    rows = [[InlineKeyboardButton(f"{a.get('name') or a['actor_id']}", callback_data=f"ap:a:{start + i}")]
            for i, a in enumerate(chunk)]
    pager = []
    if page > 0:
        pager.append(InlineKeyboardButton("◀️ السابق", callback_data=f"{back}:{page-1}"))
    if start + PAGE < len(items):
        pager.append(InlineKeyboardButton("التالي ▶️", callback_data=f"{back}:{page+1}"))
    if pager:
        rows.append(pager)
    return _nav(*rows)


async def _list_actors(update: Update, ctx, items: list[dict], title: str, page: int, back: str) -> None:
    ctx.user_data["ap_list"] = items
    if not items:
        await _show(update, f"{title}\n\nلا توجد عناصر بعد.", _nav())
        return
    lines = [title, "━━━━━━━━━━━━━━━━━━━━",
             f"العدد: <b>{len(items)}</b> — الصفحة {page+1}/{max(1, (len(items)+PAGE-1)//PAGE)}", ""]
    for i, a in enumerate(items[page*PAGE:(page+1)*PAGE], start=page*PAGE + 1):
        lines.append(f"{i}. <b>{a.get('name') or a['actor_id']}</b>"
                     f"{' ⭐' if a.get('is_featured') else ''}\n"
                     f"   <code>{a['actor_id']}</code> · {a.get('price_note') or 'حسب الاستهلاك'}")
    await _show(update, "\n".join(lines), _actor_rows(items, page, back))


async def screen_actors(update: Update, ctx, page: int) -> None:
    items = await asyncio.to_thread(_reg_get, "actors")
    await _list_actors(update, ctx, items, "📦 <b>Actors المسجّلة في النظام</b>", page, "ap:acts")


async def screen_categories(update: Update, ctx) -> None:
    rows, row = [], []
    for code, label in CATEGORIES:
        row.append(InlineKeyboardButton(label, callback_data=f"ap:cat:{code}:0"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    await _show(update, "📂 <b>التصنيفات</b>\n━━━━━━━━━━━━━━━━━━━━\nاختر تصنيفاً لعرض أدواته.", _nav(*rows))


async def screen_category(update: Update, ctx, code: str, page: int) -> None:
    items = await asyncio.to_thread(_reg_get, "actors", {"category": code})
    await _list_actors(update, ctx, items, f"📂 <b>{CAT_LABEL.get(code, code)}</b>", page, f"ap:cat:{code}")


async def screen_featured(update: Update, ctx) -> None:
    rows = [[InlineKeyboardButton(label, callback_data=f"ap:fs:{code}")] for code, label in FEATURED_SETS]
    rows.append([InlineKeyboardButton("🏆 كل المميّزة", callback_data="ap:fs:all")])
    await _show(update, "⭐ <b>Featured</b>\n━━━━━━━━━━━━━━━━━━━━\nقوائم مختارة من أفضل الأدوات.", _nav(*rows))


async def screen_featured_set(update: Update, ctx, code: str) -> None:
    items = await asyncio.to_thread(_reg_get, "actors", {"featured": "1"})
    if code == "leads":
        items = [a for a in items if "leads" in (a.get("tags") or [])]
    elif code == "cheap":
        items = sorted(items, key=lambda a: a.get("price_note") or "")
    elif code == "ai":
        items = [a for a in items if a.get("category") == "ai" or "ai" in (a.get("tags") or [])]
    elif code == "stable":
        items = sorted(items, key=lambda a: -(a.get("run_count") or 0))
    label = dict(FEATURED_SETS).get(code, "🏆 كل المميّزة")
    await _list_actors(update, ctx, items, f"⭐ <b>{label}</b>", 0, "ap:fs0")


async def screen_favorites(update: Update, ctx) -> None:
    uid = update.effective_user.id
    favs = await asyncio.to_thread(_reg_get, "favorites", {"telegram_user_id": uid})
    items = [{"actor_id": f["actor_id"], "name": f.get("name") or f["actor_id"]} for f in favs]
    await _list_actors(update, ctx, items, "❤️ <b>المفضّلة</b>", 0, "ap:fav0")


async def screen_recent(update: Update, ctx) -> None:
    runs = await asyncio.to_thread(_reg_get, "runs", {"limit": 30})
    seen, items = set(), []
    for r in runs:
        if r["actor_id"] in seen:
            continue
        seen.add(r["actor_id"])
        items.append({"actor_id": r["actor_id"],
                      "name": r.get("actor_name") or r["actor_id"],
                      "price_note": f"آخر تشغيل: {_fmt_dt(r.get('started_at'))}"})
    await _list_actors(update, ctx, items, "🕘 <b>آخر الأدوات المُشغّلة</b>", 0, "ap:rec0")


# ---------------- actor card ----------------

async def screen_actor_card(update: Update, ctx, idx: int) -> None:
    items = ctx.user_data.get("ap_list") or []
    if idx >= len(items):
        await _show(update, "انتهت الصلاحية — افتح القائمة من جديد.", _nav())
        return
    a = items[idx]
    actor_id = a["actor_id"]
    ctx.user_data["ap_actor"] = a

    schema = await asyncio.to_thread(actor_hub.get_input_schema, actor_id)
    prefill = a.get("default_input") or {}
    merged = {**actor_hub.build_prefill(schema), **(prefill if isinstance(prefill, dict) else {})}
    ctx.user_data["ap_input"] = merged

    runs = await asyncio.to_thread(_reg_get, "runs", {"limit": 1})
    mine = [r for r in runs if r["actor_id"] == actor_id]
    last = _fmt_dt(mine[0]["started_at"]) if mine else (_fmt_dt(a.get("last_run_at")) if a.get("last_run_at") else "—")

    text = (
        f"🧩 <b>{a.get('name') or actor_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<code>{actor_id}</code>\n\n"
        f"📝 {a.get('description') or 'بدون وصف'}\n"
        f"💵 السعر: {a.get('price_note') or 'حسب الاستهلاك'}\n"
        f"📂 التصنيف: {CAT_LABEL.get(a.get('category') or 'other', a.get('category') or '—')}\n"
        f"🕘 آخر تشغيل: {last}\n\n"
        f"<b>المدخلات:</b>\n{actor_hub.describe_schema(schema)}\n\n"
        f"<b>Input الحالي:</b>\n<pre>{json.dumps(merged, ensure_ascii=False, indent=1)[:1200]}</pre>"
    )
    kb = _nav(
        [InlineKeyboardButton("▶️ تشغيل", callback_data="ap:run"),
         InlineKeyboardButton("✏️ تعديل المدخلات", callback_data="ap:edit")],
        [InlineKeyboardButton("❤️ مفضلة", callback_data="ap:favadd"),
         InlineKeyboardButton("🤖 حفظ كقالب", callback_data="ap:tplsave")],
    )
    await _show(update, text, kb)


# ---------------- running ----------------

async def run_actor(update: Update, ctx, run_input: dict) -> None:
    a = ctx.user_data.get("ap_actor") or {}
    actor_id = a.get("actor_id")
    if not actor_id:
        await _show(update, "اختر Actor أولاً.", _nav())
        return
    chat_id = update.effective_chat.id
    app = ctx.application
    loop = asyncio.get_event_loop()
    msg = await app.bot.send_message(chat_id, f"🚀 تشغيل <b>{actor_id}</b>…", parse_mode=ParseMode.HTML)

    record = {}
    try:
        record = await asyncio.to_thread(_reg_post, "runs", {
            "actor_id": actor_id, "actor_name": a.get("name"), "status": "RUNNING",
            "input": run_input, "telegram_user_id": update.effective_user.id,
            "telegram_chat_id": chat_id, "provider": "platform",
        })
    except Exception as e:
        log.warning("run record failed: %s", e)

    started = time.time()
    last = {"t": 0.0, "s": ""}

    def progress(status: str, count: int):
        now = time.time()
        line = (f"⚙️ <b>{actor_id}</b>\n\nالحالة: <code>{status}</code>\n"
                f"النتائج: <b>{count}</b>\nالمدة: {int(now-started)}s")
        if line == last["s"] or now - last["t"] < 3:
            return
        last.update(t=now, s=line)
        try:
            asyncio.run_coroutine_threadsafe(
                app.bot.edit_message_text(chat_id=chat_id, message_id=msg.message_id,
                                          text=line, parse_mode=ParseMode.HTML), loop)
        except Exception:
            pass

    try:
        items = await loop.run_in_executor(
            None, lambda: _D["call_actor"](actor_id, run_input, None, 1800, progress))
    except Exception as e:
        if record.get("id"):
            await asyncio.to_thread(_reg_patch, "runs", {
                "id": record["id"], "status": "FAILED", "error_message": str(e)[:500],
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": int(time.time() - started)})
        await app.bot.send_message(chat_id, f"❌ فشل التشغيل: {str(e)[:300]}", reply_markup=_nav())
        return

    if record.get("id"):
        await asyncio.to_thread(_reg_patch, "runs", {
            "id": record["id"], "status": "SUCCEEDED", "items_count": len(items),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": int(time.time() - started)})
    try:
        await asyncio.to_thread(_reg_post, "actors", {
            "actor_id": actor_id, "name": a.get("name") or actor_id,
            "category": a.get("category") or "other",
            "description": a.get("description"),
            "price_note": a.get("price_note"),
            "default_input": run_input,
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "run_count": (a.get("run_count") or 0) + 1,
        })
    except Exception as e:
        log.warning("actor upsert failed: %s", e)

    # reuse Actor Hub export menu
    ctx.user_data["ah_items"] = items
    ctx.user_data["ah_actor"] = actor_id
    ctx.user_data["ah_fields"] = set()
    await actor_hub._send_field_menu(app, chat_id, ctx, items, actor_id)


# ---------------- jobs / usage / balance / storage ----------------

STATUS_LABEL = {
    "RUNNING": "▶️ يعمل", "READY": "⏳ منتظر", "SUCCEEDED": "✅ ناجح",
    "FAILED": "❌ فشل", "ABORTED": "⛔ ملغى", "TIMING-OUT": "⏱️ ينتهي",
}


def _fetch_runs(status: Optional[str]) -> list[dict]:
    c = _client()
    kw: dict[str, Any] = {"limit": 20, "desc": True}
    if status:
        kw["status"] = status
    return [{
        "id": r.get("id"),
        "actor": r.get("actId"),
        "status": r.get("status"),
        "started": str(r.get("startedAt") or "")[:16].replace("T", " "),
        "dataset": r.get("defaultDatasetId"),
        "usage": (r.get("usageTotalUsd") or 0),
    } for r in c.runs().list(**kw).items]


async def screen_jobs(update: Update, ctx, status: str) -> None:
    st = None if status == "all" else status
    try:
        runs = await asyncio.to_thread(_fetch_runs, st)
    except Exception as e:
        await _show(update, f"❌ {str(e)[:250]}", _nav())
        return
    ctx.user_data["ap_runs"] = runs
    filters_row = [
        InlineKeyboardButton("الكل", callback_data="ap:jobs:all"),
        InlineKeyboardButton("▶️", callback_data="ap:jobs:RUNNING"),
        InlineKeyboardButton("✅", callback_data="ap:jobs:SUCCEEDED"),
        InlineKeyboardButton("❌", callback_data="ap:jobs:FAILED"),
        InlineKeyboardButton("⛔", callback_data="ap:jobs:ABORTED"),
    ]
    if not runs:
        await _show(update, "▶️ <b>التشغيلات</b>\n\nلا توجد تشغيلات بهذه الحالة.", _nav(filters_row))
        return
    lines = ["▶️ <b>التشغيلات</b>", "━━━━━━━━━━━━━━━━━━━━"]
    rows = []
    for i, r in enumerate(runs[:PAGE]):
        lines.append(f"{i+1}. {STATUS_LABEL.get(r['status'], r['status'])} — <code>{r['actor']}</code>\n"
                     f"   🕘 {r['started']} · 💵 ${r['usage']:.3f}")
        btns = [InlineKeyboardButton(f"{i+1} 📄 النتائج", callback_data=f"ap:jres:{i}")]
        if r["status"] in ("RUNNING", "READY"):
            btns.append(InlineKeyboardButton("⛔ إلغاء", callback_data=f"ap:jcancel:{i}"))
        else:
            btns.append(InlineKeyboardButton("🔁 إعادة", callback_data=f"ap:jretry:{i}"))
        rows.append(btns)
    rows.append(filters_row)
    await _show(update, "\n".join(lines), _nav(*rows))


async def job_action(update: Update, ctx, action: str, idx: int) -> None:
    runs = ctx.user_data.get("ap_runs") or []
    if idx >= len(runs):
        await _show(update, "انتهت الصلاحية.", _nav())
        return
    r = runs[idx]
    if action == "jcancel":
        try:
            await asyncio.to_thread(lambda: _client().run(r["id"]).abort())
            await update.callback_query.answer("تم الإلغاء", show_alert=True)
        except Exception as e:
            await update.callback_query.answer(str(e)[:180], show_alert=True)
        await screen_jobs(update, ctx, "all")
        return

    if action == "jretry":
        try:
            info = await asyncio.to_thread(lambda: _client().run(r["id"]).get() or {})
            inp = await asyncio.to_thread(
                lambda: _client().key_value_store(info.get("defaultKeyValueStoreId")).get_record("INPUT"))
            run_input = (inp or {}).get("value") or {}
        except Exception:
            run_input = {}
        ctx.user_data["ap_actor"] = {"actor_id": r["actor"], "name": r["actor"]}
        await run_actor(update, ctx, run_input)
        return

    # jres → download dataset items
    try:
        items = await asyncio.to_thread(
            lambda: list(_client().dataset(r["dataset"]).iterate_items(limit=1000)))
    except Exception as e:
        await update.callback_query.answer(str(e)[:180], show_alert=True)
        return
    ctx.user_data["ah_items"] = items
    ctx.user_data["ah_actor"] = r["actor"]
    ctx.user_data["ah_fields"] = set()
    await actor_hub._send_field_menu(ctx.application, update.effective_chat.id, ctx, items, r["actor"])


def _usage_stats() -> dict:
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).isoformat()
    runs = _reg_get("runs", {"since": since, "limit": 1000})
    def total(days: int) -> tuple[int, float]:
        cut = now - timedelta(days=days)
        sel = [r for r in runs if (r.get("started_at") or "") >= cut.isoformat()]
        return len(sel), sum(float(r.get("cost_usd") or 0) for r in sel)
    d_n, d_c = total(1)
    w_n, w_c = total(7)
    m_n, m_c = total(30)
    items = sum(int(r.get("items_count") or 0) for r in runs)
    durs = [int(r["duration_seconds"]) for r in runs if r.get("duration_seconds")]
    ok = sum(1 for r in runs if r.get("status") == "SUCCEEDED")
    fail = sum(1 for r in runs if r.get("status") == "FAILED")
    apify_month = 0.0
    try:
        apify_month = float(_rest("/users/me/usage/monthly").get("totalUsageCreditsUsdAfterVolumeDiscount") or 0)
    except Exception:
        pass
    return {"d": (d_n, d_c), "w": (w_n, w_c), "m": (m_n, m_c), "items": items,
            "avg": int(sum(durs) / len(durs)) if durs else 0, "ok": ok, "fail": fail,
            "apify_month": apify_month}


async def screen_usage(update: Update, ctx) -> None:
    try:
        s = await asyncio.to_thread(_usage_stats)
    except Exception as e:
        await _show(update, f"❌ {str(e)[:250]}", _nav())
        return
    await _show(update,
        "📊 <b>الاستهلاك</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🗓️ اليوم: <b>{s['d'][0]}</b> تشغيل\n"
        f"📆 الأسبوع: <b>{s['w'][0]}</b> تشغيل\n"
        f"🗓️ الشهر: <b>{s['m'][0]}</b> تشغيل\n\n"
        f"📄 إجمالي النتائج (30 يوم): <b>{s['items']:,}</b>\n"
        f"⏱️ متوسط زمن التشغيل: <b>{s['avg']}s</b>\n"
        f"✅ ناجح: {s['ok']} · ❌ فاشل: {s['fail']}\n\n"
        f"💵 استهلاك Apify هذا الشهر: <b>${s['apify_month']:.2f}</b>",
        _nav([InlineKeyboardButton("💰 الرصيد", callback_data="ap:bal")]))


async def screen_balance(update: Update, ctx) -> None:
    try:
        me = await asyncio.to_thread(_rest, "/users/me")
        limits = await asyncio.to_thread(_rest, "/users/me/limits")
        monthly = await asyncio.to_thread(_rest, "/users/me/usage/monthly")
    except Exception as e:
        await _show(update, f"❌ تعذّر جلب الرصيد: {str(e)[:250]}", _nav())
        return
    used = float(monthly.get("totalUsageCreditsUsdAfterVolumeDiscount") or 0)
    max_usd = float((limits.get("limits") or {}).get("maxMonthlyUsageUsd") or 0)
    cur = (limits.get("current") or {})
    plan = (me.get("plan") or {}).get("id") or "—"
    remaining = max(max_usd - used, 0) if max_usd else 0
    bar_n = int((used / max_usd) * 10) if max_usd else 0
    bar = "█" * bar_n + "░" * (10 - bar_n)
    await _show(update,
        "💰 <b>رصيد Apify</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 الحساب: <code>{me.get('username') or '—'}</code>\n"
        f"📦 الباقة: <b>{plan}</b>\n\n"
        f"{bar}\n"
        f"💵 مستهلك هذا الشهر: <b>${used:.2f}</b>\n"
        f"🎯 الحد الشهري: <b>${max_usd:.2f}</b>\n"
        f"🟢 المتبقّي المتوقّع: <b>${remaining:.2f}</b>\n\n"
        f"🖥️ عمليات نشطة: {cur.get('activeActorJobCount', 0)}\n"
        f"💾 تخزين الداتاست: {int(cur.get('datasetStorageBytes', 0))/1_048_576:.1f} MB",
        _nav([InlineKeyboardButton("🔑 المفاتيح", callback_data="ap:keys"),
              InlineKeyboardButton("📊 الاستهلاك", callback_data="ap:usage")]))


async def screen_datasets(update: Update, ctx, page: int) -> None:
    try:
        ds = await asyncio.to_thread(lambda: _client().datasets().list(limit=40, desc=True).items)
    except Exception as e:
        await _show(update, f"❌ {str(e)[:250]}", _nav())
        return
    ctx.user_data["ap_ds"] = ds
    if not ds:
        await _show(update, "📄 <b>Datasets</b>\n\nلا توجد داتاسِت.", _nav())
        return
    start = page * PAGE
    lines = ["📄 <b>Datasets</b>", "━━━━━━━━━━━━━━━━━━━━"]
    rows = []
    for i, d in enumerate(ds[start:start + PAGE], start=start):
        lines.append(f"{i+1}. <code>{d.get('name') or d.get('id')}</code> — "
                     f"{d.get('itemCount', 0)} عنصر · {str(d.get('createdAt'))[:10]}")
        rows.append([InlineKeyboardButton(f"{i+1} ⬇️ تحميل", callback_data=f"ap:dsdl:{i}"),
                     InlineKeyboardButton("🗑 حذف", callback_data=f"ap:dsdel:{i}")])
    pager = []
    if page > 0:
        pager.append(InlineKeyboardButton("◀️", callback_data=f"ap:ds:{page-1}"))
    if start + PAGE < len(ds):
        pager.append(InlineKeyboardButton("▶️", callback_data=f"ap:ds:{page+1}"))
    if pager:
        rows.append(pager)
    await _show(update, "\n".join(lines), _nav(*rows))


async def dataset_action(update: Update, ctx, action: str, idx: int) -> None:
    ds = ctx.user_data.get("ap_ds") or []
    if idx >= len(ds):
        await update.callback_query.answer("انتهت الصلاحية", show_alert=True)
        return
    d = ds[idx]
    if action == "dsdel":
        try:
            await asyncio.to_thread(lambda: _client().dataset(d["id"]).delete())
            await update.callback_query.answer("تم الحذف", show_alert=True)
        except Exception as e:
            await update.callback_query.answer(str(e)[:180], show_alert=True)
        await screen_datasets(update, ctx, 0)
        return
    try:
        items = await asyncio.to_thread(lambda: list(_client().dataset(d["id"]).iterate_items(limit=1000)))
    except Exception as e:
        await update.callback_query.answer(str(e)[:180], show_alert=True)
        return
    ctx.user_data["ah_items"] = items
    ctx.user_data["ah_actor"] = d.get("name") or d["id"]
    ctx.user_data["ah_fields"] = set()
    await actor_hub._send_field_menu(ctx.application, update.effective_chat.id, ctx, items,
                                     d.get("name") or d["id"])


async def screen_storage(update: Update, ctx) -> None:
    def _load():
        c = _client()
        ds = c.datasets().list(limit=1000).items
        kv = c.key_value_stores().list(limit=1000).items
        rq = c.request_queues().list(limit=1000).items
        cur = (_rest("/users/me/limits").get("current") or {})
        return ds, kv, rq, cur
    try:
        ds, kv, rq, cur = await asyncio.to_thread(_load)
    except Exception as e:
        await _show(update, f"❌ {str(e)[:250]}", _nav())
        return
    total_items = sum(int(d.get("itemCount") or 0) for d in ds)
    await _show(update,
        "🧹 <b>التخزين</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 Datasets: <b>{len(ds)}</b> ({total_items:,} عنصر)\n"
        f"🗝️ Key-Value Stores: <b>{len(kv)}</b>\n"
        f"📥 Request Queues: <b>{len(rq)}</b>\n\n"
        f"💾 حجم الداتاست: {int(cur.get('datasetStorageBytes', 0))/1_048_576:.1f} MB\n"
        f"💾 حجم KV: {int(cur.get('keyValueStoreStorageBytes', 0))/1_048_576:.1f} MB\n"
        f"💾 حجم الطوابير: {int(cur.get('requestQueueStorageBytes', 0))/1_048_576:.1f} MB",
        _nav([InlineKeyboardButton("📄 Datasets", callback_data="ap:ds:0")]))


# ---------------- keys ----------------

async def screen_keys(update: Update, ctx) -> None:
    try:
        keys = (await asyncio.to_thread(_D["api"], "GET", "/api/public/bot/keys")).get("keys") or []
    except Exception as e:
        await _show(update, f"❌ {str(e)[:250]}", _nav())
        return
    lines = ["🔑 <b>مفاتيح Apify</b>", "━━━━━━━━━━━━━━━━━━━━",
             f"النشطة: <b>{len(keys)}</b>", ""]
    for k in keys:
        lines.append(f"• <b>{k['label']}</b> — {k.get('usage_count', 0)} استخدام")
    lines.append("\nلإضافة مفتاح جديد اضغط الزر بالأسفل أو أرسل:\n<code>/addkey apify_api_XXXX الاسم</code>")
    await _show(update, "\n".join(lines),
                _nav([InlineKeyboardButton("➕ إضافة مفتاح", callback_data="ap:keyadd")],
                     [InlineKeyboardButton("💰 الرصيد", callback_data="ap:bal")]))


# ---------------- templates ----------------

async def screen_templates(update: Update, ctx) -> None:
    tpls = await asyncio.to_thread(_reg_get, "templates", {"telegram_user_id": update.effective_user.id})
    ctx.user_data["ap_tpls"] = tpls
    if not tpls:
        await _show(update,
            "🤖 <b>القوالب</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            "لا توجد قوالب بعد.\nافتح أي Actor ← «🤖 حفظ كقالب» ليصبح تشغيله بضغطة واحدة.", _nav())
        return
    rows = [[InlineKeyboardButton(f"▶️ {t['name'][:35]}", callback_data=f"ap:tplrun:{i}"),
             InlineKeyboardButton("🗑", callback_data=f"ap:tpldel:{i}")]
            for i, t in enumerate(tpls[:PAGE])]
    lines = ["🤖 <b>القوالب الجاهزة</b>", "━━━━━━━━━━━━━━━━━━━━"]
    for i, t in enumerate(tpls[:PAGE], 1):
        lines.append(f"{i}. <b>{t['name']}</b> — <code>{t['actor_id']}</code> · {t.get('use_count', 0)}×")
    await _show(update, "\n".join(lines), _nav(*rows))


async def template_action(update: Update, ctx, action: str, idx: int) -> None:
    tpls = ctx.user_data.get("ap_tpls") or []
    if idx >= len(tpls):
        await update.callback_query.answer("انتهت الصلاحية", show_alert=True)
        return
    t = tpls[idx]
    if action == "tpldel":
        await asyncio.to_thread(_reg_delete, "templates", {"id": t["id"]})
        await update.callback_query.answer("تم الحذف")
        await screen_templates(update, ctx)
        return
    await asyncio.to_thread(_reg_patch, "templates", {"id": t["id"], "use_count": (t.get("use_count") or 0) + 1})
    ctx.user_data["ap_actor"] = {"actor_id": t["actor_id"], "name": t["name"]}
    await run_actor(update, ctx, t.get("input") or {})


# ---------------- discover / imports / exports ----------------

async def screen_discover(update: Update, ctx) -> None:
    ctx.user_data["ap_await"] = "discover"
    await _show(update,
        "🔎 <b>Discover — متجر Apify</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل كلمة بحث وسأعرض لك كل الأدوات المطابقة داخل المتجر.\n\n"
        "<i>أمثلة: facebook · linkedin · email · maps · tiktok · shopify</i>",
        _nav())


async def screen_imports(update: Update, ctx) -> None:
    ctx.user_data["ap_await"] = "import"
    await _show(update,
        "📥 <b>Imports</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل رابط الـ Actor من موقع Apify أو معرفه لإضافته إلى النظام:\n"
        "<code>https://apify.com/clockworks/tiktok-scraper</code>\n"
        "<code>clockworks/tiktok-scraper</code>",
        _nav())


async def screen_exports(update: Update, ctx) -> None:
    items = ctx.user_data.get("ah_items") or []
    if not items:
        await _show(update,
            "📤 <b>Exports</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            "لا توجد نتائج في الجلسة الحالية.\n"
            "شغّل أي Actor أو افتح داتاست من 📄 Datasets ثم عد إلى هنا.", _nav())
        return
    rows = [[InlineKeyboardButton("📄 CSV", callback_data="ap:ex:csv"),
             InlineKeyboardButton("📊 Excel", callback_data="ap:ex:xls")],
            [InlineKeyboardButton("{ } JSON", callback_data="ap:ex:json"),
             InlineKeyboardButton("📑 TSV", callback_data="ap:ex:tsv")],
            [InlineKeyboardButton("🧠 جهات الاتصال فقط", callback_data="ap:ex:contacts")]]
    await _show(update,
        f"📤 <b>Exports</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"النتائج الحالية: <b>{len(items)}</b> عنصر من <code>{ctx.user_data.get('ah_actor','—')}</code>\n"
        f"اختر صيغة التصدير:", _nav(*rows))


def _rows_cols(ctx, kind: str) -> tuple[list[dict], list[str]]:
    items = ctx.user_data.get("ah_items") or []
    if kind == "contacts":
        rows = actor_hub.smart_extract(items)
        return rows, ["name", "phone", "whatsapp", "all_phones", "email", "website"]
    rows = [it if isinstance(it, dict) else {"value": it} for it in items]
    return rows, actor_hub._all_fields(items)


async def export_action(update: Update, ctx, kind: str) -> None:
    q = update.callback_query
    items = ctx.user_data.get("ah_items") or []
    if not items:
        await q.answer("لا توجد نتائج", show_alert=True)
        return
    base = str(ctx.user_data.get("ah_actor", "export")).replace("/", "_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    if kind == "json":
        raw = json.dumps(items, ensure_ascii=False, indent=1).encode("utf-8")
        await q.message.reply_document(io.BytesIO(raw), filename=f"{base}_{stamp}.json")
        return

    rows, cols = _rows_cols(ctx, kind)
    if not rows:
        await q.answer("لا توجد بيانات لهذه الصيغة", show_alert=True)
        return

    if kind in ("tsv", "contacts"):
        data = actor_hub._tsv(rows, cols)
        ext = "tsv"
    else:
        def cell(v):
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            s = str(v if v is not None else "").replace('"', '""').replace("\n", " ")
            return f'"{s}"'
        body = "\n".join(",".join(cell(r.get(c)) for c in cols) for r in rows)
        data = ("\ufeff" + ",".join(cols) + "\n" + body).encode("utf-8")
        ext = "csv"  # Excel opens UTF-8 BOM CSV natively
    await q.message.reply_document(io.BytesIO(data), filename=f"{base}_{stamp}.{ext}",
                                   caption=f"📤 {len(rows)} صف × {len(cols)} حقل")


# ---------------- text input handler ----------------

def _parse_actor_id(text: str) -> Optional[str]:
    t = text.strip()
    m = re.search(r"apify\.com/([\w\-.]+)/([\w\-.]+)", t)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    if re.fullmatch(r"[\w\-.]+[/~][\w\-.]+", t):
        return t.replace("~", "/")
    return None


async def text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    mode = ctx.user_data.pop("ap_await", None)
    if not mode:
        return
    text = (update.message.text or "").strip()

    if mode == "discover":
        msg = await update.message.reply_text("⏳ جاري البحث في متجر Apify…")
        try:
            found = await asyncio.to_thread(lambda: _client().store().list(search=text, limit=20).items)
        except Exception as e:
            await msg.edit_text(f"❌ {str(e)[:250]}")
            return
        items = [{
            "actor_id": f"{a.get('username')}/{a.get('name')}",
            "name": a.get("title") or a.get("name"),
            "description": (a.get("description") or "")[:150],
            "category": (a.get("categories") or ["other"])[0].lower() if a.get("categories") else "other",
            "price_note": a.get("currentPricingInfo", {}).get("pricingModel") if isinstance(a.get("currentPricingInfo"), dict) else None,
        } for a in found]
        if not items:
            await msg.edit_text("لم أجد أدوات مطابقة. جرّب كلمة أخرى.")
            return
        ctx.user_data["ap_list"] = items
        await msg.delete()
        await _list_actors(update, ctx, items, f"🔎 <b>نتائج: {text}</b>", 0, "ap:disc0")
        return

    if mode == "import":
        actor_id = _parse_actor_id(text)
        if not actor_id:
            await update.message.reply_text("❌ رابط أو معرّف غير صالح. أعد المحاولة من 📥 Imports.")
            return
        try:
            info = await asyncio.to_thread(lambda: _client().actor(actor_id).get() or {})
        except Exception as e:
            await update.message.reply_text(f"❌ تعذّر جلب الـ Actor: {str(e)[:200]}")
            return
        item = await asyncio.to_thread(_reg_post, "actors", {
            "actor_id": actor_id,
            "name": info.get("title") or actor_id,
            "description": (info.get("description") or "")[:400],
            "category": "other",
            "price_note": None,
        })
        ctx.user_data["ap_list"] = [item]
        await update.message.reply_text(
            f"✅ تمت إضافة <b>{item.get('name')}</b> إلى النظام.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧩 فتح الأداة", callback_data="ap:a:0")],
                [InlineKeyboardButton("⬅️ منصة Apify", callback_data="ap:home")]]))
        return

    if mode == "edit":
        raw = re.sub(r"^```(?:json)?|```$", "", text).strip()
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("JSON يجب أن يكون object")
        except Exception as e:
            ctx.user_data["ap_await"] = "edit"
            await update.message.reply_text(f"❌ JSON غير صالح: {str(e)[:150]}\nأعد الإرسال.")
            return
        ctx.user_data["ap_input"] = data
        await run_actor(update, ctx, data)
        return

    if mode == "tplname":
        a = ctx.user_data.get("ap_actor") or {}
        await asyncio.to_thread(_reg_post, "templates", {
            "name": text[:60], "actor_id": a.get("actor_id"),
            "input": ctx.user_data.get("ap_input") or {},
            "telegram_user_id": update.effective_user.id})
        await update.message.reply_text(
            f"✅ تم حفظ القالب <b>{text[:60]}</b>", parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🤖 القوالب", callback_data="ap:tpl")]]))
        return

    if mode == "keyadd":
        if not text.startswith("apify_api_"):
            ctx.user_data["ap_await"] = "keyadd"
            await update.message.reply_text("❌ المفتاح يجب أن يبدأ بـ apify_api_ — أعد الإرسال.")
            return
        parts = text.split()
        try:
            await asyncio.to_thread(_D["api"], "POST", "/api/public/bot/keys",
                                    json={"api_key": parts[0], "label": " ".join(parts[1:]) or None})
        except Exception as e:
            await update.message.reply_text(f"❌ {str(e)[:200]}")
            return
        await update.message.reply_text("✅ تمت إضافة المفتاح.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔑 المفاتيح", callback_data="ap:keys")]]))
        return


# ---------------- router ----------------

async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not await _D["is_allowed"](q.from_user.id):
        await q.edit_message_text("❌ غير مصرح لك.")
        return
    parts = q.data.split(":")
    action = parts[1]
    arg = parts[2] if len(parts) > 2 else None
    arg2 = parts[3] if len(parts) > 3 else None

    try:
        if action == "home":
            await platform_home(update, ctx)
        elif action == "acts":
            await screen_actors(update, ctx, int(arg or 0))
        elif action == "cats":
            await screen_categories(update, ctx)
        elif action == "cat":
            await screen_category(update, ctx, arg or "other", int(arg2 or 0))
        elif action == "feat":
            await screen_featured(update, ctx)
        elif action == "fs":
            await screen_featured_set(update, ctx, arg or "all")
        elif action in ("fav", "fav0"):
            await screen_favorites(update, ctx)
        elif action in ("rec", "rec0"):
            await screen_recent(update, ctx)
        elif action in ("disc", "disc0", "fs0"):
            if action == "disc":
                await screen_discover(update, ctx)
            else:
                await _list_actors(update, ctx, ctx.user_data.get("ap_list") or [],
                                   "🔎 <b>النتائج</b>", int(arg or 0), f"ap:{action}")
        elif action == "a":
            await screen_actor_card(update, ctx, int(arg or 0))
        elif action == "run":
            await run_actor(update, ctx, ctx.user_data.get("ap_input") or {})
        elif action == "edit":
            ctx.user_data["ap_await"] = "edit"
            await q.message.reply_text(
                "✏️ أرسل الآن JSON الجديد للمدخلات:\n"
                f"<pre>{json.dumps(ctx.user_data.get('ap_input') or {}, ensure_ascii=False, indent=1)[:1500]}</pre>",
                parse_mode=ParseMode.HTML)
        elif action == "favadd":
            a = ctx.user_data.get("ap_actor") or {}
            await asyncio.to_thread(_reg_post, "favorites", {
                "telegram_user_id": q.from_user.id, "actor_id": a.get("actor_id"), "name": a.get("name")})
            await q.answer("❤️ أُضيفت للمفضلة", show_alert=True)
        elif action == "tplsave":
            ctx.user_data["ap_await"] = "tplname"
            await q.message.reply_text("🤖 أرسل اسماً للقالب:")
        elif action == "tpl":
            await screen_templates(update, ctx)
        elif action in ("tplrun", "tpldel"):
            await template_action(update, ctx, action, int(arg or 0))
        elif action == "jobs":
            await screen_jobs(update, ctx, arg or "all")
        elif action in ("jres", "jcancel", "jretry"):
            await job_action(update, ctx, action, int(arg or 0))
        elif action == "usage":
            await screen_usage(update, ctx)
        elif action == "bal":
            await screen_balance(update, ctx)
        elif action == "ds":
            await screen_datasets(update, ctx, int(arg or 0))
        elif action in ("dsdl", "dsdel"):
            await dataset_action(update, ctx, action, int(arg or 0))
        elif action == "st":
            await screen_storage(update, ctx)
        elif action == "keys":
            await screen_keys(update, ctx)
        elif action == "keyadd":
            ctx.user_data["ap_await"] = "keyadd"
            await q.message.reply_text("🔑 أرسل المفتاح:\n<code>apify_api_XXXX اسم اختياري</code>",
                                       parse_mode=ParseMode.HTML)
        elif action == "imp":
            await screen_imports(update, ctx)
        elif action == "exp":
            await screen_exports(update, ctx)
        elif action == "ex":
            await export_action(update, ctx, arg or "tsv")
    except Exception as e:  # pragma: no cover
        log.exception("platform action failed: %s", q.data)
        try:
            await q.message.reply_text(f"❌ خطأ: {str(e)[:250]}", reply_markup=_nav())
        except Exception:
            pass


async def apify_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await platform_home(update, ctx)


def register(app: Application) -> None:
    app.add_handler(CommandHandler("apify", apify_cmd))
    app.add_handler(CallbackQueryHandler(router, pattern=r"^ap:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input), group=5)
