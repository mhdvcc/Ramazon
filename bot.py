import os, json, logging, threading, functools
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from zoneinfo import ZoneInfo

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.environ["BOT_TOKEN"]                 # BotFather bergan token
WEB_APP_URL = os.environ.get("WEB_APP_URL", "")  # mini ilova manzili (https://...)
PORT = int(os.environ.get("PORT", "8080"))
TZ = ZoneInfo("Asia/Tashkent")
DB = "users.json"

logging.basicConfig(level=logging.INFO)

CITIES = {
    "Toshkent": (41.2995, 69.2401, "Ташкент"), "Samarqand": (39.6542, 66.9597, "Самарканд"),
    "Buxoro": (39.7747, 64.4286, "Бухара"), "Andijon": (40.7821, 72.3442, "Андижан"),
    "Namangan": (41.0011, 71.6683, "Наманган"), "Farg'ona": (40.3864, 71.7864, "Фергана"),
    "Qarshi": (38.8606, 65.7891, "Карши"), "Navoiy": (40.0844, 65.3792, "Навои"),
    "Nukus": (42.4531, 59.6103, "Нукус"), "Urganch": (41.5506, 60.6317, "Ургенч"),
    "Xiva": (41.3775, 60.3640, "Хива"), "Termiz": (37.2242, 67.2783, "Термез"),
    "Jizzax": (40.1158, 67.8422, "Джизак"), "Guliston": (40.4897, 68.7842, "Гулистан"),
}
PRAYERS = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]

TXT = {
    "uz": {
        "choose_lang": "Tilni tanlang / Выберите язык:",
        "choose_city": "Shahringizni tanlang:",
        "saved": "✅ Tayyor! Endi namoz vaqtlari haqida eslatma yuboraman.\n\nMini ilovani ochish uchun pastdagi tugmani bosing.",
        "open_app": "🕌 Mini ilovani ochish",
        "names": {"Fajr": "Bomdod", "Sunrise": "Quyosh", "Dhuhr": "Peshin", "Asr": "Asr", "Maghrib": "Shom", "Isha": "Xufton"},
        "today": "🕌 Bugungi namoz vaqtlari — {city}",
        "ram": "\n\n🌙 Saharlik tugashi: {f}\n🌅 Iftor: {m}",
        "remind10": "⏰ {name} namoziga 10 daqiqa qoldi ({t}).",
        "now": "🕌 {name} namozi vaqti kirdi ({t}).",
        "sahar10": "🌙 Saharlik tugashiga 10 daqiqa qoldi ({t}). Niyat qilishni unutmang.",
        "sahar_now": "🌙 Saharlik vaqti tugadi ({t}). Bomdod vaqti kirdi.",
        "iftar10": "🌅 Iftorga 10 daqiqa qoldi ({t}). Duoga tayyorlaning.",
        "iftar_now": "🌅 Iftor vaqti! ({t})\nAllohumma laka sumtu va bika amantu va 'alayka tavakkaltu va 'ala rizqika aftartu.\nIftoringiz qabul bo'lsin! 🤲",
        "on": "🔔 Eslatmalar yoqildi", "off": "🔕 Eslatmalar o'chirildi", "nocity": "Avval /start bosing.",
        "help": "/start — sozlash\n/vaqt — bugungi vaqtlar\n/app — mini ilova\n/eslatma — eslatmani yoqish/o'chirish\n/til — tilni o'zgartirish",
    },
    "ru": {
        "choose_lang": "Tilni tanlang / Выберите язык:",
        "choose_city": "Выберите ваш город:",
        "saved": "✅ Готово! Теперь я буду присылать напоминания о времени намаза.\n\nНажмите кнопку ниже, чтобы открыть мини-приложение.",
        "open_app": "🕌 Открыть приложение",
        "names": {"Fajr": "Фаджр", "Sunrise": "Восход", "Dhuhr": "Зухр", "Asr": "Аср", "Maghrib": "Магриб", "Isha": "Иша"},
        "today": "🕌 Время намаза сегодня — {city}",
        "ram": "\n\n🌙 Конец сухура: {f}\n🌅 Ифтар: {m}",
        "remind10": "⏰ До намаза {name} 10 минут ({t}).",
        "now": "🕌 Наступило время намаза {name} ({t}).",
        "sahar10": "🌙 До конца сухура 10 минут ({t}). Не забудьте про намерение.",
        "sahar_now": "🌙 Время сухура закончилось ({t}). Наступил Фаджр.",
        "iftar10": "🌅 До ифтара 10 минут ({t}). Приготовьтесь к дуа.",
        "iftar_now": "🌅 Время ифтара! ({t})\nАллахумма лака сумту ва бика аманту ва аляйка таваккальту ва аля ризқика афтарту.\nПусть Аллах примет ваш пост! 🤲",
        "on": "🔔 Напоминания включены", "off": "🔕 Напоминания выключены", "nocity": "Сначала нажмите /start.",
        "help": "/start — настройка\n/vaqt — время на сегодня\n/app — мини-приложение\n/eslatma — вкл/выкл напоминания\n/til — сменить язык",
    },
}

