"""Ramazon · Namoz vaqti — Telegram bot.

Namoz vaqtlari O'zbekiston Muftiyati jadvallariga mos qilib o'zimiz hisoblanadi
(tashqi API kerak emas): Bomdod 15.5°, Xufton 15.25°, Asr hanafiy, Shom = quyosh botishidan +4 daqiqa.
"""
import os, json, math, logging, threading, functools, asyncio
from datetime import datetime, date, timedelta
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from zoneinfo import ZoneInfo

import httpx
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo,
                      ReplyKeyboardMarkup, KeyboardButton)
from telegram.error import BadRequest
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler, MessageHandler,
                          ContextTypes, filters)

TOKEN = os.environ["BOT_TOKEN"]
WEB_APP_URL = os.environ.get("WEB_APP_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "8080"))
SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_KEY", "")
TZ = ZoneInfo("Asia/Tashkent")
DB = "users.json"
ADMIN = "@mhdvcc"

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------- shaharlar
# nomi: (kenglik, uzunlik, ruscha nomi)
CITIES = {
    "Toshkent": (41.2995, 69.2401, "Ташкент"), "Samarqand": (39.6542, 66.9597, "Самарканд"),
    "Buxoro": (39.7747, 64.4286, "Бухара"), "Andijon": (40.7821, 72.3442, "Андижан"),
    "Namangan": (40.9983, 71.6726, "Наманган"), "Farg'ona": (40.3842, 71.7843, "Фергана"),
    "Qarshi": (38.8606, 65.7891, "Карши"), "Navoiy": (40.0844, 65.3792, "Навои"),
    "Nukus": (42.4531, 59.6103, "Нукус"), "Urganch": (41.5506, 60.6317, "Ургенч"),
    "Termiz": (37.2242, 67.2783, "Термез"), "Jizzax": (40.1158, 67.8422, "Джизак"),
    "Guliston": (40.4897, 68.7842, "Гулистан"), "Xiva": (41.3775, 60.3640, "Хива"),
    "Qo'qon": (40.5286, 70.9425, "Коканд"), "Marg'ilon": (40.4711, 71.7247, "Маргилан"),
    "Angren": (41.0167, 70.1436, "Ангрен"), "Chirchiq": (41.4689, 69.5822, "Чирчик"),
    "Olmaliq": (40.8447, 69.5984, "Алмалык"), "Bekobod": (40.2208, 69.2697, "Бекабад"),
    "Nurafshon": (41.0417, 69.3578, "Нурафшон"), "Yangiyo'l": (41.1117, 69.0475, "Янгиюль"),
    "Shahrisabz": (39.0578, 66.8342, "Шахрисабз"), "Kattaqo'rg'on": (39.8997, 66.2564, "Каттакурган"),
    "Urgut": (39.4000, 67.2500, "Ургут"), "Denov": (38.2753, 67.8986, "Денау"),
    "Zarafshon": (41.5750, 64.2000, "Зарафшан"), "Uchquduq": (42.1558, 63.5559, "Учкудук"),
    "G'ijduvon": (40.1017, 64.6819, "Гиждуван"), "Qo'ng'irot": (43.0722, 58.9006, "Кунград"),
    "Asaka": (40.6411, 72.2386, "Асака"), "Shahrixon": (40.7114, 72.0556, "Шахрихан"),
    "Chust": (41.0033, 71.2372, "Чуст"), "Pop": (40.8731, 71.1103, "Пап"),
    "Rishton": (40.3569, 71.2847, "Риштан"), "Yangiyer": (40.2750, 68.8217, "Янгиер"),
}
KEYS = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]
PR = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]

# ---------------------------------------------------------------- Ramazon sanalari (taxminiy, Muftiyat e'lon qilgach yangilang)
RAMADAN = [(date(2027, 2, 9), date(2027, 3, 10)), (date(2028, 1, 29), date(2028, 2, 27))]

def ramadan_day(d):
    """Ramazonning nechanchi kuni (1..30) yoki 0."""
    for a, b in RAMADAN:
        if a <= d <= b:
            return (d - a).days + 1
    return 0

def next_ramadan(d):
    for a, b in RAMADAN:
        if d <= b:
            return a
    return None

# ---------------------------------------------------------------- hisoblash
P_FAJR, P_ISHA = 15.5, 15.25         # burchaklar
D_SUNRISE, D_ASR, D_MAGHRIB = -0.75, -0.75, 4.0   # daqiqa tuzatishlar (Muftiyat jadvaliga moslangan)

