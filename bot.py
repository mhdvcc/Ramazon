import os, json, logging, threading, functools, asyncio
from collections import Counter
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from zoneinfo import ZoneInfo

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ["BOT_TOKEN"]                 # BotFather bergan token
WEB_APP_URL = os.environ.get("WEB_APP_URL", "")  # mini ilova manzili (https://...)
PORT = int(os.environ.get("PORT", "8080"))
TZ = ZoneInfo("Asia/Tashkent")
DB = "users.json"
# Admin: Telegram username (@siz) yoki ID. Render'da ADMIN_USERNAMES / ADMIN_IDS orqali o'zgartirsa bo'ladi.
ADMIN_USERNAMES = {x.strip().lower().lstrip("@") for x in os.environ.get("ADMIN_USERNAMES", "mhdvcc").split(",") if x.strip()}
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()}

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
        "menu_hint": "Pastdagi menyudan foydalaning 👇",
        "settings": "⚙️ Sozlamalar", "set_lang": "🌐 Tilni o'zgartirish", "set_city": "🏙 Shaharni o'zgartirish",
        "sahur_msg": "🌙 Saharlik tugashi: {f}\n⏳ {lf} qoldi\n\n🌅 Iftor: {m}\n⏳ {lm} qoldi",
        "not_ram": "\n\nℹ️ Ramazon hali boshlanmagan. Hozircha Bomdod va Shom vaqti ko'rsatildi.",
        "h": "soat", "mi": "daqiqa",
        "duas": "🤲 Ramazon duolari\n\n🌙 Saharlik (ro'za niyati)\nنَوَيْتُ أَنْ أَصُومَ صَوْمَ شَهْرِ رَمَضَانَ مِنَ الْفَجْرِ إِلَى الْمَغْرِبِ خَالِصًا لِلّٰهِ تَعَالَى\nNavaytu an asuma sovma shahri ramazona minal fajri ilal mag'ribi, xolisan lillahi ta'ala.\n\n🌅 Iftor duosi\nاللَّهُمَّ لَكَ صُمْتُ وَبِكَ آمَنْتُ وَعَلَيْكَ تَوَكَّلْتُ وَعَلَى رِزْقِكَ أَفْطَرْتُ\nAllohumma laka sumtu va bika amantu va 'alayka tavakkaltu va 'ala rizqika aftartu.\n\n✨ Iftordan keyin\nذَهَبَ الظَّمَأُ وَابْتَلَّتِ الْعُرُوقُ وَثَبَتَ الْأَجْرُ إِنْ شَاءَ اللّٰهُ\nZahabaz zama'u vabtallatil 'uruqu va sabatal ajru in sha Alloh.\n\n🌟 Qadr kechasi\nاللَّهُمَّ إِنَّكَ عَفُوٌّ تُحِبُّ الْعَفْوَ فَاعْفُ عَنِّي\nAllohumma innaka 'afuvvun tuhibbul 'afva fa'fu 'anni.",
        "mode_title": "🔔 Eslatma turini tanlang:",
        "mode_both": "⏰ 10 daqiqa oldin va vaqti kirganda", "mode_exact": "🕌 Faqat vaqti kirganda", "mode_off": "🔕 O'chirish",
        "mode_set": "✅ Saqlandi:",
        "guide": "📖 Yo'riqnoma\n\n1️⃣ /start bosing, til va shaharingizni tanlang.\n2️⃣ 🕌 Namoz vaqtlari: bugungi 6 ta vaqt.\n3️⃣ 🌙 Saharlik va iftor: tugash va ochish vaqti, qancha qolgani.\n4️⃣ 📱 Mini ilova: oylik taqvim, tasbeh va duolar.\n5️⃣ 🔔 Eslatma: namozdan 10 daqiqa oldin va vaqti kirganda xabar yuboraman. Turini o'zingiz tanlaysiz.\n6️⃣ ⚙️ Sozlamalar: til yoki shaharni o'zgartirish.\n\n🌙 Ramazonda bomdoddan oldin saharlik tugashini, shomdan oldin iftorni eslataman, iftor duosi bilan.\n\n💡 Eslatmalar kelishi uchun botni ovozsiz (mute) qilmang.",
        "help_full": "🆘 Yordam\n\nBuyruqlar:\n/start — sozlash\n/vaqt — bugungi vaqtlar\n/app — mini ilova\n/eslatma — eslatma turi\n/til — tilni o'zgartirish\n/help — yordam\n\nMuammo bo'lsa:\n• Bot javob bermasa, /start ni qayta bosing.\n• Eslatma kelmasa, 🔔 Eslatma tugmasida yoqilganini tekshiring va botni mute qilmang.\n• Vaqtlar masjid vaqtidan 1–3 daqiqa farq qilishi mumkin, masjid vaqtiga ham qarang.\n• Mini ilova ochilmasa, 30 soniya kutib qayta urining.\n\n👤 Admin: @mhdvcc\nSavol va takliflar uchun yozing.",
        "admin_btn": "✉️ Adminga yozish",
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
        "menu_hint": "Пользуйтесь меню ниже 👇",
        "settings": "⚙️ Настройки", "set_lang": "🌐 Сменить язык", "set_city": "🏙 Сменить город",
        "sahur_msg": "🌙 Конец сухура: {f}\n⏳ осталось {lf}\n\n🌅 Ифтар: {m}\n⏳ осталось {lm}",
        "not_ram": "\n\nℹ️ Рамадан ещё не начался. Показано время Фаджра и Магриба.",
        "h": "ч", "mi": "мин",
        "duas": "🤲 Дуа Рамадана\n\n🌙 Сухур (намерение на пост)\nنَوَيْتُ أَنْ أَصُومَ صَوْمَ شَهْرِ رَمَضَانَ مِنَ الْفَجْرِ إِلَى الْمَغْرِبِ خَالِصًا لِلّٰهِ تَعَالَى\nНавайту ан асума соума шахри рамадана минал фаджри илаль магриби холисан лилляхи таала.\n\n🌅 Дуа ифтара\nاللَّهُمَّ لَكَ صُمْتُ وَبِكَ آمَنْتُ وَعَلَيْكَ تَوَكَّلْتُ وَعَلَى رِزْقِكَ أَفْطَرْتُ\nАллахумма лака сумту ва бика аманту ва аляйка таваккальту ва аля ризқика афтарту.\n\n✨ После ифтара\nذَهَبَ الظَّمَأُ وَابْتَلَّتِ الْعُرُوقُ وَثَبَتَ الْأَجْرُ إِنْ شَاءَ اللّٰهُ\nЗахабаз заму ва-бталлатиль уруку ва сабаталь аджру инша Аллах.\n\n🌟 Ночь Кадр\nاللَّهُمَّ إِنَّكَ عَفُوٌّ تُحِبُّ الْعَفْوَ فَاعْفُ عَنِّي\nАллахумма иннака 'афуввун тухиббуль-'афва фа'фу 'анни.",
        "mode_title": "🔔 Выберите тип напоминаний:",
        "mode_both": "⏰ За 10 минут и в момент намаза", "mode_exact": "🕌 Только в момент намаза", "mode_off": "🔕 Выключить",
        "mode_set": "✅ Сохранено:",
        "guide": "📖 Инструкция\n\n1️⃣ Нажмите /start, выберите язык и город.\n2️⃣ 🕌 Время намаза: 6 времён на сегодня.\n3️⃣ 🌙 Сухур и ифтар: время и сколько осталось.\n4️⃣ 📱 Приложение: календарь на месяц, тасбих и дуа.\n5️⃣ 🔔 Напоминания: за 10 минут и в момент намаза. Тип выбираете сами.\n6️⃣ ⚙️ Настройки: смена языка или города.\n\n🌙 В Рамадан напомню о конце сухура и об ифтаре, с дуа для ифтара.\n\n💡 Чтобы напоминания приходили, не отключайте уведомления бота.",
        "help_full": "🆘 Помощь\n\nКоманды:\n/start — настройка\n/vaqt — время на сегодня\n/app — приложение\n/eslatma — тип напоминаний\n/til — сменить язык\n/help — помощь\n\nЕсли что-то не работает:\n• Бот не отвечает: нажмите /start ещё раз.\n• Нет напоминаний: проверьте кнопку 🔔 Напоминания и не отключайте уведомления.\n• Время может отличаться от мечети на 1–3 минуты, ориентируйтесь и на мечеть.\n• Приложение не открывается: подождите 30 секунд и попробуйте снова.\n\n👤 Админ: @mhdvcc\nПишите по вопросам и предложениям.",
        "admin_btn": "✉️ Написать админу",
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
    await q.message.reply_text(TXT[lang]["menu_hint"], reply_markup=reply_kb(lang))

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
    if not u or "lang" not in u:
        return await update.message.reply_text(TXT["uz"]["nocity"] + " / " + TXT["ru"]["nocity"])
    lang = u["lang"]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(TXT[lang]["mode_both"], callback_data="mode:both")],
                               [InlineKeyboardButton(TXT[lang]["mode_exact"], callback_data="mode:exact")],
                               [InlineKeyboardButton(TXT[lang]["mode_off"], callback_data="mode:off")]])
    await update.message.reply_text(TXT[lang]["mode_title"], reply_markup=kb)

