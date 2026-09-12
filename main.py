# -*- coding: utf-8 -*-
# ══════════════════════════════════════════
#  HiVo Proxies — ربات پروکسی تلگرام
# ══════════════════════════════════════════
import asyncio, html, io, logging, os, re, threading
from datetime import datetime

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from tester import S, LOCK, refresh_loop, retest_all if False else None
from tester import S, LOCK, refresh_loop
from store import STORE

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER = "8343701928"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("hivo")

FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def fa(x):
    return str(x).translate(FA)

ADMIN_STATE = {}

def link_of(p):
    return f"https://t.me/proxy?server={p['server']}&port={p['port']}&secret={p['secret']}"

def label_of(p):
    mark = "✅" if p.get("deep") else "🔌"
    name = p.get("country") or ""
    return f"{p.get('flag','🌐')} {name} | {fa(p['latency'])}ms {mark}".strip()

def register(update):
    u = update.effective_user
    if u:
        STORE.touch(u.id, u.first_name or "", u.username or "")

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
        [InlineKeyboardButton("📢 عضویت", url=f"https://t.me/{ch.lstrip('@')}")],
        [InlineKeyboardButton("✅ بررسی", callback_data="recheck")]])
    await update.effective_message.reply_html("⚡️ <b>HiVo Proxies</b>\n\n「 اول عضو شو، بعد برگرد 」",
                                              reply_markup=kb)
    return False

def menu_text():
    wel = STORE.data["settings"].get("welcome", "").strip()
    deep = sum(1 for p in S["good"] if p.get("deep"))
    return "\n".join([
        "⚡️ <b>HiVo Proxies</b>",
        "",
        wel or "「 عبور، حق توست 」",
        "",
        f"🟢 {fa(len(S['good']))} پروکسی زنده",
        f"✅ {fa(deep)} تأیید عمیق (دست‌دهی واقعی)",
        f"🔄 {ago(S['last'])}",
        "",
        "「 عدد بفرست — با یک لمس اضافه می‌شود 」",
    ])

def ago(dt):
    if not dt:
        return "—"
    s = int((datetime.now() - dt).total_seconds())
    if s < 60:
        return f"{fa(s)} ثانیه پیش"
    if s < 3600:
        return f"{fa(s // 60)} دقیقه پیش"
    return f"{fa(s // 3600)} ساعت پیش"

def main_menu(is_admin=False):
    rows = [[InlineKeyboardButton("👑 اختصاصی", callback_data="premium"),
             InlineKeyboardButton("⚡️ ۱۰", callback_data="px:10")],
            [InlineKeyboardButton("📄 ۲۵", callback_data="px:25"),
             InlineKeyboardButton("📄 ۵۰", callback_data="px:50"),
             InlineKeyboardButton("📄 همه", callback_data="px:all")],
            [InlineKeyboardButton("📊 آمار", callback_data="stats"),
             InlineKeyboardButton("ℹ️ راهنما", callback_data="help")],
            [InlineKeyboardButton("♻️ تست مجدد", callback_data="retest")]]
    if is_admin:
        rows.append([InlineKeyboardButton("👑 پنل ادمین", callback_data="adm")])
    return InlineKeyboardMarkup(rows)

def stats_text():
    g = S["good"]
    deep = sum(1 for p in g if p.get("deep"))
    rate = f"{fa(round(len(g) * 100 / S['tested']))}٪" if S["tested"] else "—"
    src = STORE.data["sources"]
    top = "\n".join(
        f"  {fa(i)}. {p.get('flag','🌐')} {html.escape(p.get('country') or p['server'])} — {fa(p['latency'])}ms"
        for i, p in enumerate(g[:5], 1)) or "  —"
    return (
        "📊 <b>آمار</b> — 「 اعداد دروغ نمی‌گویند 」\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📥 جمع‌آوری‌شده: <b>{fa(S['fetched'])}</b>\n"
        f"🔌 زنده (TCP): <b>{fa(S['tcp'])}</b>\n"
        f"🟢 نهایی: <b>{fa(len(g))}</b>\n"
        f"✅ تأیید عمیق: <b>{fa(deep)}</b>\n"
        f"📈 نرخ موفقیت: <b>{rate}</b>\n"
        f"📡 منابع: <b>{fa(len(src['urls']))} لینک + {fa(len(src['channels']))} کانال</b>\n\n"
        f"🏆 <b>برترین‌ها:</b>\n{top}\n\n"
        f"🔄 {ago(S['last'])}")

