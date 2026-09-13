# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Configs v7 — مینی‌اپ + اینلاین + QR + ری‌اکشن
# ══════════════════════════════════════════

import asyncio, base64, html, io, json, logging, os, re, threading
from datetime import datetime
from urllib.parse import quote

import qrcode

from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                      InlineQueryResultArticle, InputTextMessageContent,
                      MenuButtonWebApp, ReactionTypeEmoji, Update, WebAppInfo)
try:
    from telegram import CopyTextButton
    HAS_COPY = True
except ImportError:
    HAS_COPY = False
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, InlineQueryHandler,
                          MessageHandler, filters)

from tester import (S, LOCK, refresh_loop, retest_all, URI_RE)
from store import STORE

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER = "8343701928"

REPO = os.environ.get("GITHUB_REPOSITORY", "")
APP_URL = ""
if REPO and "/" in REPO:
    _o, _n = REPO.split("/", 1)
    APP_URL = f"https://{_o.lower()}.github.io/{_n}/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("elite")

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def fa(x):
    return str(x).translate(FA)

ADMIN_STATE = {}

TAGLINE = "「 آزادی، یک اتصال فاصله دارد 」"
FILE_TAG = "「 این‌ها زنده‌اند؛ تو هم باش 」"
PREMIUM_TAG = "「 چیزهای خاص، برای تو 」"
STATS_TAG = "「 اعداد دروغ نمی‌گویند 」"
LOCK_TAG = "「 اول عضو شو، بعد برگرد 」"

# ────────── ابزارها ──────────
def quality(ms):
    if ms < 300:
        return "🟩🟩🟩🟩🟩"
    if ms < 700:
        return "🟩🟩🟩🟩🟨"
    if ms < 1500:
        return "🟩🟩🟨🟨⬜️"
    return "🟨🟨⬜️⬜️⬜️"

def fa_ago(dt):
    if not dt:
        return "—"
    s = int((datetime.now() - dt).total_seconds())
    if s < 60:
        return f"{fa(s)} ثانیه پیش"
    if s < 3600:
        return f"{fa(s // 60)} دقیقه پیش"
    return f"{fa(s // 3600)} ساعت پیش"

def register(update):
    u = update.effective_user
    if u:
        STORE.touch(u.id, u.first_name or "", u.username or "")

async def react(message, emoji="⚡️"):
    try:
        await message.set_reaction(reaction=[ReactionTypeEmoji(emoji)])
    except Exception:
        pass

async def gate(update, ctx):
    st = STORE.data["settings"]
    ch = st.get("lock_channel", "")
    if not st.get("lock_on") or not ch:
        return True
    uid = update.effective_user.id
    if STORE.is_admin(uid):
        return True
    try:
        m = await ctx.bot.get_chat_member(ch, uid)
        if m.status not in ("left", "kicked"):
            return True
    except Exception:
        return True
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{ch.lstrip('@')}")],
        [InlineKeyboardButton("✅ بررسی", callback_data="recheck")],
    ])
    await update.effective_message.reply_html(
        f"⚡️ <b>HiVo Configs</b>\n\n{LOCK_TAG}", reply_markup=kb)
    return False

def premium_uri(uri):
    name = "HiVo Premium 👑"
    low = uri.lower()
    if low.startswith("vmess://"):
        try:
            s = uri[8:].strip().replace("-", "+").replace("_", "/")
            s += "=" * (-len(s) % 4)
            d = json.loads(base64.b64decode(s).decode("utf-8", "ignore"))
            d["ps"] = name
            return "vmess://" + base64.b64encode(
                json.dumps(d, ensure_ascii=False).encode()).decode()
        except Exception:
            return uri
    return uri.split("#", 1)[0] + "#" + quote(name, safe="")

def qr_bytes(url):
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ────────── منوها ──────────
def menu_text():
    wel = STORE.data["settings"].get("welcome", "").strip()
    return "\n".join([
        "⚡️ <b>HiVo Configs</b>",
        "",
        wel or TAGLINE,
        "",
        f"🟢 {fa(len(S['good']))} زنده",
        f"🔄 {fa_ago(S['last'])}",
        "",
        "「 یک عدد بفرست، بقیه‌اش با ما 」",
    ])