async def on_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    mode = q.data.split(":")[1]
    u = USERS.setdefault(str(q.from_user.id), {"lang": "uz", "city": "Toshkent"})
    u["mode"] = mode; u["remind"] = mode != "off"; save_db(USERS)
    lang = u.get("lang", "uz")
    await q.edit_message_text(TXT[lang]["mode_set"] + "\n" + TXT[lang]["mode_" + mode])

async def guide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    await update.message.reply_text(TXT[u.get("lang", "uz")]["guide"])

async def til(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TXT["uz"]["choose_lang"], reply_markup=lang_kb())

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    lang = u.get("lang", "uz")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(TXT[lang]["admin_btn"], url="https://t.me/mhdvcc")]])
    await update.message.reply_text(TXT[lang]["help_full"], reply_markup=kb)


BTN = {
    "uz": {"times": "🕌 Namoz vaqtlari", "sahur": "🌙 Saharlik va iftor", "app": "📱 Mini ilova",
           "dua": "🤲 Duolar", "remind": "🔔 Eslatma", "settings": "⚙️ Sozlamalar",
           "guide": "📖 Yo'riqnoma", "help": "🆘 Yordam"},
    "ru": {"times": "🕌 Время намаза", "sahur": "🌙 Сухур и ифтар", "app": "📱 Приложение",
           "dua": "🤲 Дуа", "remind": "🔔 Напоминания", "settings": "⚙️ Настройки",
           "guide": "📖 Инструкция", "help": "🆘 Помощь"},
}