def help_text(is_admin=False):
    t = ("ℹ️ <b>راهنما</b>\n「 ساده مثل یک لمس 」\n━━━━━━━━━━━━━━━━━━\n\n"
         "🔢 عدد بفرست ← پروکسی می‌گیری\n"
         "📲 روی هر پروکسی لمس کن ← تلگرام اضافه‌اش می‌کند\n"
         "✅ تأیید عمیق = دست‌دهی واقعی MTProto پاس شده\n"
         "👑 اختصاصی = پروکسی‌های ویژه\n\n"
         "「 هر پروکسی، یک پنجره 」")
    if is_admin:
        t += "\n\n👑 <b>ادمین:</b> /admin"
    return t

async def send_proxies(message, n):
    g = list(S["good"])
    if not g:
        await message.reply_text("⏳ 「 چیزهای خوب، زمان می‌برند 」")
        return
    items = g if (n is None or n >= len(g)) else g[:n]
    await message.chat.send_action("typing")
    if items and n is not None and n > 20:
        content = "\n".join(link_of(p) for p in items) + "\n"
        buf = io.BytesIO(content.encode())
        await message.reply_document(buf, filename=f"HiVoProxies-{len(items)}.txt",
                                     caption=f"⚡️ <b>{fa(len(items))} پروکسی زنده</b>\n"
                                             "「 باز کن، لمس کن، آزاد شو 」",
                                     parse_mode=ParseMode.HTML)
        STORE.add_totals(files=1, proxies=len(items))
        return
    first = True
    for i in range(0, len(items), 8):
        chunk = items[i:i + 8]
        rows = [[InlineKeyboardButton(label_of(p), url=link_of(p))] for p in chunk]
        if first:
            await message.reply_html(f"⚡️ <b>{fa(len(items))} پروکسی زنده</b> — لمس کن تا اضافه شود:",
                                     reply_markup=InlineKeyboardMarkup(rows))
            first = False
        else:
            await message.reply_html("‌", reply_markup=InlineKeyboardMarkup(rows))
        await asyncio.sleep(0.4)
    STORE.add_totals(files=0, proxies=len(items))

async def send_premium(message):
    prem = STORE.premium()
    if not prem:
        await message.reply_html("👑 <b>اختصاصی</b>\n\n「 هنوز چیزی اینجا نیست؛ به‌زودی 」")
        return
    rows = [[InlineKeyboardButton(f"👑 {p.get('name') or p['server']}", url=link_of(p))] for p in prem]
    await message.reply_html(f"👑 <b>اختصاصی — {fa(len(prem))} ویژه</b>\n「 چیزهای خاص، برای تو 」",
                             reply_markup=InlineKeyboardMarkup(rows))

# ────────── پنل ادمین ──────────
def admin_text():
    src = STORE.data["sources"]
    return ("👑 <b>پنل ادمین</b>\n「 فرمان بده 」\n━━━━━━━━━━━━━━━━━━\n"
            f"📡 کانال‌ها: <b>{fa(len(src['channels']))}</b> | لینک‌ها: <b>{fa(len(src['urls']))}</b>\n"
            f"📜 اختصاصی: <b>{fa(len(STORE.premium()))}</b>\n"
            f"👥 کاربران: <b>{fa(len(STORE.users()))}</b>")

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 افزودن کانال", callback_data="src:c"),
         InlineKeyboardButton("🔗 افزودن لینک", callback_data="src:u")],
        [InlineKeyboardButton("📜 منابع", callback_data="src:l"),
         InlineKeyboardButton("♻️ ریست منابع", callback_data="src:r")],
        [InlineKeyboardButton("➕ اختصاصی", callback_data="adm:add"),
         InlineKeyboardButton("🗑 پاک اختصاصی", callback_data="adm:clear")],
        [InlineKeyboardButton("📣 همگانی", callback_data="adm:bc"),
         InlineKeyboardButton("📊 کاربران", callback_data="adm:users")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="adm:set"),
         InlineKeyboardButton("🏠 منو", callback_data="menu")]])

def settings_text():
    st = STORE.data["settings"]
    wel = st.get("welcome", "").strip() or "پیش‌فرض"
    return ("⚙️ <b>تنظیمات</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"✏️ خوش‌آمد: <i>{html.escape(wel[:60])}</i>\n"
            f"📢 قفل کانال: <b>{'🟢 روشن' if st.get('lock_on') else '⚪️ خاموش'}</b>")