def main_menu(is_admin=False):
    rows = []
    if APP_URL:
        rows.append([InlineKeyboardButton("📱 اپ HiVo", web_app=WebAppInfo(url=APP_URL))])
    rows.append([InlineKeyboardButton("👑 اختصاصی", callback_data="premium")])
    rows.append([InlineKeyboardButton("📄 ۵۰", callback_data="file:50"),
                 InlineKeyboardButton("📄 ۱۰۰", callback_data="file:100"),
                 InlineKeyboardButton("📄 ۲۰۰", callback_data="file:200")])
    rows.append([InlineKeyboardButton("📄 ۵۰۰", callback_data="file:500"),
                 InlineKeyboardButton("📄 همه", callback_data="file:all")])
    rows.append([InlineKeyboardButton("🔗 سابسکرایبشن", callback_data="sub"),
                 InlineKeyboardButton("📱 QR", callback_data="qr")])
    rows.append([InlineKeyboardButton("📊 آمار", callback_data="stats"),
                 InlineKeyboardButton("ℹ️ راهنما", callback_data="help")])
    rows.append([InlineKeyboardButton("♻️ تست مجدد", callback_data="retest")])
    if is_admin:
        rows.append([InlineKeyboardButton("👑 پنل ادمین", callback_data="adm")])
    return InlineKeyboardMarkup(rows)

def stats_text():
    g = S["good"]
    rate = f"{fa(round(len(g) * 100 / S['tested']))}٪" if S["tested"] else "—"
    sub = "✅ فعال" if S["sub"] else "—"
    top = "\n".join(
        f"  {fa(i)}. ⏱ {fa(c['latency'])}ms {quality(c['latency'])}"
        f"  <code>{html.escape(str(c['host']))}</code>"
        for i, c in enumerate(g[:5], 1)) or "  —"
    return (
        f"📊 <b>آمار</b> — {STATS_TAG}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📥 از ۱۲ منبع: <b>{fa(S['fetched'])}</b>\n"
        f"🔬 تست‌شده: <b>{fa(S['tested'])}</b>\n"
        f"🟢 زنده: <b>{fa(len(g))}</b>\n"
        f"📈 موفقیت: <b>{rate}</b>\n"
        f"🔗 سابسکرایبشن: <b>{sub}</b>\n\n"
        f"🏆 <b>برترین‌ها:</b>\n{top}\n\n"
        f"🔄 {fa_ago(S['last'])}")

def help_text(is_admin=False):
    t = (
        "ℹ️ <b>راهنما</b>\n"
        "「 ساده مثل نفس کشیدن 」\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔢 عدد بفرست ← فایل می‌گیری\n"
        "📱 اپ HiVo ← تجربه کامل\n"
        "🔍 توی هر چتی: <code>@ربات 10</code>\n"
        "🔗 سابسکرایبشن ← همیشه تازه\n"
        "👑 اختصاصی ← چیزهای خاص\n\n"
        "「 هر کلید، دری را باز می‌کند 」")
    if is_admin:
        t += "\n\n👑 <b>ادمین:</b> /admin"
    return t

# ────────── پنل ادمین ──────────
def admin_panel_text():
    st = STORE.data["settings"]
    lock = f"🟢 {st.get('lock_channel', '')}" if st.get("lock_on") else "⚪️ خاموش"
    return (
        "👑 <b>پنل ادمین</b>\n"
        "「 فرمان بده 」\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📜 اختصاصی: <b>{fa(len(STORE.premium()))}</b>\n"
        f"📢 قفل کانال: <b>{lock}</b>")

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن اختصاصی", callback_data="adm:add"),
         InlineKeyboardButton("📜 دیدن", callback_data="adm:list")],
        [InlineKeyboardButton("🗑 پاک‌کردن اختصاصی‌ها", callback_data="adm:clear")],
        [InlineKeyboardButton("📣 پیام همگانی", callback_data="adm:bc"),
         InlineKeyboardButton("📊 کاربران", callback_data="adm:stats")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="adm:set")],
        [InlineKeyboardButton("🏠 منو", callback_data="menu")],
    ])

def settings_text():
    st = STORE.data["settings"]
    wel = st.get("welcome", "").strip() or "پیش‌فرض"
    return (
        "⚙️ <b>تنظیمات</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"✏️ متن خوش‌آمد: <i>{html.escape(wel[:60])}</i>\n"
        f"📢 قفل کانال: <b>{'🟢 روشن' if st.get('lock_on') else '⚪️ خاموش'}</b>")

def settings_kb():
    st = STORE.data["settings"]
    lock_label = "🔓 خاموش کن" if st.get("lock_on") else "🔒 روشن کن"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ متن خوش‌آمد", callback_data="adm:wel")],
        [InlineKeyboardButton("📢 کانال قفل", callback_data="adm:chan"),
         InlineKeyboardButton(lock_label, callback_data="adm:lock")],
        [InlineKeyboardButton("🔙 پنل", callback_data="adm")],
    ])