def _sunpos(d):
    jd = d.toordinal() + 1721424.5 + 7 / 24
    T = (jd - 2451545.0) / 36525
    L0 = (280.46646 + T * (36000.76983 + T * 0.0003032)) % 360
    M = 357.52911 + T * (35999.05029 - 0.0001537 * T)
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    Mr = math.radians(M)
    C = ((1.914602 - T * (0.004817 + 0.000014 * T)) * math.sin(Mr) + (0.019993 - 0.000101 * T) * math.sin(2 * Mr)
         + 0.000289 * math.sin(3 * Mr))
    tl = L0 + C
    om = 125.04 - 1934.136 * T
    lam = tl - 0.00569 - 0.00478 * math.sin(math.radians(om))
    eps0 = 23 + (26 + ((21.448 - T * (46.815 + T * (0.00059 - T * 0.001813)))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(om))
    dec = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam))))
    y = math.tan(math.radians(eps / 2)) ** 2
    L0r = math.radians(L0)
    eot = 4 * math.degrees(y * math.sin(2 * L0r) - 2 * e * math.sin(Mr) + 4 * e * y * math.sin(Mr) * math.cos(2 * L0r)
                            - 0.5 * y * y * math.sin(4 * L0r) - 1.25 * e * e * math.sin(2 * Mr))
    return dec, eot

_cache = {}
def prayer_times(city, d):
    """{'Fajr': daqiqa, ...} — kun boshidan daqiqalarda (butun son)."""
    key = (city, d.toordinal())
    if key in _cache:
        return _cache[key]
    lat, lon, _ = CITIES[city]
    dec, eot = _sunpos(d)
    noon = 12 * 60 + 5 * 60 - lon * 4 - eot
    p, de = math.radians(lat), math.radians(dec)

    def ang(a):
        c = (math.sin(math.radians(a)) - math.sin(p) * math.sin(de)) / (math.cos(p) * math.cos(de))
        return math.degrees(math.acos(max(-1, min(1, c)))) * 4

    asr_alt = math.degrees(math.atan(1 / (2 + math.tan(abs(p - de)))))
    raw = {"Fajr": noon - ang(-P_FAJR), "Sunrise": noon - ang(-0.833) + D_SUNRISE, "Dhuhr": noon,
           "Asr": noon + ang(asr_alt) + D_ASR, "Maghrib": noon + ang(-0.833) + D_MAGHRIB,
           "Isha": noon + ang(-P_ISHA)}
    res = {k: int(math.floor(v + 0.5)) for k, v in raw.items()}
    if len(_cache) > 4000:
        _cache.clear()
    _cache[key] = res
    return res

def hm(m):
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"

def now_tz():
    return datetime.now(TZ)

def next_prayer(city, now):
    """(nomi, qolgan_soniya, vaqt_matni, ertaga_mi)"""
    ns = now.hour * 3600 + now.minute * 60 + now.second
    t = prayer_times(city, now.date())
    for k in PR:
        if t[k] * 60 > ns:
            return k, t[k] * 60 - ns, hm(t[k]), False
    tm = prayer_times(city, now.date() + timedelta(days=1))
    return "Fajr", 86400 - ns + tm["Fajr"] * 60, hm(tm["Fajr"]), True

def last_prayer(city, now):
    ns = now.hour * 3600 + now.minute * 60 + now.second
    t = prayer_times(city, now.date())
    last = None
    for k in PR:
        if t[k] * 60 <= ns:
            last = (k, hm(t[k]))
    if last is None:
        y = prayer_times(city, now.date() - timedelta(days=1))
        last = ("Isha", hm(y["Isha"]))
    return last

def until(city, now, key):
    """key vaqtigacha (bugun, o'tgan bo'lsa ertaga) soniya."""
    ns = now.hour * 3600 + now.minute * 60 + now.second
    t = prayer_times(city, now.date())[key] * 60
    if t > ns:
        return t - ns
    return 86400 - ns + prayer_times(city, now.date() + timedelta(days=1))[key] * 60

# ---------------------------------------------------------------- matnlar
WEEK = {"uz": ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"],
        "ru": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]}
MONTH = {"uz": ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"],
         "ru": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]}