def settings_kb():
    st = STORE.data["settings"]
    lbl = "🔓 خاموش کن" if st.get("lock_on") else "🔒 روشن کن"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ متن خوش‌آمد", callback_data="adm:wel")],
        [InlineKeyboardButton("📢 کانال قفل", callback_data="adm:chan"),
         InlineKeyboardButton(lbl, callback_data="adm:lock")],
        [InlineKeyboardButton("🔙 پنل", callback_data="adm")]])

def users_text():
    users = STORE.users()
    today = datetime.now().date().isoformat()
    active = sum(1 for u in users.values() if (u.get("last") or "").startswith(today))
    tot = STORE.data.get("totals", {})
    top = sorted(users.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:8]
    body = "\n".join(f"{fa(i)}. {html.escape(u.get('name') or '—')} — {fa(u.get('count', 0))} بار"
                     for i, (uid, u) in enumerate(top, 1)) or "  —"
    return ("👑 <b>کاربران</b>\n「 هر اسم، یک داستان 」\n━━━━━━━━━━━━━━━━━━\n"
            f"👥 کل: <b>{fa(len(users))}</b>\n🟢 امروز: <b>{fa(active)}</b>\n"
            f"📄 فایل: <b>{fa(tot.get('files', 0))}</b>\n"
            f"⚡️ پروکسی تحویلی: <b>{fa(tot.get('proxies', 0))}</b>\n\n"
            f"🏆 <b>پرکاربردترها:</b>\n{body}")

async def do_broadcast(ctx, text, status_msg):
    ok = fail = 0
    for uid in list(STORE.users().keys()):
        try:
            await ctx.bot.send_message(int(uid), f"📣 {text}")
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.06)
    extra = f"\n❌ {fa(fail)}" if fail else ""
    await status_msg.edit_text(f"✅ رفت به {fa(ok)} نفر{extra}")

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
    await update.message.reply_html(admin_text(), reply_markup=admin_kb())