def users_text():
    users = STORE.users()
    today = datetime.now().date().isoformat()
    active = sum(1 for u in users.values() if (u.get("last") or "").startswith(today))
    tot = STORE.data.get("totals", {})
    top = sorted(users.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:8]
    lines = [f"{fa(i)}. {html.escape(u.get('name') or '—')} — {fa(u.get('count', 0))} بار"
             for i, (uid, u) in enumerate(top, 1)]
    body = "\n".join(lines) or "  —"
    return (
        "👑 <b>کاربران</b>\n"
        "「 هر اسم، یک داستان 」\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 کل: <b>{fa(len(users))}</b>\n"
        f"🟢 امروز: <b>{fa(active)}</b>\n"
        f"📄 فایل: <b>{fa(tot.get('files', 0))}</b>\n"
        f"⚡️ کانفیگ: <b>{fa(tot.get('configs', 0))}</b>\n\n"
        f"🏆 <b>پرکاربردتر‌ها:</b>\n{body}")

async def do_broadcast(ctx, text, status_msg):
    users = STORE.users()
    ok = fail = 0
    for uid in list(users.keys()):
        try:
            await ctx.bot.send_message(int(uid), f"📣 {text}")
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.06)
    extra = f"\n❌ {fa(fail)}" if fail else ""
    await status_msg.edit_text(f"✅ رفت به {fa(ok)} نفر{extra}")

# ────────── ارسال ──────────
async def send_config_file(message, n):
    g = list(S["good"])
    if not g:
        await message.reply_text("⏳ 「 چیزهای خوب، زمان می‌برند 」")
        return
    items = g if (n is None or n >= len(g)) else g[:n]
    await message.chat.send_action("upload_document")
    content = "\n".join(c["uri"] for c in items) + "\n"
    buf = io.BytesIO(content.encode())
    caption = (
        f"⚡️ <b>HiVo Configs — {fa(len(items))} زنده</b>\n"
        f"{FILE_TAG}\n"
        f"⏱ بهترین: <b>{fa(items[0]['latency'])}ms</b> {quality(items[0]['latency'])}")
    msg = await message.reply_document(document=buf, filename=f"HiVo-{len(items)}.txt",
                                       caption=caption, parse_mode=ParseMode.HTML)
    await react(msg)
    STORE.add_totals(files=1, configs=len(items))

async def send_premium(message):
    prem = STORE.premium()
    if not prem:
        await message.reply_html(
            "👑 <b>اختصاصی</b>\n\n「 هنوز چیزی اینجا نیست؛ ولی به‌زودی 」")
        return
    uris = [premium_uri(u) for u in prem]
    await message.chat.send_action("upload_document")
    buf = io.BytesIO(("\n".join(uris) + "\n").encode())
    caption = f"👑 <b>HiVo Premium — {fa(len(uris))} ویژه</b>\n{PREMIUM_TAG}"
    msg = await message.reply_document(document=buf, filename="HiVo-Premium.txt",
                                       caption=caption, parse_mode=ParseMode.HTML)
    await react(msg, "🔥")
    STORE.add_totals(files=1, configs=len(uris))

async def send_sub_qr(message):
    url = S.get("sub")
    if not url:
        await message.reply_html("⏳ 「 هنوز در راه است 」")
        return
    msg = await message.reply_photo(photo=qr_bytes(url),
                                    caption=("🔗 <b>QR سابسکرایبشن</b>\n"
                                             "از گوشی دوم اسکن کن یا لینک را بگیر:\n"
                                             f"<code>{html.escape(url)}</code>"),
                                    parse_mode=ParseMode.HTML)
    await react(msg)

# ────────── اینلاین ──────────
async def on_inline(update, ctx):
    q = update.inline_query
    g = list(S["good"])
    if not g:
        await q.answer([], cache_time=5)
        return
    try:
        offset = int(q.offset or 0)
    except ValueError:
        offset = 0
    items = g[offset:offset + 12]
    results = []
    for i, c in enumerate(items, offset + 1):
        results.append(InlineQueryResultArticle(
            id=str(i),
            title=f"⚡️ {c['latency']}ms — HiVo",
            description=c["uri"][:90],
            input_message_content=InputTextMessageContent(
                message_text=f"⚡️ <b>HiVo Configs</b> — {c['latency']}ms\n"
                             f"<code>{html.escape(c['uri'])}</code>",
                parse_mode=ParseMode.HTML),
        ))
    await q.answer(results, cache_time=10, is_personal=True,
                   next_offset=str(offset + 12) if offset + 12 < len(g) else "")

# ────────── دستورات ──────────
async def cmd_start(update, ctx):
    register(update)
    if not await gate(update, ctx):
        return
    await update.message.reply_html(menu_text(),
                                    reply_markup=main_menu(STORE.is_admin(update.effective_user.id)))