TXT = {
    "uz": {
        "choose_lang": "Tilni tanlang / Выберите язык:",
        "choose_city": "Shahringizni tanlang:",
        "saved": "✅ Tayyor! Namoz vaqtlari shaharingiz bo'yicha hisoblanadi va har namoz oldidan eslatma yuboraman.\n\nMini ilovani ochish uchun pastdagi tugmani bosing.",
        "menu_hint": "Pastdagi menyudan foydalaning 👇",
        "open_app": "🕌 Mini ilovani ochish",
        "names": {"Fajr": "Bomdod", "Sunrise": "Quyosh", "Dhuhr": "Peshin", "Asr": "Asr", "Maghrib": "Shom", "Isha": "Xufton"},
        "title": "🕌 Namoz vaqtlari — {city}",
        "date_line": "📅 {wd}, {d}-{mo} {y}   ⏰ {t}",
        "last": "✅ Oxirgi o'tgan: {n} ({t}) — o'tdi",
        "next": "⏭ Keyingi: {n} — {t}{tm}",
        "tomorrow": " (ertaga)",
        "left": "⏳ Qoldi: {x}",
        "ram_line": "🌙 Ramazon, {n}-kun\n🌙 Saharlik tugashi: {f}   🌅 Iftor: {m}",
        "ram_soon": "🌙 Ramazonga taxminan {d} kun qoldi",
        "src": "ℹ️ Vaqtlar O'zbekiston Muftiyati jadvaliga mos hisoblangan, 1 daqiqagacha farq bo'lishi mumkin.",
        "refresh": "🔄 Yangilash",
        "sahur_msg": "🌙 Saharlik tugashi (Bomdod): {f}\n⏳ {lf} qoldi\n\n🌅 Iftor (Shom): {m}\n⏳ {lm} qoldi",
        "not_ram": "\n\nℹ️ Ramazon hali boshlanmagan. Hozircha Bomdod va Shom vaqti ko'rsatildi.",
        "ram_cal_btn": "📅 Ramazon taqvimi (30 kun)",
        "ram_cal_title": "🌙 Ramazon taqvimi — {city}\n(taxminiy boshlanish: {start})\n\nKun · Sana · Saharlik · Iftor\n",
        "ram_cal_note": "\nℹ️ Ramazon boshlanish sanasi Muftiyat e'lon qilgach aniqlashadi.",
        "h": "soat", "mi": "daqiqa",
        "pre": "⏰ {n} namoziga 10 daqiqa qoldi ({t}).\n🚿 Tahorat qilib tayyorlaning.",
        "now": "🕌 {n} namozi vaqti kirdi ({t}).\n⏭ Keyingi: {nn} — {nt}{tm}\n🤲 Alloh namozlaringizni qabul qilsin!",
        "sahar10": "🌙 Saharlik tugashiga 10 daqiqa qoldi ({t}).\nNiyat: Navaytu an asuma sovma shahri ramazona minal fajri ilal mag'ribi, xolisan lillahi ta'ala.",
        "sahar_now": "🌙 Saharlik vaqti tugadi ({t}). Bomdod vaqti kirdi.\n🤲 Alloh ro'zangizni qabul qilsin!",
        "iftar30": "🌅 Iftorga 30 daqiqa qoldi ({t}).\n🤲 Duo qilish uchun yaxshi payt.",
        "iftar10": "🌅 Iftorga 10 daqiqa qoldi ({t}). Iftor duosiga tayyorlaning.",
        "iftar_now": "🌅 Iftor vaqti! ({t})\nAllohumma laka sumtu va bika amantu va 'alayka tavakkaltu va 'ala rizqika aftartu.\nIftoringiz qabul bo'lsin! 🤲",
        "juma": "🕌 Juma muborak! Bugun juma kuni.\nPeshin (Juma) namoziga 1 soat qoldi ({t}).",
        "settings": "⚙️ Sozlamalar", "set_lang": "🌐 Tilni o'zgartirish", "set_city": "🏙 Shaharni o'zgartirish",
        "mode_title": "🔔 Eslatma turini tanlang:",
        "mode_both": "⏰ 10 daqiqa oldin va vaqti kirganda", "mode_exact": "🕌 Faqat vaqti kirganda", "mode_off": "🔕 O'chirish",
        "mode_set": "✅ Saqlandi:",
        "nocity": "Avval /start bosing.",
        "duas": "🤲 Ramazon duolari\n\n🌙 Saharlik (ro'za niyati)\nنَوَيْتُ أَنْ أَصُومَ صَوْمَ شَهْرِ رَمَضَانَ مِنَ الْفَجْرِ إِلَى الْمَغْرِبِ خَالِصًا لِلّٰهِ تَعَالَى\nNavaytu an asuma sovma shahri ramazona minal fajri ilal mag'ribi, xolisan lillahi ta'ala.\n\n🌅 Iftor duosi\nاللَّهُمَّ لَكَ صُمْتُ وَبِكَ آمَنْتُ وَعَلَيْكَ تَوَكَّلْتُ وَعَلَى رِزْقِكَ أَفْطَرْتُ\nAllohumma laka sumtu va bika amantu va 'alayka tavakkaltu va 'ala rizqika aftartu.\n\n✨ Iftordan keyin\nذَهَبَ الظَّمَأُ وَابْتَلَّتِ الْعُرُوقُ وَثَبَتَ الْأَجْرُ إِنْ شَاءَ اللّٰهُ\nZahabaz zama'u vabtallatil 'uruqu va sabatal ajru in sha Alloh.\n\n🌟 Qadr kechasi\nاللَّهُمَّ إِنَّكَ عَفُوٌّ تُحِبُّ الْعَفْوَ فَاعْفُ عَنِّي\nAllohumma innaka 'afuvvun tuhibbul 'afva fa'fu 'anni.",
        "guide": "📖 Yo'riqnoma\n\n1️⃣ /start bosing, til va shaharingizni tanlang.\n2️⃣ 🕌 Namoz vaqtlari: bugungi vaqtlar, qaysi namoz o'tgani va keyingisiga qancha qolgani.\n3️⃣ 🌙 Saharlik va iftor: vaqti, qancha qolgani va 30 kunlik Ramazon taqvimi.\n4️⃣ 📱 Mini ilova: oylik taqvim, tasbeh va duolar.\n5️⃣ 🔔 Eslatma: namozdan 10 daqiqa oldin va vaqti kirganda xabar yuboraman. Turini o'zingiz tanlaysiz.\n6️⃣ ⚙️ Sozlamalar: til yoki shaharni o'zgartirish.\n\n🌙 Ramazonda iftorga 30 va 10 daqiqa qolganda, saharlik tugashidan oldin eslataman. Juma kuni ham eslatma bor.\n\n💡 Eslatmalar kelishi uchun botni ovozsiz (mute) qilmang.",
        "help_full": "🆘 Yordam\n\nBuyruqlar:\n/start — sozlash\n/vaqt — bugungi vaqtlar\n/app — mini ilova\n/eslatma — eslatma turi\n/til — tilni o'zgartirish\n/help — yordam\n\nMuammo bo'lsa:\n• Bot javob bermasa, /start ni qayta bosing.\n• Eslatma kelmasa, 🔔 Eslatma tugmasida yoqilganini tekshiring va botni mute qilmang.\n• Vaqtlar masjid vaqtidan 1 daqiqagacha farq qilishi mumkin.\n• Mini ilova ochilmasa, 30 soniya kutib qayta urining.\n\n👤 Admin: " + ADMIN + "\nSavol va takliflar uchun yozing.",
        "admin_btn": "✉️ Adminga yozish",
    },
    "ru": {
        "choose_lang": "Tilni tanlang / Выберите язык:",
        "choose_city": "Выберите ваш город:",
        "saved": "✅ Готово! Время намаза считается по вашему городу, и я буду напоминать перед каждым намазом.\n\nНажмите кнопку ниже, чтобы открыть приложение.",
        "menu_hint": "Пользуйтесь меню ниже 👇",
        "open_app": "🕌 Открыть приложение",
        "names": {"Fajr": "Фаджр", "Sunrise": "Восход", "Dhuhr": "Зухр", "Asr": "Аср", "Maghrib": "Магриб", "Isha": "Иша"},
        "title": "🕌 Время намаза — {city}",
        "date_line": "📅 {wd}, {d} {mo} {y}   ⏰ {t}",
        "last": "✅ Последний: {n} ({t}) — прошёл",
        "next": "⏭ Следующий: {n} — {t}{tm}",
        "tomorrow": " (завтра)",
        "left": "⏳ Осталось: {x}",
        "ram_line": "🌙 Рамадан, {n}-й день\n🌙 Конец сухура: {f}   🌅 Ифтар: {m}",
        "ram_soon": "🌙 До Рамадана примерно {d} дн.",
        "src": "ℹ️ Время рассчитано по таблицам Муфтията Узбекистана, возможна разница до 1 минуты.",
        "refresh": "🔄 Обновить",
        "sahur_msg": "🌙 Конец сухура (Фаджр): {f}\n⏳ осталось {lf}\n\n🌅 Ифтар (Магриб): {m}\n⏳ осталось {lm}",
        "not_ram": "\n\nℹ️ Рамадан ещё не начался. Показано время Фаджра и Магриба.",
        "ram_cal_btn": "📅 Календарь Рамадана (30 дней)",
        "ram_cal_title": "🌙 Календарь Рамадана — {city}\n(ориентировочное начало: {start})\n\nДень · Дата · Сухур · Ифтар\n",
        "ram_cal_note": "\nℹ️ Дата начала Рамадана уточнится после объявления Муфтията.",
        "h": "ч", "mi": "мин",
        "pre": "⏰ До намаза {n} 10 минут ({t}).\n🚿 Совершите омовение и приготовьтесь.",
        "now": "🕌 Наступило время намаза {n} ({t}).\n⏭ Следующий: {nn} — {nt}{tm}\n🤲 Пусть Аллах примет ваши намазы!",
        "sahar10": "🌙 До конца сухура 10 минут ({t}).\nНамерение: Навайту ан асума соума шахри рамадана минал фаджри илаль магриби холисан лилляхи таала.",
        "sahar_now": "🌙 Время сухура закончилось ({t}). Наступил Фаджр.\n🤲 Пусть Аллах примет ваш пост!",
        "iftar30": "🌅 До ифтара 30 минут ({t}).\n🤲 Хорошее время для дуа.",
        "iftar10": "🌅 До ифтара 10 минут ({t}). Приготовьтесь к дуа.",
        "iftar_now": "🌅 Время ифтара! ({t})\nАллахумма лака сумту ва бика аманту ва аляйка таваккальту ва аля ризқика афтарту.\nПусть Аллах примет ваш пост! 🤲",
        "juma": "🕌 Джума мубарак! Сегодня пятница.\nДо пятничного намаза остался 1 час ({t}).",
        "settings": "⚙️ Настройки", "set_lang": "🌐 Сменить язык", "set_city": "🏙 Сменить город",
        "mode_title": "🔔 Выберите тип напоминаний:",
        "mode_both": "⏰ За 10 минут и в момент намаза", "mode_exact": "🕌 Только в момент намаза", "mode_off": "🔕 Выключить",
        "mode_set": "✅ Сохранено:",
        "nocity": "Сначала нажмите /start.",
        "duas": "🤲 Дуа Рамадана\n\n🌙 Сухур (намерение на пост)\nنَوَيْتُ أَنْ أَصُومَ صَوْمَ شَهْرِ رَمَضَانَ مِنَ الْفَجْرِ إِلَى الْمَغْرِبِ خَالِصًا لِلّٰهِ تَعَالَى\nНавайту ан асума соума шахри рамадана минал фаджри илаль магриби холисан лилляхи таала.\n\n🌅 Дуа ифтара\nاللَّهُمَّ لَكَ صُمْتُ وَبِكَ آمَنْتُ وَعَلَيْكَ تَوَكَّلْتُ وَعَلَى رِزْقِكَ أَفْطَرْتُ\nАллахумма лака сумту ва бика аманту ва аляйка таваккальту ва аля ризқика афтарту.\n\n✨ После ифтара\nذَهَبَ الظَّمَأُ وَابْتَلَّتِ الْعُرُوقُ وَثَبَتَ الْأَجْرُ إِنْ شَاءَ اللّٰهُ\nЗахабаз заму ва-бталлатиль уруку ва сабаталь аджру инша Аллах.\n\n🌟 Ночь Кадр\nاللَّهُمَّ إِنَّكَ عَفُوٌّ تُحِبُّ الْعَفْوَ فَاعْفُ عَنِّي\nАллахумма иннака 'афуввун тухиббуль-'афва фа'фу 'анни.",
        "guide": "📖 Инструкция\n\n1️⃣ Нажмите /start, выберите язык и город.\n2️⃣ 🕌 Время намаза: время на сегодня, какой намаз прошёл и сколько осталось до следующего.\n3️⃣ 🌙 Сухур и ифтар: время, сколько осталось и календарь Рамадана на 30 дней.\n4️⃣ 📱 Приложение: календарь на месяц, тасбих и дуа.\n5️⃣ 🔔 Напоминания: за 10 минут и в момент намаза. Тип выбираете сами.\n6️⃣ ⚙️ Настройки: смена языка или города.\n\n🌙 В Рамадан напомню за 30 и 10 минут до ифтара и перед концом сухура. В пятницу тоже есть напоминание.\n\n💡 Чтобы напоминания приходили, не отключайте уведомления бота.",
        "help_full": "🆘 Помощь\n\nКоманды:\n/start — настройка\n/vaqt — время на сегодня\n/app — приложение\n/eslatma — тип напоминаний\n/til — сменить язык\n/help — помощь\n\nЕсли что-то не работает:\n• Бот не отвечает: нажмите /start ещё раз.\n• Нет напоминаний: проверьте кнопку 🔔 Напоминания и не отключайте уведомления.\n• Время может отличаться от мечети до 1 минуты.\n• Приложение не открывается: подождите 30 секунд и попробуйте снова.\n\n👤 Админ: " + ADMIN + "\nПишите по вопросам и предложениям.",
        "admin_btn": "✉️ Написать админу",
    },
}

