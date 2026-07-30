"""
Universal Apify Actor Hub
=========================
يسمح بتشغيل *أي* Actor من Apify مباشرة من تلجرام:

  /actor            → بحث في متجر Apify / actors حسابك / معرف مباشر
  /myactors         → actors الموجودة في حسابك
  /lastrun          → إعادة إرسال نتائج آخر تشغيل

بعد انتهاء التشغيل يعرض البوت كل الحقول الموجودة في النتائج ويترك لك
الاختيار: كل الحقول، أو حقول محددة، أو استخراج ذكي (هاتف/واتساب/إيميل/موقع)،
أو JSON خام، أو حفظ في قاعدة بيانات الـ Leads.

هذا الملف مستقل تماماً — لا يعدّل أي منطق قائم (Meta / GMaps / Validate).
يتم حقن الاعتماديات من bot.py عبر init().
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Callable, Optional

from apify_client import ApifyClient
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

log = logging.getLogger("actor_hub")

# ---------------- injected deps ----------------
_D: dict[str, Any] = {}


def init(*, api, call_actor, get_active_key, is_allowed, countries, cancel_cmd) -> None:
    _D.update(
        api=api,
        call_actor=call_actor,
        get_active_key=get_active_key,
        is_allowed=is_allowed,
        countries=countries,
        cancel_cmd=cancel_cmd,
    )


AH_QUERY, AH_INPUT = range(700, 702)

MAX_LIST = 8
MAX_FIELDS = 30

# ---------------- smart extraction ----------------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
WA_RE = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=)(\+?\d{6,20})", re.I)
PHONE_RE = re.compile(r"(?:\+|00)\d[\d\s\-().]{6,20}\d|\b0\d[\d\s\-]{6,15}\d\b")
SOCIAL_HOSTS = ("facebook.com", "instagram.com", "tiktok.com", "twitter.com", "x.com",
                "youtube.com", "linkedin.com", "wa.me", "whatsapp.com", "t.me")
NAME_KEYS = ("name", "title", "pagename", "fullname", "businessname", "companyname", "nickname")
SITE_KEYS = ("website", "url", "link", "domain", "websiteuri", "homepage")


def _walk(obj: Any, out: list[str], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out, depth + 1)


def _pick(item: dict, keys: tuple[str, ...]) -> str:
    for k, v in item.items():
        if isinstance(v, str) and v.strip() and k.lower().replace("_", "") in keys:
            return v.strip()
    return ""


def _clean_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw)
    if d.startswith("00"):
        d = d[2:]
    return d if 8 <= len(d) <= 15 else ""


def smart_extract(items: list[dict]) -> list[dict]:
    """يستخرج أي وسيلة تواصل حقيقية من أي شكل بيانات مهما كان الـ Actor."""
    rows: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            it = {"value": it}
        blob: list[str] = []
        _walk(it, blob)
        text = "\n".join(blob)

        emails = sorted({e.lower() for e in EMAIL_RE.findall(text)})
        was = sorted({_clean_phone(w) for w in WA_RE.findall(text)} - {""})
        phones = sorted({_clean_phone(p) for p in PHONE_RE.findall(text)} - {""})
        sites = sorted({
            s for s in blob
            if s.startswith("http") and not any(h in s.lower() for h in SOCIAL_HOSTS)
        })
        name = _pick(it, NAME_KEYS)
        site = _pick(it, SITE_KEYS) or (sites[0] if sites else "")

        if not (emails or was or phones or site):
            continue
        rows.append({
            "name": name,
            "phone": (was or phones or [""])[0],
            "whatsapp": was[0] if was else "",
            "all_phones": ",".join(dict.fromkeys(was + phones)),
            "email": emails[0] if emails else "",
            "website": site,
        })
    return rows


# ---------------- Apify helpers ----------------

def _client() -> ApifyClient:
    key = _D["get_active_key"]()
    if not key:
        raise RuntimeError("لا توجد مفاتيح Apify نشطة. أضف مفتاحاً عبر /addkey")
    return ApifyClient(key["api_key"])


def search_store(query: str) -> list[dict]:
    c = _client()
    res = c.store().list(search=query, limit=MAX_LIST).items
    return [{
        "id": f"{a.get('username')}/{a.get('name')}",
        "title": a.get("title") or a.get("name"),
        "runs": (a.get("stats") or {}).get("totalRuns", 0),
    } for a in res]


def list_my_actors() -> list[dict]:
    c = _client()
    res = c.actors().list(limit=MAX_LIST, desc=True).items
    return [{
        "id": f"{a.get('username')}/{a.get('name')}" if a.get("username") else a.get("id"),
        "title": a.get("title") or a.get("name"),
        "runs": (a.get("stats") or {}).get("totalRuns", 0),
    } for a in res]


def get_input_schema(actor_id: str) -> dict:
    """يرجع {'properties':..., 'required':[...]} أو {} إن لم يتوفر."""
    try:
        c = _client()
        build = c.actor(actor_id).default_build().get() or {}
        defn = build.get("actorDefinition") or {}
        schema = defn.get("input")
        if not schema and build.get("inputSchema"):
            schema = json.loads(build["inputSchema"])
        return schema or {}
    except Exception as e:  # pragma: no cover
        log.warning("schema fetch failed for %s: %s", actor_id, e)
        return {}


def build_prefill(schema: dict) -> dict:
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    out: dict[str, Any] = {}
    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        val = spec.get("prefill", spec.get("default"))
        if val is None and name in required:
            t = spec.get("type")
            val = {"string": "", "integer": 10, "number": 10,
                   "boolean": False, "array": [], "object": {}}.get(t, "")
        if val is not None:
            out[name] = val
    return out


def describe_schema(schema: dict) -> str:
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    if not props:
        return "لا يوجد Input Schema معلن — أرسل JSON حسب توثيق الـ Actor."
    lines = []
    for name, spec in list(props.items())[:18]:
        if not isinstance(spec, dict):
            continue
        star = "⭐" if name in required else "•"
        lines.append(f"{star} <code>{name}</code> ({spec.get('type','?')}) — {(spec.get('title') or '')[:45]}")
    if len(props) > 18:
        lines.append(f"… و{len(props)-18} حقل آخر")
    return "\n".join(lines)


# ---------------- Telegram flow ----------------

async def _guard(update: Update) -> bool:
    if not await _D["is_allowed"](update.effective_user.id):
        await update.effective_message.reply_text("❌ غير مصرح لك.")
        return False
    return True


async def actor_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _guard(update):
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
    await update.effective_message.reply_text(
        "🧩 <b>Apify Actor Hub</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل واحدة مما يلي:\n"
        "• كلمة بحث في متجر Apify (مثال: <code>instagram scraper</code>)\n"
        "• <code>mine</code> لعرض actors حسابك\n"
        "• معرف actor مباشرة (مثال: <code>apify/web-scraper</code>)\n\n"
        "/cancel للإلغاء",
        parse_mode=ParseMode.HTML,
    )
    return AH_QUERY


async def actor_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = (update.message.text or "").strip()
    loop = asyncio.get_event_loop()

    # معرف مباشر
    if ("/" in q or "~" in q) and " " not in q:
        return await _show_actor(update, ctx, q.replace("~", "/"))

    msg = await update.message.reply_text("⏳ جاري الجلب من Apify...")
    try:
        if q.lower() in ("mine", "حسابي", "my"):
            items = await loop.run_in_executor(None, list_my_actors)
        else:
            items = await loop.run_in_executor(None, search_store, q)
    except Exception as e:
        await msg.edit_text(f"❌ خطأ: {str(e)[:250]}")
        return AH_QUERY

    if not items:
        await msg.edit_text("لم أجد نتائج. جرّب كلمة أخرى أو أرسل معرف actor مباشرة.")
        return AH_QUERY

    ctx.user_data["ah_list"] = items
    kb = [[InlineKeyboardButton(f"{i+1}. {a['title'][:40]} ({a['runs']} runs)",
                                callback_data=f"ah:a:{i}")] for i, a in enumerate(items)]
    await msg.edit_text("اختر Actor:", reply_markup=InlineKeyboardMarkup(kb))
    return AH_QUERY


async def actor_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    qy = update.callback_query
    await qy.answer()
    idx = int(qy.data.split(":")[2])
    items = ctx.user_data.get("ah_list") or []
    if idx >= len(items):
        await qy.edit_message_text("انتهت الصلاحية، أعد /actor")
        return ConversationHandler.END
    return await _show_actor(update, ctx, items[idx]["id"])


async def _show_actor(update: Update, ctx: ContextTypes.DEFAULT_TYPE, actor_id: str) -> int:
    send = (update.callback_query.edit_message_text if update.callback_query
            else update.message.reply_text)
    loop = asyncio.get_event_loop()
    schema = await loop.run_in_executor(None, get_input_schema, actor_id)
    prefill = build_prefill(schema)
    ctx.user_data["ah_actor"] = actor_id
    ctx.user_data["ah_prefill"] = prefill
    pretty = json.dumps(prefill, ensure_ascii=False, indent=2)[:2500]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ تشغيل بالمدخلات الافتراضية", callback_data="ah:run")]])
    await send(
        f"🧩 <b>{actor_id}</b>\n\n<b>الحقول:</b>\n{describe_schema(schema)}\n\n"
        f"<b>Input المقترح:</b>\n<pre>{pretty}</pre>\n\n"
        "أرسل JSON معدّل الآن، أو اضغط تشغيل.",
        parse_mode=ParseMode.HTML, reply_markup=kb,
    )
    return AH_INPUT


async def actor_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON يجب أن يكون object")
    except Exception as e:
        await update.message.reply_text(f"❌ JSON غير صالح: {str(e)[:150]}\nأعد الإرسال أو /cancel")
        return AH_INPUT
    return await _run(update, ctx, data)


async def actor_run_default(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return await _run(update, ctx, ctx.user_data.get("ah_prefill") or {})


async def _run(update: Update, ctx: ContextTypes.DEFAULT_TYPE, run_input: dict) -> int:
    actor_id = ctx.user_data.get("ah_actor")
    if not actor_id:
        await update.effective_message.reply_text("ابدأ من /actor")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    app = ctx.application
    loop = asyncio.get_event_loop()
    msg = await app.bot.send_message(chat_id, f"🚀 تشغيل <b>{actor_id}</b>…", parse_mode=ParseMode.HTML)
    last = {"t": 0.0, "s": ""}

    def progress(status: str, count: int):
        now = time.time()
        line = f"⚙️ <b>{actor_id}</b>\n\nالحالة: <code>{status}</code>\nالنتائج: <b>{count}</b>"
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
        await app.bot.send_message(chat_id, f"❌ فشل التشغيل: {str(e)[:300]}")
        return ConversationHandler.END

    ctx.user_data["ah_items"] = items
    ctx.user_data["ah_fields"] = set()
    await _send_field_menu(app, chat_id, ctx, items, actor_id)
    return ConversationHandler.END


def _all_fields(items: list) -> list[str]:
    keys: list[str] = []
    for it in items[:200]:
        if isinstance(it, dict):
            for k in it.keys():
                if k not in keys:
                    keys.append(k)
    return keys[:MAX_FIELDS]


def _fields_kb(ctx: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    fields = ctx.user_data.get("ah_all_fields") or []
    chosen = ctx.user_data.get("ah_fields") or set()
    rows, row = [], []
    for i, f in enumerate(fields):
        row.append(InlineKeyboardButton(("✅ " if f in chosen else "") + f[:18], callback_data=f"ahf:t:{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("📤 تصدير المحدد", callback_data="ahf:export"),
                 InlineKeyboardButton("🗂 كل الحقول", callback_data="ahf:all")])
    rows.append([InlineKeyboardButton("🧠 استخراج ذكي (أرقام/إيميل)", callback_data="ahf:smart")])
    rows.append([InlineKeyboardButton("{ } JSON خام", callback_data="ahf:json"),
                 InlineKeyboardButton("💾 حفظ في Leads", callback_data="ahf:save")])
    return InlineKeyboardMarkup(rows)


async def _send_field_menu(app: Application, chat_id: int, ctx, items: list, actor_id: str) -> None:
    if not items:
        await app.bot.send_message(chat_id, "⚠️ انتهى التشغيل بدون نتائج.")
        return
    fields = _all_fields(items)
    ctx.user_data["ah_all_fields"] = fields
    smart = smart_extract(items)
    sample = json.dumps(items[0], ensure_ascii=False, indent=1)[:900]
    await app.bot.send_message(
        chat_id,
        f"✅ <b>اكتمل</b> — {len(items)} نتيجة من <code>{actor_id}</code>\n"
        f"🧠 نتائج فيها وسيلة تواصل: <b>{len(smart)}</b>\n\n"
        f"<b>عيّنة:</b>\n<pre>{sample}</pre>\n\nاختر ما تريد استخراجه:",
        parse_mode=ParseMode.HTML, reply_markup=_fields_kb(ctx),
    )


def _tsv(rows: list[dict], cols: list[str]) -> bytes:
    def cell(v):
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        return str(v if v is not None else "").replace("\t", " ").replace("\n", " ")
    body = "\n".join("\t".join(cell(r.get(c)) for c in cols) for r in rows)
    return ("\t".join(cols) + "\n" + body).encode("utf-8")


async def field_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    qy = update.callback_query
    await qy.answer()
    action = qy.data.split(":")[1]
    items = ctx.user_data.get("ah_items") or []
    actor_id = ctx.user_data.get("ah_actor", "actor")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = actor_id.replace("/", "_")

    if action == "t":
        i = int(qy.data.split(":")[2])
        fields = ctx.user_data.get("ah_all_fields") or []
        chosen = set(ctx.user_data.get("ah_fields") or set())
        f = fields[i]
        chosen.symmetric_difference_update({f})
        ctx.user_data["ah_fields"] = chosen
        await qy.edit_message_reply_markup(reply_markup=_fields_kb(ctx))
        return

    if not items:
        await qy.message.reply_text("انتهت صلاحية النتائج، شغّل /actor مجدداً.")
        return

    if action in ("export", "all"):
        cols = (ctx.user_data.get("ah_all_fields") if action == "all"
                else [f for f in (ctx.user_data.get("ah_all_fields") or [])
                      if f in (ctx.user_data.get("ah_fields") or set())])
        if not cols:
            await qy.message.reply_text("لم تحدد أي حقل.")
            return
        rows = [it if isinstance(it, dict) else {"value": it} for it in items]
        await qy.message.reply_document(io.BytesIO(_tsv(rows, cols)),
                                        filename=f"{base}_{stamp}.tsv",
                                        caption=f"📤 {len(rows)} صف × {len(cols)} حقل")
        return

    if action == "smart":
        rows = smart_extract(items)
        if not rows:
            await qy.message.reply_text("🧠 لم أجد أي هاتف/واتساب/إيميل في هذه النتائج.")
            return
        ctx.user_data["ah_smart"] = rows
        cols = ["name", "phone", "whatsapp", "all_phones", "email", "website"]
        await qy.message.reply_document(io.BytesIO(_tsv(rows, cols)),
                                        filename=f"{base}_contacts_{stamp}.tsv",
                                        caption=f"🧠 {len(rows)} جهة اتصال مستخرجة")
        return

    if action == "json":
        raw = json.dumps(items, ensure_ascii=False, indent=1).encode("utf-8")
        await qy.message.reply_document(io.BytesIO(raw), filename=f"{base}_{stamp}.json",
                                        caption=f"{{ }} {len(items)} عنصر خام")
        return

    if action == "save":
        rows = ctx.user_data.get("ah_smart") or smart_extract(items)
        ctx.user_data["ah_smart"] = rows
        if not rows:
            await qy.message.reply_text("لا توجد أرقام لحفظها.")
            return
        codes = _D["countries"]
        kb, row = [], []
        for code, label in codes:
            row.append(InlineKeyboardButton(label, callback_data=f"ahs:{code}"))
            if len(row) == 3:
                kb.append(row); row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("بدون دولة", callback_data="ahs:XX")])
        await qy.message.reply_text(f"💾 حفظ {len(rows)} جهة — اختر الدولة:",
                                    reply_markup=InlineKeyboardMarkup(kb))
        return


async def save_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    qy = update.callback_query
    await qy.answer()
    country = qy.data.split(":")[1]
    rows = ctx.user_data.get("ah_smart") or []
    actor_id = ctx.user_data.get("ah_actor", "actor")
    rows = [r for r in rows if r.get("phone")]
    if not rows:
        await qy.edit_message_text("لا توجد أرقام صالحة للحفظ.")
        return
    await qy.edit_message_text(f"💾 جاري حفظ {len(rows)} رقم...")
    loop = asyncio.get_event_loop()

    def _do():
        job = _D["api"]("POST", "/api/public/bot/jobs", json={
            "keyword": f"actor:{actor_id}", "country": country,
            "provider": f"apify:{actor_id}", "status": "running",
            "telegram_chat_id": qy.message.chat_id,
        })["job"]
        items = [{
            "phone": r["phone"], "kind": "mobile" if r.get("whatsapp") else None,
            "business_name": r.get("name") or None, "page_name": r.get("name") or None,
            "website": r.get("website") or None, "email": r.get("email") or None,
        } for r in rows]
        res = _D["api"]("POST", "/api/public/bot/numbers", json={
            "search_id": job["id"], "country": country,
            "source": f"apify:{actor_id}", "items": items})
        _D["api"]("PATCH", "/api/public/bot/jobs", json={
            "id": job["id"], "status": "completed", "progress": 100, "finished": True,
            "numbers_found": res.get("total", 0), "numbers_new": res.get("new_count", 0)})
        return res

    try:
        res = await loop.run_in_executor(None, _do)
    except Exception as e:
        await qy.edit_message_text(f"❌ فشل الحفظ: {str(e)[:250]}")
        return
    await qy.edit_message_text(
        f"✅ تم الحفظ في Leads\n📊 إجمالي: {res.get('total',0)} | 🆕 جديد: {res.get('new_count',0)}")


async def lastrun_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    items = ctx.user_data.get("ah_items") or []
    if not items:
        await update.effective_message.reply_text("لا يوجد تشغيل سابق في هذه الجلسة. استخدم /actor")
        return
    await _send_field_menu(ctx.application, update.effective_chat.id, ctx, items,
                           ctx.user_data.get("ah_actor", "actor"))


async def myactors_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    loop = asyncio.get_event_loop()
    try:
        items = await loop.run_in_executor(None, list_my_actors)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ {str(e)[:200]}")
        return
    if not items:
        await update.effective_message.reply_text("لا توجد actors في حسابك. استخدم /actor للبحث في المتجر.")
        return
    txt = "\n".join(f"• <code>{a['id']}</code> — {a['title']}" for a in items)
    await update.effective_message.reply_text(f"🧩 <b>actors حسابك:</b>\n{txt}", parse_mode=ParseMode.HTML)


def register(app: Application) -> None:
    conv = ConversationHandler(
        entry_points=[CommandHandler("actor", actor_start),
                      CallbackQueryHandler(actor_start, pattern=r"^m:actor$")],
        states={
            AH_QUERY: [
                CallbackQueryHandler(actor_pick, pattern=r"^ah:a:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, actor_query),
            ],
            AH_INPUT: [
                CallbackQueryHandler(actor_run_default, pattern=r"^ah:run$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, actor_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", _D["cancel_cmd"])],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(field_cb, pattern=r"^ahf:"))
    app.add_handler(CallbackQueryHandler(save_cb, pattern=r"^ahs:"))
    app.add_handler(CommandHandler("myactors", myactors_cmd))
    app.add_handler(CommandHandler("lastrun", lastrun_cmd))