# ---------- saqlash ----------
_lock = threading.Lock()
def load_db():
    try:
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
def save_db(db):
    with _lock, open(DB, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
USERS = load_db()

def user(uid):
    return USERS.get(str(uid))

# ---------- namoz vaqtlari ----------
_cache = {}
async def get_day(city):
    now = datetime.now(TZ)
    key = (city, now.strftime("%Y-%m-%d"))
    if key in _cache:
        return _cache[key]
    lat, lng, _ = CITIES[city]
    url = (f"https://api.aladhan.com/v1/timings/{now:%d-%m-%Y}"
           f"?latitude={lat}&longitude={lng}&method=3&school=1&timezonestring=Asia/Tashkent")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(url)
    d = r.json()["data"]
    res = {"t": {k: d["timings"][k][:5] for k in PRAYERS}, "ramadan": int(d["date"]["hijri"]["month"]["number"]) == 9}
    for k in [k for k in _cache if k[1] != key[1]]:
        _cache.pop(k, None)
    _cache[key] = res
    return res

def minus(hhmm, mins):
    h, m = map(int, hhmm.split(":"))
    t = (h * 60 + m - mins) % 1440
    return f"{t // 60:02d}:{t % 60:02d}"

# ---------- tugmalar ----------
def lang_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang:uz"),
                                  InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru")]])
def city_kb(lang):
    names = list(CITIES)
    btns = [InlineKeyboardButton(CITIES[n][2] if lang == "ru" else n, callback_data=f"city:{n}") for n in names]
    return InlineKeyboardMarkup([btns[i:i + 2] for i in range(0, len(btns), 2)])
def app_kb(lang):
    if not WEB_APP_URL:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(TXT[lang]["open_app"], web_app=WebAppInfo(url=WEB_APP_URL))]])

# ---------- buyruqlar ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TXT["uz"]["choose_lang"], reply_markup=lang_kb())

async def on_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = q.data.split(":")[1]
    u = USERS.setdefault(str(q.from_user.id), {"city": "Toshkent", "remind": True})
    u["lang"] = lang; save_db(USERS)
    await q.edit_message_text(TXT[lang]["choose_city"], reply_markup=city_kb(lang))

async def on_city(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    city = q.data.split(":", 1)[1]
    u = USERS.setdefault(str(q.from_user.id), {"lang": "uz", "remind": True})
    u["city"] = city; u["remind"] = True; save_db(USERS)
    lang = u.get("lang", "uz")
    await q.edit_message_text(TXT[lang]["saved"], reply_markup=app_kb(lang))

async def vaqt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    if not u or "city" not in u:
        return await update.message.reply_text(TXT["uz"]["nocity"] + " / " + TXT["ru"]["nocity"])
    lang = u["lang"]; day = await get_day(u["city"]); t = day["t"]
    lines = [TXT[lang]["today"].format(city=CITIES[u["city"]][2] if lang == "ru" else u["city"]), ""]
    lines += [f"{TXT[lang]['names'][k]}: {t[k]}" for k in PRAYERS]
    text = "\n".join(lines)
    if day["ramadan"]:
        text += TXT[lang]["ram"].format(f=t["Fajr"], m=t["Maghrib"])
    await update.message.reply_text(text, reply_markup=app_kb(lang))

async def app(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    kb = app_kb(u["lang"])
    await update.message.reply_text(TXT[u["lang"]]["open_app"] + " ⬇️" if kb else "WEB_APP_URL yo'q", reply_markup=kb)

async def toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    if not u:
        return await update.message.reply_text(TXT["uz"]["nocity"] + " / " + TXT["ru"]["nocity"])
    u["remind"] = not u.get("remind", True); save_db(USERS)
    await update.message.reply_text(TXT[u["lang"]]["on" if u["remind"] else "off"])

async def til(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TXT["uz"]["choose_lang"], reply_markup=lang_kb())

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    await update.message.reply_text(TXT[u["lang"]]["help"])

# ---------- eslatmalar (har daqiqada tekshiradi) ----------
async def reminder_job(ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ).strftime("%H:%M")
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    sent = ctx.bot_data.setdefault("sent", set())
    if len(sent) > 5000:
        sent.clear()
    for uid, u in list(USERS.items()):
        if not u.get("remind", True) or "city" not in u or "lang" not in u:
            continue
        try:
            day = await get_day(u["city"])
        except Exception as e:
            logging.warning("vaqt olinmadi: %s", e); continue
        lang, t, ram = u["lang"], day["t"], day["ramadan"]
        names = TXT[lang]["names"]
        for k in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
            for offset in (10, 0):
                if minus(t[k], offset) != now:
                    continue
                key = (uid, today, k, offset)
                if key in sent:
                    continue
                sent.add(key)
                if ram and k == "Fajr":
                    msg = TXT[lang]["sahar10" if offset else "sahar_now"].format(t=t[k])
                elif ram and k == "Maghrib":
                    msg = TXT[lang]["iftar10" if offset else "iftar_now"].format(t=t[k])
                else:
                    msg = TXT[lang]["remind10" if offset else "now"].format(name=names[k], t=t[k])
                try:
                    await ctx.bot.send_message(int(uid), msg)
                except Exception as e:
                    logging.warning("yuborilmadi %s: %s", uid, e)

# ---------- kichik veb-server (mini ilova + hosting uyg'onib turishi uchun) ----------
def run_web():
    handler = functools.partial(SimpleHTTPRequestHandler, directory=os.path.join(os.path.dirname(__file__) or ".", "web"))
    ThreadingHTTPServer(("0.0.0.0", PORT), handler).serve_forever()

def main():
    threading.Thread(target=run_web, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("vaqt", vaqt))
    application.add_handler(CommandHandler("app", app))
    application.add_handler(CommandHandler("eslatma", toggle))
    application.add_handler(CommandHandler("til", til))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CallbackQueryHandler(on_lang, pattern="^lang:"))
    application.add_handler(CallbackQueryHandler(on_city, pattern="^city:"))
    now = datetime.now(TZ)
    application.job_queue.run_repeating(reminder_job, interval=60, first=60 - now.second)
    application.run_polling()

if __name__ == "__main__":
    main()