BTN = {
    "uz": {"times": "🕌 Namoz vaqtlari", "sahur": "🌙 Saharlik va iftor", "app": "📱 Mini ilova",
           "dua": "🤲 Duolar", "remind": "🔔 Eslatma", "settings": "⚙️ Sozlamalar",
           "guide": "📖 Yo'riqnoma", "help": "🆘 Yordam"},
    "ru": {"times": "🕌 Время намаза", "sahur": "🌙 Сухур и ифтар", "app": "📱 Приложение",
           "dua": "🤲 Дуа", "remind": "🔔 Напоминания", "settings": "⚙️ Настройки",
           "guide": "📖 Инструкция", "help": "🆘 Помощь"},
}

def cname(city, lang):
    return CITIES[city][2] if lang == "ru" else city

def dur(sec, lang):
    sec = max(0, int(sec))
    h, m = sec // 3600, sec % 3600 // 60
    hh, mm = TXT[lang]["h"], TXT[lang]["mi"]
    if h and m:
        return f"{h} {hh} {m} {mm}"
    if h:
        return f"{h} {hh}"
    return f"{max(m, 1)} {mm}" if sec else f"0 {mm}"

# ---------------------------------------------------------------- saqlash (fayl + ixtiyoriy Supabase)
_lock = threading.Lock()