def reply_kb(lang):
    b = BTN[lang]
    app_btn = KeyboardButton(b["app"], web_app=WebAppInfo(url=WEB_APP_URL)) if WEB_APP_URL else KeyboardButton(b["app"])
    return ReplyKeyboardMarkup(
        [[KeyboardButton(b["times"]), KeyboardButton(b["sahur"])],
         [app_btn, KeyboardButton(b["dua"])],
         [KeyboardButton(b["remind"]), KeyboardButton(b["settings"])],
         [KeyboardButton(b["guide"]), KeyboardButton(b["help"])]],
        resize_keyboard=True, is_persistent=True)

def _left(hhmm, lang):
    now = datetime.now(TZ)
    ns = now.hour * 3600 + now.minute * 60 + now.second
    h, m = map(int, hhmm.split(":"))
    d = (h * 3600 + m * 60 - ns) % 86400
    return f"{d // 3600} {TXT[lang]['h']} {d % 3600 // 60} {TXT[lang]['mi']}"

async def _need_setup(update):
    await update.message.reply_text(TXT["uz"]["nocity"] + " / " + TXT["ru"]["nocity"])

async def sahur(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    if not u or "city" not in u or "lang" not in u:
        return await _need_setup(update)
    lang = u["lang"]; day = await get_day(u["city"]); t = day["t"]
    text = TXT[lang]["sahur_msg"].format(f=t["Fajr"], m=t["Maghrib"], lf=_left(t["Fajr"], lang), lm=_left(t["Maghrib"], lang))
    if not day["ramadan"]:
        text += TXT[lang]["not_ram"]
    await update.message.reply_text(text)

async def duolar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    await update.message.reply_text(TXT[u.get("lang", "uz")]["duas"])

async def settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    if not u or "lang" not in u:
        return await _need_setup(update)
    lang = u["lang"]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(TXT[lang]["set_lang"], callback_data="set:lang")],
                               [InlineKeyboardButton(TXT[lang]["set_city"], callback_data="set:city")]])
    await update.message.reply_text(TXT[lang]["settings"], reply_markup=kb)