async def on_text(update, ctx):
    register(update)
    uid = update.effective_user.id
    if STORE.is_admin(uid) and uid in ADMIN_STATE:
        state = ADMIN_STATE.pop(uid)
        txt = (update.message.text or "").strip()
        if state == "src:c":
            ok = STORE.add_source("channels", txt)
            await update.message.reply_html("✅ کانال اضافه شد — از دور بعد اعمال می‌شود." if ok
                                            else "⚠️ قبلاً اضافه شده.")
        elif state == "src:u":
            ok = STORE.add_source("urls", txt)
            await update.message.reply_html("✅ منبع اضافه شد." if ok else "⚠️ قبلاً اضافه شده.")
        elif state == "premium":
            from tester import LINK_RE, TG_RE, LINE_RE
            found = []
            for rx in (LINK_RE, TG_RE):
                for m in rx.finditer(txt.replace("&amp;", "&")):
                    found.append({"server": m.group(1), "port": int(m.group(2)),
                                  "secret": m.group(3).lower(), "name": ""})
            for m in LINE_RE.finditer(txt):
                found.append({"server": m.group(1), "port": int(m.group(2)),
                              "secret": m.group(3).lower(), "name": ""})
            added = sum(1 for p in found if STORE.add_premium(p))
            await update.message.reply_html(f"👑 <b>{fa(added)} اختصاصی اضافه شد</b>\n"
                                            f"📜 کل: <b>{fa(len(STORE.premium()))}</b>")
        elif state == "welcome":
            if txt.lower() == "/off":
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
                await update.message.reply_html(f"📢 قفل روشن شد: <code>{html.escape(txt)}</code>\n"
                                                "⚠️ ربات باید ادمین کانال باشد.")
        elif state == "broadcast":
            status = await update.message.reply_text("📣 در راه‌اند…")
            await do_broadcast(ctx, txt, status)
        return
    if not await gate(update, ctx):
        return
    m = re.search(r"\d+", update.message.text or "")
    if m:
        await send_proxies(update.message, int(m.group()))
    else:
        await cmd_start(update, ctx)

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
    if data.startswith("px:"):
        if not await gate(update, ctx):
            return
        arg = data.split(":")[1]
        await send_proxies(q.message, None if arg == "all" else int(arg))
    elif data == "premium":
        if not await gate(update, ctx):
            return
        await send_premium(q.message)
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
        await q.message.reply_html(menu_text(), reply_markup=main_menu(is_admin))
    elif data == "adm" and is_admin:
        await q.edit_message_text(admin_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())
    elif data == "src:c" and is_admin:
        ADMIN_STATE[uid] = "src:c"
        await q.message.reply_html("📢 <b>آیدی کانال پروکسی را بفرست</b>\n"
                                   "مثلاً: @proxy_channel یا لینک کامل\n\n/cancel انصراف")
    elif data == "src:u" and is_admin:
        ADMIN_STATE[uid] = "src:u"
        await q.message.reply_html("🔗 <b>لینک منبع را بفرست</b>\n"
                                   "(لینک raw گیت‌هاب یا API — هر متنی که لینک پروکسی داخلش باشد)\n\n/cancel انصراف")
    elif data == "src:l" and is_admin:
        src = STORE.data["sources"]
        chans = "\n".join(f"  • {html.escape(c)}" for c in src["channels"]) or "  —"
        urls = "\n".join(f"  • {html.escape(u[:60])}" for u in src["urls"]) or "  —"
        await q.message.reply_html(f"📜 <b>کانال‌ها:</b>\n{chans}\n\n<b>لینک‌ها:</b>\n{urls}",
                                   reply_markup=kb_menu)
    elif data == "src:r" and is_admin:
        STORE.reset_sources()
        await q.message.reply_html("♻️ منابع به پیش‌فرض برگشت.", reply_markup=kb_menu)
    elif data == "adm:add" and is_admin:
        ADMIN_STATE[uid] = "premium"
        await q.message.reply_html("➕ <b>لینک پروکسی‌های اختصاصی را بفرست</b>\n"
                                   "(t.me/proxy?... — چند تا، هر کدام در یک خط)\n\n/cancel انصراف")
    elif data == "adm:clear" and is_admin:
        n = STORE.clear_premium()
        await q.message.reply_html(f"🗑 {fa(n)} اختصاصی پاک شد.", reply_markup=kb_menu)
    elif data == "adm:bc" and is_admin:
        ADMIN_STATE[uid] = "broadcast"
        await q.message.reply_html("📣 <b>متن پیام را بفرست</b>\n\n/cancel انصراف")
    elif data == "adm:users" and is_admin:
        await q.edit_message_text(users_text(), parse_mode=ParseMode.HTML,
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("🔙 پنل", callback_data="adm")]]))
    elif data == "adm:set" and is_admin:
        await q.edit_message_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())
    elif data == "adm:wel" and is_admin:
        ADMIN_STATE[uid] = "welcome"
        await q.message.reply_html("✏️ <b>متن خوش‌آمد را بفرست</b> (کوتاه، از ته دل)\n\n/off پیش‌فرض — /cancel انصراف")
    elif data == "adm:chan" and is_admin:
        ADMIN_STATE[uid] = "channel"
        await q.message.reply_html("📢 <b>آیدی کانال قفل را بفرست</b> (با @)\n\n/off خاموشی — /cancel انصراف")
    elif data == "adm:lock" and is_admin:
        st = STORE.data["settings"]
        STORE.set_setting("lock_on", not st.get("lock_on"))
        await q.edit_message_text(settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_kb())

async def cmd_cancel(update, ctx):
    ADMIN_STATE.pop(update.effective_user.id, None)
    await update.message.reply_html("「 برگشتی 」")

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 آغاز"),
        BotCommand("admin", "👑 پنل ادمین"),
        BotCommand("cancel", "↩️ لغو")])
    await app.bot.set_my_description(
        "پروکسی‌های زنده تلگرام — تست‌شده با دست‌دهی واقعی، با یک لمس اضافه می‌شوند ⚡️")
    await app.bot.set_my_short_description("「 عبور، حق توست 」⚡️")

async def post_shutdown(app):
    STORE.save()

async def cmd_stats(update, ctx):
    register(update)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    await update.message.reply_html(stats_text(), reply_markup=kb)

async def cmd_help(update, ctx):
    register(update)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 منو", callback_data="menu")]])
    await update.message.reply_html(help_text(STORE.is_admin(update.effective_user.id)), reply_markup=kb)

def main():
    STORE.load()
    STORE.set_admin(os.environ.get("ADMIN_ID", "").strip() or OWNER)
    threading.Thread(target=refresh_loop, daemon=True).start()
    threading.Thread(target=STORE.autosave_loop, daemon=True).start()
    app = (Application.builder().token(BOT_TOKEN)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    app.add_handler(CommandHandler(["start", "menu"], cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("HiVo Proxies started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