async def cmd_admin(update, ctx):
    register(update)
    if not STORE.is_admin(update.effective_user.id):
        return
    await update.message.reply_html(admin_panel_text(), reply_markup=admin_kb())

async def cmd_users(update, ctx):
    if not STORE.is_admin(update.effective_user.id):
        return
    await update.message.reply_html(users_text())

async def cmd_broadcast(update, ctx):
    if not STORE.is_admin(update.effective_user.id):
        return
    raw = update.message.text or ""
    parts = raw.split(" ", 1)
    text = parts[1].strip() if len(parts) > 1 else ""
    if not text:
        await update.message.reply_html("استفاده: <code>/broadcast متن</code>")
        return
    status = await update.message.reply_text("📣 در راه‌اند…")
    await do_broadcast(ctx, text, status)

async def cmd_cancel(update, ctx):
    ADMIN_STATE.pop(update.effective_user.id, None)
    await update.message.reply_html("「 برگشتی 」")

async def cmd_configs(update, ctx):
    register(update)
    if not await gate(update, ctx):
        return
    n = None
    if ctx.args and ctx.args[0].isdigit():
        n = int(ctx.args[0])
    await send_config_file(update.message, n)

async def on_text(update, ctx):
    register(update)
    uid = update.effective_user.id
    if STORE.is_admin(uid) and uid in ADMIN_STATE:
        state = ADMIN_STATE.pop(uid)
        txt = (update.message.text or "").strip()
        if state == "premium":
            uris = URI_RE.findall(txt)
            if not uris:
                await update.message.reply_html("❌ کانفیگی پیدا نکردم. دوباره بفرست.")
                return
            added = STORE.add_premium(uris)
            await update.message.reply_html(
                f"👑 <b>{fa(added)} کانفیگ اختصاصی اضافه شد</b>\n"
                f"📜 کل: <b>{fa(len(STORE.premium()))}</b>\n\n「 ذخیره شد 」")
        elif state == "welcome":
            if txt.lower() == "/off" or txt == "خاموش":
                STORE.set_setting("welcome", "")
                await update.message.reply_html("✏️ برگشت به پیش‌فرض.")
            else:
                STORE.set_setting("welcome", txt)
                await update.message.reply_html("✏️ 「 متن تازه نشست 」")
        elif state == "channel":
            if txt.lower() == "/off":
                STORE.set_setting("lock_on", False)
                await update.message.reply_html("📢 قفل خاموش شد.")
            else:
                if not txt.startswith("@"):
                    txt = "@" + txt
                STORE.set_setting("lock_channel", txt)
                STORE.set_setting("lock_on", True)
                await update.message.reply_html(
                    f"📢 قفل روشن شد: <code>{html.escape(txt)}</code>\n"
                    "⚠️ ربات باید ادمین کانال باشد.")
        elif state == "broadcast":
            status = await update.message.reply_text("📣 در راه‌اند…")
            await do_broadcast(ctx, txt, status)
        return
    if not await gate(update, ctx):
        return
    m = re.search(r"\d+", update.message.text or "")
    if m:
        await send_config_file(update.message, int(m.group()))
    else:
        await cmd_start(update, ctx)