async def on_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = user(q.from_user.id) or {"lang": "uz"}
    lang = u.get("lang", "uz")
    if q.data == "set:lang":
        await q.edit_message_text(TXT["uz"]["choose_lang"], reply_markup=lang_kb())
    else:
        await q.edit_message_text(TXT[lang]["choose_city"], reply_markup=city_kb(lang))

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    actions = {"times": vaqt, "sahur": sahur, "app": app, "dua": duolar, "remind": toggle, "settings": settings, "guide": guide, "help": help_cmd}
    for labels in BTN.values():
        for key, label in labels.items():
            if text == label:
                return await actions[key](update, ctx)


# ---------- admin ----------
def is_admin(update: Update) -> bool:
    u = update.effective_user
    return bool(u) and (u.id in ADMIN_IDS or (u.username or "").lower() in ADMIN_USERNAMES)

async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID: {update.effective_user.id}")

async def admin_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    total = len(USERS)
    langs = Counter(u.get("lang", "?") for u in USERS.values())
    cities = Counter(u.get("city", "?") for u in USERS.values()).most_common(6)
    modes = Counter((u.get("mode") or ("both" if u.get("remind", True) else "off")) for u in USERS.values())
    text = (f"👑 Admin paneli\n\n👥 Foydalanuvchilar: {total}\n"
            f"🇺🇿 O'zbekcha: {langs.get('uz', 0)}\n🇷🇺 Ruscha: {langs.get('ru', 0)}\n\n"
            f"🏙 Shaharlar:\n" + "\n".join(f"• {c}: {n}" for c, n in cities) +
            f"\n\n🔔 Eslatma: 10 daq+vaqt {modes.get('both', 0)}, faqat vaqt {modes.get('exact', 0)}, o'chiq {modes.get('off', 0)}"
            "\n\nHammaga xabar yuborish:\n/broadcast Matn shu yerda")
    await update.message.reply_text(text)

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    parts = (update.message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await update.message.reply_text("Ishlatish: /broadcast Xabar matni")
    msg = parts[1].strip()
    await update.message.reply_text(f"📤 Yuborilmoqda: {len(USERS)} ta foydalanuvchi...")
    ok = fail = 0
    for uid in list(USERS):
        try:
            await ctx.bot.send_message(int(uid), msg)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"✅ Yuborildi: {ok}\n❌ Yuborilmadi (bot bloklangan): {fail}")

# ---------- eslatmalar (har daqiqada tekshiradi) ----------
async def reminder_job(ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ).strftime("%H:%M")
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    sent = ctx.bot_data.setdefault("sent", set())
    if len(sent) > 5000:
        sent.clear()
    for uid, u in list(USERS.items()):
        mode = u.get("mode") or ("both" if u.get("remind", True) else "off")
        if mode == "off" or "city" not in u or "lang" not in u:
            continue
        offsets = (10, 0) if mode == "both" else (0,)
        try:
            day = await get_day(u["city"])
        except Exception as e:
            logging.warning("vaqt olinmadi: %s", e); continue
        lang, t, ram = u["lang"], day["t"], day["ramadan"]
        names = TXT[lang]["names"]
        for k in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
            for offset in offsets:
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
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CallbackQueryHandler(on_lang, pattern="^lang:"))
    application.add_handler(CallbackQueryHandler(on_city, pattern="^city:"))
    application.add_handler(CallbackQueryHandler(on_set, pattern="^set:"))
    application.add_handler(CallbackQueryHandler(on_mode, pattern="^mode:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    now = datetime.now(TZ)
    application.job_queue.run_repeating(reminder_job, interval=60, first=60 - now.second)
    application.run_polling()

if __name__ == "__main__":
    main()