def _sb_headers(extra=None):
    h = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}", "Content-Type": "application/json"}
    h.update(extra or {})
    return h

def load_db():
    if SB_URL and SB_KEY:
        try:
            r = httpx.get(f"{SB_URL}/rest/v1/users?select=uid,data", headers=_sb_headers(), timeout=20)
            r.raise_for_status()
            db = {row["uid"]: row["data"] for row in r.json()}
            logging.info("Supabase'dan %d foydalanuvchi yuklandi", len(db))
            return db
        except Exception as e:
            logging.warning("Supabase o'qilmadi: %s", e)
    try:
        with open(DB, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _sb_upsert(uid, data):
    try:
        httpx.post(f"{SB_URL}/rest/v1/users", headers=_sb_headers({"Prefer": "resolution=merge-duplicates"}),
                   json={"uid": uid, "data": data}, timeout=20).raise_for_status()
    except Exception as e:
        logging.warning("Supabase yozilmadi: %s", e)

def save_db(db, uid=None):
    with _lock:
        try:
            with open(DB, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False)
        except Exception as e:
            logging.warning("fayl yozilmadi: %s", e)
    if SB_URL and SB_KEY and uid is not None and str(uid) in db:
        threading.Thread(target=_sb_upsert, args=(str(uid), db[str(uid)]), daemon=True).start()

USERS = load_db()

def user(uid):
    return USERS.get(str(uid))

# ---------------------------------------------------------------- tugmalar
def lang_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang:uz"),
                                  InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru")]])

def city_kb(lang):
    btns = [InlineKeyboardButton(cname(n, lang), callback_data=f"city:{n}") for n in CITIES]
    return InlineKeyboardMarkup([btns[i:i + 3] for i in range(0, len(btns), 3)])

def app_kb(lang):
    if not WEB_APP_URL:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(TXT[lang]["open_app"], web_app=WebAppInfo(url=WEB_APP_URL))]])