# ────────── دکمه‌ها ──────────
async def on_button(update, ctx):
    register(update)
    q = update.callback_query
    data = q.data
    await q.answer()
    uid = q.from_user.id
    is_admin = STORE.is_admin(uid)
    kb_menu = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])

    if data == "recheck":
        if await gate(update, ctx):
            await q.message.reply_html(menu_text(), reply_markup=main_menu(is_admin))
        return

    if data.startswith("file:"):
        if not await gate(update, ctx):
            return
        arg = data.split(":")[1]
        await send_config_file(q.message, None if arg == "all" else int(arg))
    elif data == "premium":
        if not await gate(update, ctx):
            return
        await send_premium(q.message)
    elif data == "qr":
        await send_sub_qr(q.message)
    elif data == "sub":
        url = S.get("sub")
        if url:
            txt = ("🔗 <b>سابسکرایبشن</b>\n\n"
                   f"<code>{html.escape(url)}</code>\n\n"
                   "「 یک بار اضافه کن، همیشه تازه 」")
        else:
            txt = "⏳ 「 هنوز در راه است 」"
        await q.message.reply_html(txt, reply_markup=kb_menu)
    elif data == "menu":
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.reply_html(menu_text(), reply_markup=main_menu(is_admin))
    elif data == "stats":
        await q.edit_message_text(stats_text(), parse_mode=ParseMode.HTML, reply_markup=kb_menu)
    elif data == "help":
        await q.edit_message_text(help_text(is_admin), parse_mode=ParseMode.HTML, reply_markup=kb_menu)
    elif data == "retest":
        await q.edit_message_text("📡 「 صبر؛ کیفیت ساخته می‌شود 」", parse_mode=ParseMode.HTML)
        res = await asyncio.get_running_loop().run_in_executor(None, retest_all)
        with LOCK:
            if res:
                S["good"], S["last"] = res, datetime.now()
        best = f"{fa(res[0]['latency'])}ms" if res else "—"
        await q.edit_message_text(
            f"♻️ <b>تازه شد</b>\n🟢 {fa(len(res))} زنده\n⚡️ {best}",
            parse_mode=ParseMode.HTML, reply_markup=kb_menu)
    elif data == "adm" and is_admin:
        await q.edit_message_text(admin_panel_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())
    elif data == "adm:add" and is_admin:
        ADMIN_STATE[uid] = "premium"
        await q.message.reply_html(
            "➕ <b>کانفیگ‌های اختصاصی را بفرست</b>\n(چند خط — هر خط یک کانفیگ)\n\n/cancel برای انصراف")
    elif data == "adm:list" and is_admin:
        prem = STORE.premium()
        if not prem:
            await q.message.reply_html("📜 「 خالی است 」")
        else:
            buf = io.BytesIO(("\n".join(prem) + "\n").encode())
            await q.message.reply_document(buf, filename="premium-raw.txt",
                                           caption=f"📜 {fa(len(prem))} کانفیگ اختصاصی")
    elif data == "adm:clear" and is_admin:
        n = STORE.clear_premium()
        await q.message.reply_html(f"🗑 {fa(n)} کانفیگ پاک شد.", reply_markup=kb_menu)
        await q.message.reply_html(admin_panel_text(), reply_markup=admin_kb())
    elif data == "adm:bc" and is_admin:
        ADMIN_STATE[uid] = "broadcast"
        await q.message.reply_html("📣 <b>متن پیام را بفرست</b>\n\n/cancel برای انصراف")
    elif data == "adm:stats" and is_admin:
        await q.edit_message_text(users_text(), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("🔙 پنل", callback_data="adm")]]))
    elif data == "adm:set" and is_admin:
        await q.edit_message_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())
    elif data == "adm:wel" and is_admin:
        ADMIN_STATE[uid] = "welcome"
        await q.message.reply_html(
            "✏️ <b>متن خوش‌آمد را بفرست</b>\n(کوتاه و از ته دل)\n\n/off برای پیش‌فرض — /cancel انصراف")
    elif data == "adm:chan" and is_admin:
        ADMIN_STATE[uid] = "channel"
        await q.message.reply_html(
            "📢 <b>آیدی کانال را بفرست</b> (با @)\nربات باید ادمین کانال باشد.\n\n/off برای خاموشی — /cancel انصراف")
    elif data == "adm:lock" and is_admin:
        st = STORE.data["settings"]
        STORE.set_setting("lock_on", not st.get("lock_on"))
        await q.edit_message_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())

# ────────── شروع ──────────
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 آغاز"),
        BotCommand("configs", "📄 فایل — /configs 200"),
        BotCommand("stats", "📊 آمار"),
        BotCommand("help", "ℹ️ راهنما"),
    ])
    await app.bot.set_my_description(
        "مرزها را نقاشی کردند؛ ما راهی ساختیم ⚡️ کانفیگ زنده، تست‌شده، بی‌محدودیت.")
    await app.bot.set_my_short_description(TAGLINE + " ⚡️")
    if APP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="⚡️ HiVo", web_app=WebAppInfo(url=APP_URL)))
            log.info(f"menu button → {APP_URL}")
        except Exception as e:
            log.warning(f"menu button: {e}")

async def post_shutdown(app):
    ok = STORE.save()
    log.info(f"final save: {ok}")

def main():
    STORE.load()
    forced = os.environ.get("ADMIN_ID", "").strip()
    STORE.set_admin(forced or OWNER)
    threading.Thread(target=refresh_loop, daemon=True).start()
    threading.Thread(target=STORE.autosave_loop, daemon=True).start()
    app = (Application.builder()
           .token(BOT_TOKEN)
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .build())
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("configs", cmd_configs))
    app.add_handler(InlineQueryHandler(on_inline))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("HiVo Configs v7 started")
    app.run_polling(drop_pending_updates=True)

async def cmd_stats(update, ctx):
    register(update)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    await update.message.reply_html(stats_text(), reply_markup=kb)

if __name__ == "__main__":
    main()