def reply_kb(lang):
    b = BTN[lang]
    app_btn = KeyboardButton(b["app"], web_app=WebAppInfo(url=WEB_APP_URL)) if WEB_APP_URL else KeyboardButton(b["app"])
    return ReplyKeyboardMarkup(
        [[KeyboardButton(b["times"]), KeyboardButton(b["sahur"])],
         [app_btn, KeyboardButton(b["dua"])],
         [KeyboardButton(b["remind"]), KeyboardButton(b["settings"])],
         [KeyboardButton(b["guide"]), KeyboardButton(b["help"])]],
        resize_keyboard=True, is_persistent=True)

async def _need_setup(update):
    await update.message.reply_text(TXT["uz"]["nocity"] + " / " + TXT["ru"]["nocity"])

def ready(u):
    return bool(u) and "city" in u and "lang" in u

# ---------------------------------------------------------------- namoz vaqtlari kartasi
def render_times(u, now=None):
    now = now or now_tz()
    lang, city = u["lang"], u["city"]
    L = TXT[lang]
    t = prayer_times(city, now.date())
    ns = now.hour * 3600 + now.minute * 60 + now.second
    nk, left, nt, tomorrow = next_prayer(city, now)
    lk, lt = last_prayer(city, now)
    lines = [L["title"].format(city=cname(city, lang)),
             L["date_line"].format(wd=WEEK[lang][now.weekday()], d=now.day, mo=MONTH[lang][now.month - 1],
                                   y=now.year, t=now.strftime("%H:%M")), ""]
    for k in KEYS:
        if t[k] * 60 <= ns:
            mark = "✅"
        elif k == nk and not tomorrow:
            mark = "🔸"
        else:
            mark = "▫️"
        lines.append(f"{mark} {L['names'][k]}: {hm(t[k])}")
    lines += ["", L["last"].format(n=L["names"][lk], t=lt),
              L["next"].format(n=L["names"][nk], t=nt, tm=L["tomorrow"] if tomorrow else ""),
              L["left"].format(x=dur(left, lang))]
    rd = ramadan_day(now.date())
    if rd:
        lines += ["", L["ram_line"].format(n=rd, f=hm(t["Fajr"]), m=hm(t["Maghrib"]))]
    else:
        nr = next_ramadan(now.date())
        if nr:
            lines += ["", L["ram_soon"].format(d=(nr - now.date()).days)]
    lines += ["", L["src"]]
    return "\n".join(lines)

def times_kb(lang):
    row = [InlineKeyboardButton(TXT[lang]["refresh"], callback_data="refresh")]
    if WEB_APP_URL:
        row.append(InlineKeyboardButton(TXT[lang]["open_app"], web_app=WebAppInfo(url=WEB_APP_URL)))
    return InlineKeyboardMarkup([row])

async def vaqt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    if not ready(u):
        return await _need_setup(update)
    await update.message.reply_text(render_times(u), reply_markup=times_kb(u["lang"]))

async def on_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    u = user(q.from_user.id)
    if not ready(u):
        return await q.answer()
    try:
        await q.edit_message_text(render_times(u), reply_markup=times_kb(u["lang"]))
        await q.answer("✅")
    except BadRequest:
        await q.answer("✅")

async def sahur(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    if not ready(u):
        return await _need_setup(update)
    lang, city = u["lang"], u["city"]
    now = now_tz(); t = prayer_times(city, now.date()); L = TXT[lang]
    text = L["sahur_msg"].format(f=hm(t["Fajr"]), m=hm(t["Maghrib"]),
                                 lf=dur(until(city, now, "Fajr"), lang), lm=dur(until(city, now, "Maghrib"), lang))
    if not ramadan_day(now.date()):
        text += L["not_ram"]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(L["ram_cal_btn"], callback_data="ramcal")]])
    await update.message.reply_text(text, reply_markup=kb)

async def on_ramcal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = user(q.from_user.id)
    if not ready(u):
        return
    lang, city = u["lang"], u["city"]; L = TXT[lang]
    start = next_ramadan(now_tz().date()) or RAMADAN[0][0]
    rows = []
    for i in range(30):
        d = start + timedelta(days=i)
        t = prayer_times(city, d)
        rows.append(f"{i + 1:>2} · {d.day:02d}.{d.month:02d} · {hm(t['Fajr'])} · {hm(t['Maghrib'])}")
    start_txt = f"{start.day}-{MONTH[lang][start.month - 1]}" if lang == "uz" else f"{start.day} {MONTH[lang][start.month - 1]}"
    text = L["ram_cal_title"].format(city=cname(city, lang), start=start_txt) + "\n".join(rows) + L["ram_cal_note"]
    await q.message.reply_text(text)

async def duolar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    await update.message.reply_text(TXT[u.get("lang", "uz")]["duas"])

async def guide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    await update.message.reply_text(TXT[u.get("lang", "uz")]["guide"])

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    lang = u.get("lang", "uz")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(TXT[lang]["admin_btn"], url=f"https://t.me/{ADMIN.lstrip('@')}")]])
    await update.message.reply_text(TXT[lang]["help_full"], reply_markup=kb)

async def app(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id) or {"lang": "uz"}
    lang = u.get("lang", "uz")
    kb = app_kb(lang)
    await update.message.reply_text(TXT[lang]["open_app"] + " ⬇️" if kb else "WEB_APP_URL yo'q", reply_markup=kb)

async def toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = user(update.effective_user.id)
    if not u or "lang" not in u:
        return await _need_setup(update)
    lang = u["lang"]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(TXT[lang]["mode_both"], callback_data="mode:both")],
                               [InlineKeyboardButton(TXT[lang]["mode_exact"], callback_data="mode:exact")],
                               [InlineKeyboardButton(TXT[lang]["mode_off"], callback_data="mode:off")]])
    await update.message.reply_text(TXT[lang]["mode_title"], reply_markup=kb)

async def on_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    mode = q.data.split(":")[1]
    u = USERS.setdefault(str(q.from_user.id), {"lang": "uz", "city": "Toshkent"})
    u["mode"] = mode; u["remind"] = mode != "off"; save_db(USERS, q.from_user.id)
    lang = u.get("lang", "uz")
    await q.edit_message_text(TXT[lang]["mode_set"] + "\n" + TXT[lang]["mode_" + mode])

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

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TXT["uz"]["choose_lang"], reply_markup=lang_kb())

async def til(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TXT["uz"]["choose_lang"], reply_markup=lang_kb())

async def on_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = q.data.split(":")[1]
    u = USERS.setdefault(str(q.from_user.id), {"city": "Toshkent", "remind": True})
    u["lang"] = lang; save_db(USERS, q.from_user.id)
    await q.edit_message_text(TXT[lang]["choose_city"], reply_markup=city_kb(lang))

async def on_city(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    city = q.data.split(":", 1)[1]
    if city not in CITIES:
        return
    u = USERS.setdefault(str(q.from_user.id), {"lang": "uz", "remind": True})
    u["city"] = city
    u.setdefault("mode", "both"); u["remind"] = u["mode"] != "off"
    save_db(USERS, q.from_user.id)
    lang = u.get("lang", "uz")
    await q.edit_message_text(TXT[lang]["saved"], reply_markup=app_kb(lang))
    await q.message.reply_text(TXT[lang]["menu_hint"], reply_markup=reply_kb(lang))
    await q.message.reply_text(render_times(u), reply_markup=times_kb(lang))

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    actions = {"times": vaqt, "sahur": sahur, "app": app, "dua": duolar, "remind": toggle,
               "settings": settings, "guide": guide, "help": help_cmd}
    for labels in BTN.values():
        for key, label in labels.items():
            if text == label:
                return await actions[key](update, ctx)

# ---------------------------------------------------------------- eslatmalar
def reminder_events(u, now):
    """Shu daqiqada yuborilishi kerak bo'lgan xabarlar: [(kalit, matn)]"""
    lang, city = u["lang"], u["city"]; L = TXT[lang]
    mode = u.get("mode") or ("both" if u.get("remind", True) else "off")
    if mode == "off":
        return []
    cur = now.hour * 60 + now.minute
    t = prayer_times(city, now.date())
    ram = ramadan_day(now.date()) > 0
    names = L["names"]
    out = []
    for k in PR:
        evs = [(0, "now")]
        if mode == "both":
            evs.append((10, "pre"))
            if ram and k == "Maghrib":
                evs.append((30, "iftar30"))
        for off, kind in evs:
            if (t[k] - off) % 1440 != cur:
                continue
            if ram and k == "Fajr":
                text = L["sahar10"] if kind == "pre" else L["sahar_now"]
            elif ram and k == "Maghrib":
                text = {"iftar30": L["iftar30"], "pre": L["iftar10"], "now": L["iftar_now"]}[kind].format(t=hm(t[k]))
            elif kind == "pre":
                text = L["pre"].format(n=names[k], t=hm(t[k]))
            else:
                nk, left, nt, tomorrow = next_prayer(city, now + timedelta(minutes=1))
                text = L["now"].format(n=names[k], t=hm(t[k]), nn=names[nk], nt=nt,
                                       tm=L["tomorrow"] if tomorrow else "")
            if "{t}" in text:
                text = text.format(t=hm(t[k]))
            out.append((f"{k}:{kind}", text))
    if now.weekday() == 4 and (t["Dhuhr"] - 60) % 1440 == cur:
        out.append(("juma", L["juma"].format(t=hm(t["Dhuhr"]))))
    return out

async def reminder_job(ctx: ContextTypes.DEFAULT_TYPE):
    now = now_tz()
    today = now.strftime("%Y-%m-%d")
    sent = ctx.bot_data.setdefault("sent", set())
    if len(sent) > 20000:
        sent.clear()
    for uid, u in list(USERS.items()):
        if not ready(u):
            continue
        try:
            events = reminder_events(u, now)
        except Exception as e:
            logging.warning("eslatma hisoblanmadi %s: %s", uid, e)
            continue
        for key, text in events:
            k = (uid, today, key)
            if k in sent:
                continue
            sent.add(k)
            try:
                await ctx.bot.send_message(int(uid), text)
            except Exception as e:
                logging.warning("yuborilmadi %s: %s", uid, e)
            await asyncio.sleep(0.04)

# ---------------------------------------------------------------- kichik veb-server (mini ilova + uyg'oq turish)
def run_web():
    handler = functools.partial(SimpleHTTPRequestHandler, directory=os.path.join(os.path.dirname(__file__) or ".", "web"))
    ThreadingHTTPServer(("0.0.0.0", PORT), handler).serve_forever()

def main():
    threading.Thread(target=run_web, daemon=True).start()
    application = Application.builder().token(TOKEN).build()
    for name, fn in [("start", start), ("vaqt", vaqt), ("app", app), ("eslatma", toggle), ("til", til), ("help", help_cmd)]:
        application.add_handler(CommandHandler(name, fn))
    application.add_handler(CallbackQueryHandler(on_lang, pattern="^lang:"))
    application.add_handler(CallbackQueryHandler(on_city, pattern="^city:"))
    application.add_handler(CallbackQueryHandler(on_set, pattern="^set:"))
    application.add_handler(CallbackQueryHandler(on_mode, pattern="^mode:"))
    application.add_handler(CallbackQueryHandler(on_refresh, pattern="^refresh$"))
    application.add_handler(CallbackQueryHandler(on_ramcal, pattern="^ramcal$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    now = datetime.now(TZ)
    application.job_queue.run_repeating(reminder_job, interval=60, first=60 - now.second)
    application.run_polling()

if __name__ == "__main__":
    main()
