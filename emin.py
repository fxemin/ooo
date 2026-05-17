import telebot
import threading
import time
import os
import requests
import certifi
from datetime import datetime, timezone, timedelta
from flask import Flask
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from bson import ObjectId
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ╔══════════════════════════════════════════════════════════╗
#                     КОНФИГУРАЦИЯ
# ╚══════════════════════════════════════════════════════════╝
BOT_TOKEN    = "8361874404:AAFtGTflPuqUJC9zL1oVg90WuJRrDLOQzKY"
ADMIN_ID     = 6824684800
RENDER_URL   = "https://vpn-bot-z9rj.onrender.com"

MONGO_URI = (
    "mongodb+srv://emin_saparbayew09:emin.1235.@emin.ri18oi5.mongodb.net"
    "/?retryWrites=true&w=majority&appName=Emin"
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ╔══════════════════════════════════════════════════════════╗
#                      MONGODB
# ╚══════════════════════════════════════════════════════════╝
_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=10000)
try:
    _client.admin.command("ping")
    print("MongoDB OK")
except ConnectionFailure:
    print("MongoDB FAIL")

_db               = _client["bot_data"]
col_users         = _db["users"]
col_sponsors      = _db["sponsors"]
col_addlist       = _db["addlist"]
col_settings      = _db["settings"]
col_reklam        = _db["reklam"]
col_tgrass_ch     = _db["tgrass_channels"]
col_post_channels = _db["post_channels"]

col_users.create_index("user_id", unique=True)

# ╔══════════════════════════════════════════════════════════╗
#                      FSM
# ╚══════════════════════════════════════════════════════════╝
_states   = {}
user_data = {}

def set_state(uid, state, **kw):
    _states[uid]   = state
    user_data[uid] = kw

def clear_state(uid):
    _states.pop(uid, None)
    user_data.pop(uid, None)

def get_state(uid):
    return _states.get(uid)

# ╔══════════════════════════════════════════════════════════╗
#                    НАСТРОЙКИ
# ╚══════════════════════════════════════════════════════════╝
def get_setting(key, default=""):
    doc = col_settings.find_one({"key": key})
    return doc["value"] if doc else default

def set_setting(key, value):
    col_settings.update_one({"key": key}, {"$set": {"value": value}}, upsert=True)

for _k, _v in [
    ("vpn_code",      "SHADOWVIP-2024"),
    ("tgrass",        "on"),
    ("tgrass_username", ""),
    ("welcome_text",
     "👋 <b>Salam, bota hoş geldiňiz!</b>\n\n"
     "VPN kodyny almak üçin aşakdaky kanallara agza boluň 👇"),
]:
    if not get_setting(_k):
        set_setting(_k, _v)

# ╔══════════════════════════════════════════════════════════╗
#                 ПОЛЬЗОВАТЕЛИ
# ╚══════════════════════════════════════════════════════════╝
def db_add_user(user_id, username):
    if col_users.find_one({"user_id": user_id}):
        return False
    col_users.insert_one({
        "user_id":   user_id,
        "username":  username or "",
        "join_date": datetime.now(timezone.utc).isoformat(),
    })
    return True

def db_get_all_users():
    return [d["user_id"] for d in col_users.find({}, {"user_id": 1})]

def db_get_stats():
    now    = datetime.now(timezone.utc)
    d1_ago = (now - timedelta(days=1)).isoformat()
    d7_ago = (now - timedelta(days=7)).isoformat()
    total  = col_users.count_documents({})
    today  = col_users.count_documents({"join_date": {"$gte": d1_ago}})
    week   = col_users.count_documents({"join_date": {"$gte": d7_ago}})
    return total, today, week

def db_get_growth():
    now = datetime.now(timezone.utc)
    res = []
    for i in range(6, -1, -1):
        ds = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        de = ds + timedelta(days=1)
        c  = col_users.count_documents({
            "join_date": {"$gte": ds.isoformat(), "$lt": de.isoformat()}
        })
        res.append((ds.strftime("%d.%m"), c))
    return res

# ╔══════════════════════════════════════════════════════════╗
#                  КАНАЛЫ — СПОНСОР / ADDLIST
# ╚══════════════════════════════════════════════════════════╝
def _ch_list(col):
    return [(str(d["_id"]), d.get("link",""), d.get("name",""), d.get("username",""))
            for d in col.find()]

def _add_ch(col, link, name, username):
    u = username.strip().lstrip("@")
    col.update_one({"username": u},
                   {"$set": {"link": link, "name": name, "username": u}}, upsert=True)

def _del_ch(col, doc_id):
    try: col.delete_one({"_id": ObjectId(doc_id)})
    except Exception: pass

def get_sponsors():    return _ch_list(col_sponsors)
def get_addlist():     return _ch_list(col_addlist)
def add_sponsor(l,n,u):  _add_ch(col_sponsors, l, n, u)
def add_addlist(l,n,u):  _add_ch(col_addlist,  l, n, u)
def del_sponsor(i):    _del_ch(col_sponsors, i)
def del_addlist(i):    _del_ch(col_addlist,  i)

def parse_channel_args(text):
    parts = text.strip().split(maxsplit=2)
    if len(parts) < 3:
        return None, None, None
    name, raw = parts[1], parts[2].strip()
    if raw.startswith("@"):
        return name, "https://t.me/" + raw.lstrip("@"), raw
    if "t.me/" in raw:
        u = "@" + raw.split("t.me/")[-1].split("/")[0]
        return name, raw, u
    return name, "https://t.me/" + raw, "@" + raw

# ╔══════════════════════════════════════════════════════════╗
#                  ПОСТ-КАНАЛЫ
# ╚══════════════════════════════════════════════════════════╝
def get_post_channels():
    return list(col_post_channels.find())

def add_post_channel(name, username):
    u = username.strip().lstrip("@")
    col_post_channels.update_one({"username": u},
                                 {"$set": {"name": name, "username": u}}, upsert=True)

def del_post_channel(doc_id):
    try: col_post_channels.delete_one({"_id": ObjectId(doc_id)})
    except Exception: pass

# ╔══════════════════════════════════════════════════════════╗
#                    РЕКЛАМА
# ╚══════════════════════════════════════════════════════════╝
def save_reklam(chat_id, msg_id):
    col_reklam.insert_one({"chat_id": str(chat_id), "message_id": msg_id})

def get_reklamlar():
    return [(d["chat_id"], d["message_id"]) for d in col_reklam.find()]

def clear_reklamlar():
    col_reklam.delete_many({})

# ╔══════════════════════════════════════════════════════════╗
#                  ADMIN YETKİ
# ╚══════════════════════════════════════════════════════════╝
def is_extra_admin(uid):
    return bool(col_settings.find_one({"key": f"extra_admin_{uid}"}))

# ╔══════════════════════════════════════════════════════════╗
#                  TGRASS
# ╚══════════════════════════════════════════════════════════╝
# ── TGrass yeni döküman: POST https://tgrass.space/offers
# ── Header: {"Auth": TOKEN, "Content-Type": "application/json"}
TGRASS_ENDPOINT = "https://tgrass.space/offers"
TGRASS_HEADERS  = {
    "Content-Type": "application/json",
    "Auth":         "b8c2b74f432a422b81113115f86aabe0",
}

def tgrass_fetch_channels():
    """
    TGrass API — POST https://tgrass.space/offers
    Genel kanal listesini çeker, MongoDB tgrass_channels koleksiyonuna kaydeder.
    """
    if get_setting("tgrass", "on") != "on":
        return 0, "TGrass kapalı"
    try:
        resp = requests.post(
            TGRASS_ENDPOINT,
            json={
                "tg_user_id": 0,
                "is_premium": False,
                "lang":       "en",
            },
            headers=TGRASS_HEADERS,
            timeout=30
        )
        if resp.status_code != 200:
            msg = f"HTTP {resp.status_code}: {resp.text[:100]}"
            print(f"[TGrass fetch] {msg}")
            return 0, msg
        data = resp.json()
        # Cevap: liste | {"offers":[...]} | {"status":"ok","offers":[...]}
        if isinstance(data, list):
            offers = data
        elif isinstance(data, dict):
            offers = data.get("offers", data.get("channels", []))
        else:
            offers = []
        count = 0
        for offer in offers:
            username = (offer.get("username") or offer.get("login") or
                        offer.get("channel_username") or "")
            name     = (offer.get("name") or offer.get("title") or username)
            link     = (offer.get("link") or offer.get("url") or
                        (f"https://t.me/{username.lstrip('@')}" if username else ""))
            if username and link:
                _add_ch(col_tgrass_channels, link, name, username)
                count += 1
        print(f"[TGrass fetch] {count} kanal kaydedildi")
        return count, "ok"
    except requests.exceptions.ConnectionError as e:
        msg = f"Bağlantı hatası: {str(e)[:60]}"
        print(f"[TGrass fetch] {msg}")
        return 0, msg
    except requests.exceptions.Timeout:
        print("[TGrass fetch] Timeout")
        return 0, "Timeout (30s)"
    except Exception as e:
        msg = str(e)[:80]
        print(f"[TGrass fetch] {msg}")
        return 0, msg

def tgrass_get_offers(user):
    """
    TGrass API — POST https://tgrass.space/offers (kullanıcıya özel)
    Kullanıcının abonelik durumunu döndürür.
    """
    if get_setting("tgrass", "on") != "on":
        return []
    try:
        resp = requests.post(
            TGRASS_ENDPOINT,
            json={
                "tg_user_id": user.id,
                "is_premium": bool(getattr(user, "is_premium", False)),
                "lang":       getattr(user, "language_code", "en") or "en",
            },
            headers=TGRASS_HEADERS,
            timeout=30
        )
        if resp.status_code != 200:
            print(f"[TGrass offers] HTTP {resp.status_code}")
            return []
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("offers", data.get("channels", []))
    except requests.exceptions.ConnectionError as e:
        print(f"[TGrass offers] Bağlantı hatası: {str(e)[:60]}")
        return []
    except requests.exceptions.Timeout:
        print("[TGrass offers] Timeout")
        return []
    except Exception as e:
        print(f"[TGrass offers] {e}")
        return []

def check_tgrass_subscription(user):
    """
    TGrass kanallarında abonelik kontrolü.
    subscribed=False olanları döndürür: [(id, link, name), ...]
    Eğer API cevabında subscribed alanı yoksa, MongoDB'deki listeyi kullanır.
    """
    if get_setting("tgrass", "on") != "on":
        return []
    not_sub = []
    offers = tgrass_get_offers(user)
    if offers:
        # API cevabı varsa ondan kontrol et
        for offer in offers:
            if offer.get("type") not in ("channel", None):
                continue
            if not offer.get("subscribed", True):
                name = offer.get("name") or offer.get("title") or "TGrass"
                link = offer.get("link") or offer.get("url") or ""
                if link:
                    not_sub.append((f"tg_{offer.get('offer_id', '')}", link, name))
    else:
        # API'den cevap gelmezse MongoDB'deki TGrass kanallarını get_chat_member ile kontrol et
        for ch_id, ch_link, ch_name, username in _ch_list(col_tgrass_channels):
            if not username:
                continue
            try:
                m = bot.get_chat_member("@" + username.lstrip("@"), user.id)
                if m.status in ("left", "kicked", "banned"):
                    not_sub.append((ch_id, ch_link, ch_name))
            except telebot.apihelper.ApiTelegramException as e:
                err = str(e).lower()
                # Bot hesabı veya bulunamayan kanal → atla
                if "bot" in err or "not found" in err or "chat not found" in err:
                    continue
                not_sub.append((ch_id, ch_link, ch_name))
            except Exception:
                not_sub.append((ch_id, ch_link, ch_name))
    return not_sub

# ╔══════════════════════════════════════════════════════════╗
#                   КЛАВИАТУРЫ
# ╚══════════════════════════════════════════════════════════╝
def build_main_keyboard(user_id=None, _tgrass_user=None):
    kb      = InlineKeyboardMarkup(row_width=2)
    sp_btns = [InlineKeyboardButton(text=f"🌟 {n}", url=l) for _, l, n, _ in get_sponsors()]
    al_btns = [InlineKeyboardButton(text=f"✨ {n}", url=l) for _, l, n, _ in get_addlist()]
    tg_btns = []
    if _tgrass_user and get_setting("tgrass","on") == "on":
        offers = tgrass_get_offers(_tgrass_user)
        for offer in offers:
            if not offer.get("subscribed", True):
                lnk = offer.get("link") or offer.get("url") or ""
                nm  = offer.get("name") or "TGrass"
                if lnk:
                    tg_btns.append(InlineKeyboardButton(text=f"⚙️ {nm}", url=lnk))
    all_btns = sp_btns + al_btns + tg_btns
    if all_btns:
        kb.add(*all_btns)
    kb.row(InlineKeyboardButton(text="✅ Agza boldum", callback_data="check_sub"))
    return kb

def build_unsub_keyboard(not_sub):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(*[InlineKeyboardButton(text=n, url=l) for _, l, n in not_sub])
    kb.row(InlineKeyboardButton(text="✅ Agza boldum", callback_data="check_sub"))
    return kb

def build_admin_keyboard():
    total, today, _ = db_get_stats()
    tgrass  = get_setting("tgrass", "on")
    tg_icon = "✅" if tgrass == "on" else "❌"
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(InlineKeyboardButton(
        text=f"🏁 Польз: {total} (сег. +{today})", callback_data="adm_stats"))
    kb.row(
        InlineKeyboardButton(text="📢 Рассылка",      callback_data="adm_broadcast"),
        InlineKeyboardButton(text="📡 Пост в каналы", callback_data="adm_send_channel"),
    )
    kb.row(
        InlineKeyboardButton(text="🔑 Изменить VPN",  callback_data="adm_code"),
        InlineKeyboardButton(text="🗑 Удалить рекл.", callback_data="adm_del_reklam"),
    )
    kb.row(
        InlineKeyboardButton(text="➕ Спонсор",       callback_data="adm_add_sponsor"),
        InlineKeyboardButton(text="🗑 Спонсор",       callback_data="adm_del_sponsor"),
    )
    kb.row(
        InlineKeyboardButton(text="➕ Addlist",       callback_data="adm_add_addlist"),
        InlineKeyboardButton(text="🗑 Addlist",       callback_data="adm_del_addlist"),
    )
    kb.row(
        InlineKeyboardButton(text=f"⚙️ TGrass {tg_icon}", callback_data="adm_tgrass"),
        InlineKeyboardButton(text="🔄 Обновить TGrass",    callback_data="adm_tgrass_update"),
    )
    kb.row(
        InlineKeyboardButton(text="👤 Добавить адм.",  callback_data="adm_add_admin"),
        InlineKeyboardButton(text="👤 Удалить адм.",   callback_data="adm_del_admin"),
    )
    kb.row(
        InlineKeyboardButton(text="📈 График",         callback_data="adm_growth"),
        InlineKeyboardButton(text="✏️ Приветствие",    callback_data="adm_welcome"),
    )
    return kb

def build_extra_admin_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton(text="📢 Рассылка",      callback_data="adm_broadcast"),
        InlineKeyboardButton(text="📡 Пост в каналы", callback_data="adm_send_channel"),
    )
    kb.row(
        InlineKeyboardButton(text="🗑 Удалить рекл.", callback_data="adm_del_reklam"),
        InlineKeyboardButton(text="🔑 Изменить VPN",  callback_data="adm_code"),
    )
    return kb

def _show_post_channels_menu(chat_id):
    channels = get_post_channels()
    kb = InlineKeyboardMarkup(row_width=2)
    for ch in channels:
        ch_id = str(ch["_id"])
        name  = ch.get("name","")
        uname = ch.get("username","")
        kb.row(
            InlineKeyboardButton(text=f"📺 {name} @{uname}", callback_data=f"pch_send_{ch_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"pch_del_{ch_id}"),
        )
    kb.row(
        InlineKeyboardButton(text="🚀 Отправить во все", callback_data="pch_send_all"),
        InlineKeyboardButton(text="➕ Добавить канал",   callback_data="pch_add"),
    )
    kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back"))
    bot.send_message(
        chat_id,
        f"📡 <b>Пост-каналы</b>\n\nКаналов: <b>{len(channels)}</b>\n\nВыберите канал:",
        reply_markup=kb
    )

# ╔══════════════════════════════════════════════════════════╗
#                       /start
# ╚══════════════════════════════════════════════════════════╝
@bot.message_handler(commands=["start"])
def cmd_start(message):
    u   = message.from_user
    arg = message.text.split(maxsplit=1)
    db_add_user(u.id, u.username or u.first_name or "")
    welcome = get_setting("welcome_text")
    bot.send_message(message.chat.id, welcome,
                     reply_markup=build_main_keyboard(user_id=u.id, _tgrass_user=u))

@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    uid = message.from_user.id
    if uid == ADMIN_ID:
        bot.send_message(message.chat.id, "⚙️ <b>Панель администратора</b>",
                         reply_markup=build_admin_keyboard())
    elif is_extra_admin(uid):
        bot.send_message(message.chat.id, "⚙️ <b>Панель администратора</b>",
                         reply_markup=build_extra_admin_kb())

# ╔══════════════════════════════════════════════════════════╗
#          АДМИН КОМАНДЫ (/add_sponsor, /add_addlist, etc.)
# ╚══════════════════════════════════════════════════════════╝
@bot.message_handler(commands=["add_sponsor"])
def cmd_add_sponsor(message):
    if message.from_user.id != ADMIN_ID: return
    name, link, username = parse_channel_args(message.text)
    if not name:
        bot.send_message(message.chat.id, "📌 <code>/add_sponsor 🌟НазваниеКанала @username</code>")
        return
    add_sponsor(link, name, username)
    bot.send_message(message.chat.id,
        f"✅ Спонсор добавлен!\n📢 <b>{name}</b> — <code>{username}</code>")

@bot.message_handler(commands=["add_addlist"])
def cmd_add_addlist(message):
    if message.from_user.id != ADMIN_ID: return
    name, link, username = parse_channel_args(message.text)
    if not name:
        bot.send_message(message.chat.id, "📌 <code>/add_addlist ✨НазваниеКанала @username</code>")
        return
    add_addlist(link, name, username)
    bot.send_message(message.chat.id,
        f"✅ Addlist добавлен!\n📋 <b>{name}</b> — <code>{username}</code>")

@bot.message_handler(commands=["tgrass_on"])
def cmd_tgrass_on(message):
    if message.from_user.id != ADMIN_ID: return
    set_setting("tgrass", "on")
    bot.send_message(message.chat.id, "✅ <b>TGrass включён!</b>")

@bot.message_handler(commands=["tgrass_off"])
def cmd_tgrass_off(message):
    if message.from_user.id != ADMIN_ID: return
    set_setting("tgrass", "off")
    bot.send_message(message.chat.id, "❌ <b>TGrass выключен!</b>")

@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    if message.from_user.id != ADMIN_ID: return
    clear_state(message.from_user.id)
    bot.send_message(message.chat.id, "↩️ Отменено.", reply_markup=build_admin_keyboard())

# ╔══════════════════════════════════════════════════════════╗
#              CALLBACK — ПОЛЬЗОВАТЕЛИ
# ╚══════════════════════════════════════════════════════════╝
@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def cb_check_sub(call):
    user = call.from_user
    all_ch = list(get_sponsors()) + list(get_addlist())
    tgrass = get_setting("tgrass", "on")
    tg_user = get_setting("tgrass_username", "")
    if tgrass == "on" and tg_user:
        all_ch.append(("tg", f"https://t.me/{tg_user}", "⚙️ TGrass", tg_user))

    if not all_ch:
        bot.answer_callback_query(call.id, "⚠️ Каналов ещё нет!", show_alert=True)
        return

    not_sub = check_subs(user.id)
    # TGrass kanallarını da kontrol et
    not_sub += check_tgrass_subscription(user)

    if not_sub:
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, call.message.message_id,
                reply_markup=build_unsub_keyboard(not_sub)
            )
        except Exception:
            pass
        bot.answer_callback_query(
            call.id, "❌ Вы ещё не подписались на все каналы!", show_alert=True)
        return


    # Отправить VPN-код
    vpn = get_setting("vpn_code")
    bot.send_message(
        call.message.chat.id,
        f"✅ <b>Подписка подтверждена!</b>\n\n"
        f"🔑 Ваш VPN-код:\n\n<code>{vpn}</code>"
    )
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "back_main")
def cb_back_main(call):
    welcome = get_setting("welcome_text") or "👋 <b>Добро пожаловать!</b>"
    bot.send_message(call.message.chat.id, welcome,
                     reply_markup=build_main_keyboard(_tgrass_user=call.from_user))
    bot.answer_callback_query(call.id)

# ╔══════════════════════════════════════════════════════════╗
#              CALLBACK — АДМИНИСТРАТОР
# ╚══════════════════════════════════════════════════════════╝
EXTRA_ADMIN_ALLOWED = {"adm_broadcast", "adm_send_channel", "adm_del_reklam", "adm_code", "pch_send_all"}

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_") and
    (c.from_user.id == ADMIN_ID or is_extra_admin(c.from_user.id)))
def admin_callbacks(call):
    data = call.data
    # Extra admin yetki kontrolu
    if call.from_user.id != ADMIN_ID and data not in EXTRA_ADMIN_ALLOWED:
        bot.answer_callback_query(call.id, "❌ Yetkiniz yok!", show_alert=True)
        return

    # ── Статистика ──────────────────────────────────────────────────────────────
    if data == "adm_stats":
        total, today, week = db_get_stats()
        sp_count  = col_sponsors.count_documents({})
        al_count  = col_addlist.count_documents({})
        tgrass    = get_setting("tgrass", "on")
        tg_status = "Aç" if tgrass == "on" else "Öçür"
        adm_count = col_settings.count_documents({"key": {"$regex": "^admin_"}})
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back"))
        bot.send_message(
            call.message.chat.id,
            f"📊 <b>Statistika:</b>\n\n"
            f"👥 Ulanyjylar: <b>{total}</b>\n"
            f"📢 Kanallar: <b>{sp_count}</b>\n"
            f"🔗 Addlistler: <b>{al_count}</b>\n"
            f"⚙️ TGRASS: <b>{tg_status}</b>",
            reply_markup=kb
        )
        bot.answer_callback_query(call.id)

    # ── Добавить спонсора ──────────────────────────────────────────────────────
    elif data == "adm_add_sponsor":
        set_state(call.from_user.id, "adm_add_sponsor")
        bot.send_message(call.message.chat.id,
            "📢 Введите данные спонсора в формате:\n"
            "<code>🌟НазваниеКанала @username</code>\n\n"
            "Или: /cancel")
        bot.answer_callback_query(call.id)

    # ── Удалить спонсора ──────────────────────────────────────────────────────
    elif data == "adm_del_sponsor":
        sponsors = get_sponsors()
        if not sponsors:
            bot.answer_callback_query(call.id, "Спонсоров нет!", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for sid, _, name, uname in sponsors:
            kb.add(InlineKeyboardButton(
                text=f"🗑 {name} (@{uname})",
                callback_data=f"delspon_{sid}"
            ))
        kb.add(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back"))
        bot.send_message(call.message.chat.id, "Выберите спонсора для удаления:",
                         reply_markup=kb)
        bot.answer_callback_query(call.id)

    # ── Добавить addlist ──────────────────────────────────────────────────────
    elif data == "adm_add_addlist":
        set_state(call.from_user.id, "adm_add_addlist")
        bot.send_message(call.message.chat.id,
            "📋 Введите данные addlist в формате:\n"
            "<code>✨НазваниеКанала @username</code>\n\n"
            "Или: /cancel")
        bot.answer_callback_query(call.id)

    # ── Удалить addlist ───────────────────────────────────────────────────────
    elif data == "adm_del_addlist":
        addlist = get_addlist()
        if not addlist:
            bot.answer_callback_query(call.id, "Addlist пуст!", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for aid, _, name, uname in addlist:
            kb.add(InlineKeyboardButton(
                text=f"🗑 {name} (@{uname})",
                callback_data=f"deladdl_{aid}"
            ))
        kb.add(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back"))
        bot.send_message(call.message.chat.id, "Выберите для удаления:",
                         reply_markup=kb)
        bot.answer_callback_query(call.id)

    # ── Изменить VPN код ──────────────────────────────────────────────────────
    elif data == "adm_code":
        cur = get_setting("vpn_code")
        set_state(call.from_user.id, "adm_code")
        bot.send_message(call.message.chat.id,
            f"🔑 Текущий VPN-код:\n<code>{cur}</code>\n\n"
            f"Введите новый код:")
        bot.answer_callback_query(call.id)

    # ── Рассылка ─────────────────────────────────────────────────────────────
    elif data == "adm_broadcast":
        set_state(call.from_user.id, "adm_broadcast")
        bot.send_message(call.message.chat.id,
            "📢 Отправьте сообщение для рассылки всем пользователям.\n"
            "(Текст, фото, видео — любой тип)\n\n"
            "Отмена: /cancel")
        bot.answer_callback_query(call.id)

    # ── В каналы ─────────────────────────────────────────────────────────────
    elif data == "adm_send_channel":
        _show_post_channels_menu(call.message.chat.id)
        bot.answer_callback_query(call.id)

    # ── Удалить рекламу ──────────────────────────────────────────────────────
    elif data == "adm_del_reklam":
        reklamlar = get_reklamlar()
        if not reklamlar:
            bot.answer_callback_query(call.id, "Нет сохранённой рекламы!", show_alert=True)
            return
        ok = fail = 0
        for chat_id, msg_id in reklamlar:
            try:
                bot.delete_message(chat_id=chat_id, message_id=msg_id)
                ok += 1
            except Exception:
                fail += 1
        clear_reklamlar()
        bot.send_message(call.message.chat.id,
            f"🗑 <b>Реклама удалена!</b>\n\n"
            f"✔️ Удалено: <b>{ok}</b>\n"
            f"❌ Не найдено: <b>{fail}</b>",
            reply_markup=build_admin_keyboard())
        bot.answer_callback_query(call.id)

    # ── TGrass переключатель ─────────────────────────────────────────────────
    elif data == "adm_tgrass":
        tgrass = get_setting("tgrass", "on")
        if tgrass == "on":
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton(text="❌ Выключить TGrass", callback_data="tgrass_off_confirm"),
                InlineKeyboardButton(text="📝 Изменить канал",   callback_data="tgrass_set_ch"),
                InlineKeyboardButton(text="🔙 Назад",            callback_data="adm_back"),
            )
            tg_user = get_setting("tgrass_username", "—")
            bot.send_message(call.message.chat.id,
                f"⚙️ <b>TGrass</b>\n\n"
                f"Статус: ✅ Включен\n"
                f"Канал: @{tg_user}",
                reply_markup=kb)
        else:
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton(text="✅ Включить TGrass",  callback_data="tgrass_on_confirm"),
                InlineKeyboardButton(text="📝 Изменить канал",   callback_data="tgrass_set_ch"),
                InlineKeyboardButton(text="🔙 Назад",            callback_data="adm_back"),
            )
            bot.send_message(call.message.chat.id,
                "⚙️ <b>TGrass</b>\n\nСтатус: ❌ Выключен",
                reply_markup=kb)
        bot.answer_callback_query(call.id)

    # ── График роста ─────────────────────────────────────────────────────────
    elif data == "adm_growth":
        rows  = db_get_growth()
        max_v = max((c for _, c in rows), default=1) or 1
        lines = []
        for label, count in rows:
            bar = "█" * int((count / max_v) * 12) + "░" * (12 - int((count / max_v) * 12))
            lines.append(f"<code>{label}</code> {bar} <b>{count}</b>")
        total, today, week = db_get_stats()
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back"))
        bot.send_message(
            call.message.chat.id,
            f"📈 <b>Рост за 7 дней</b>\n\n" + "\n".join(lines) +
            f"\n\n👥 Всего: <b>{total}</b> | За неделю: <b>+{week}</b> | Сегодня: <b>+{today}</b>",
            reply_markup=kb
        )
        bot.answer_callback_query(call.id)

    # ── Изменить приветствие ─────────────────────────────────────────────────
    elif data == "adm_welcome":
        cur = get_setting("welcome_text")
        set_state(call.from_user.id, "adm_welcome")
        bot.send_message(call.message.chat.id,
            f"✏️ Текущее приветствие:\n\n{cur}\n\nВведите новый текст:")
        bot.answer_callback_query(call.id)

    # ── TGrass Güncelle ──────────────────────────────────────────────────────
    elif data == "adm_tgrass_update":
        bot.answer_callback_query(call.id, "🔄 TGrass täzelendi...")
        count, msg = tgrass_fetch_channels()
        if msg == "ok":
            text = (f"✅ <b>Kanallar TGrass'tan alyndy!</b>\n\n"
                    f"📡 Kanal sayısı: <b>{count}</b>")
        else:
            text = (f"❌ <b>TGrass bağlantı hatası!</b>\n\n"
                    f"Hata: <code>{msg}</code>")
        bot.send_message(call.message.chat.id, text, reply_markup=build_admin_keyboard())

    # ── Добавить/удалить администратора ──────────────────────────────────────
    elif data == "adm_add_admin":
        set_state(call.from_user.id, "adm_add_admin")
        bot.send_message(call.message.chat.id,
            "👤 Admin edilecek adamyň ID'ini ýazyň:\n\n"
            "⚠️ Bu admin şulary edip biler:\n"
            "• 📢 Body ulanyanlara habar ibermek\n"
            "• 📡 Kanallara post ibermek\n"
            "• 🗑 Reklamany pozmak\n"
            "• 🔑 VPN koduny çalşmak\n\nОтмена: /cancel")
        bot.answer_callback_query(call.id)

    elif data == "adm_del_admin":
        # Extra admin listesini goster
        extra_admins = list(col_settings.find({"key": {"$regex": "^extra_admin_"}}))
        if not extra_admins:
            bot.answer_callback_query(call.id, "Ek admin yok!", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for adm in extra_admins:
            adm_id = adm["key"].replace("extra_admin_", "")
            adm_name = adm.get("value", adm_id)
            kb.add(InlineKeyboardButton(
                text=f"🗑 {adm_name} (ID: {adm_id})",
                callback_data=f"del_extra_admin_{adm_id}"
            ))
        kb.add(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back"))
        bot.send_message(call.message.chat.id, "Silinecek admini seçin:", reply_markup=kb)
        bot.answer_callback_query(call.id)

    # ── Назад ─────────────────────────────────────────────────────────────────
    elif data == "adm_back":
        bot.send_message(
            call.message.chat.id,
            "⚙️ <b>Панель администратора</b>",
            reply_markup=build_admin_keyboard()
        )
        bot.answer_callback_query(call.id)

# ── Пост-каналы: добавить / удалить / отправить ───────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("pch_") and
    (c.from_user.id == ADMIN_ID or is_extra_admin(c.from_user.id)))
def cb_post_channels(call):
    uid  = call.from_user.id
    data = call.data

    # ── Добавить канал ────────────────────────────────────────────────────────
    if data == "pch_add":
        set_state(uid, "pch_add")
        bot.send_message(call.message.chat.id,
            "➕ <b>Добавить пост-канал</b>\n\n"
            "Введите в формате:\n"
            "<code>Название @username</code>\n\n"
            "Например: <code>HAPP_VPN @HAPP_VPN</code>\n\nОтмена: /cancel")
        bot.answer_callback_query(call.id)

    # ── Удалить канал ─────────────────────────────────────────────────────────
    elif data.startswith("pch_del_"):
        ch_id = data[len("pch_del_"):]
        del_post_channel(ch_id)
        bot.answer_callback_query(call.id, "✅ Канал удалён!")
        _show_post_channels_menu(call.message.chat.id)

    # ── Отправить во все ──────────────────────────────────────────────────────
    elif data == "pch_send_all":
        channels = get_post_channels()
        if not channels:
            bot.answer_callback_query(call.id, "Список пуст! Сначала добавьте каналы.", show_alert=True)
            return
        names = ", ".join(f"@{c['username']}" for c in channels)
        set_state(uid, "pch_send_post", target="all")
        bot.send_message(call.message.chat.id,
            f"🚀 <b>Отправить во все каналы</b>\n\n"
            f"Каналов: <b>{len(channels)}</b>\n{names}\n\n"
            f"Отправьте рекламный пост (текст, фото, видео — любой тип)\n\nОтмена: /cancel")
        bot.answer_callback_query(call.id)

    # ── Отправить в один канал ────────────────────────────────────────────────
    elif data.startswith("pch_send_"):
        ch_id = data[len("pch_send_"):]
        ch    = col_post_channels.find_one({"_id": ObjectId(ch_id)})
        if not ch:
            bot.answer_callback_query(call.id, "Канал не найден!", show_alert=True)
            return
        set_state(uid, "pch_send_post", target=ch_id)
        bot.send_message(call.message.chat.id,
            f"📺 <b>@{ch['username']}</b> каналына пост отправьте:\n\n"
            f"(Текст, фото, видео, кнопки — любой тип)\n\n"
            "Отмена: /cancel")
        bot.answer_callback_query(call.id)

# ── Extra admin сил ──────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("del_extra_admin_") and c.from_user.id == ADMIN_ID)
def cb_del_extra_admin(call):
    adm_id = call.data[len("del_extra_admin_"):]
    col_settings.delete_one({"key": f"extra_admin_{adm_id}"})
    bot.send_message(call.message.chat.id,
        f"✅ Admin <code>{adm_id}</code> silindi!",
        reply_markup=build_admin_keyboard())
    bot.answer_callback_query(call.id)

# ── TGrass on/off confirm ─────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data in ("tgrass_on_confirm", "tgrass_off_confirm",
                                                        "tgrass_set_ch") and c.from_user.id == ADMIN_ID)
def tgrass_actions(call):
    if call.data == "tgrass_on_confirm":
        set_setting("tgrass", "on")
        bot.answer_callback_query(call.id, "✅ TGrass включён!")
        bot.send_message(call.message.chat.id, "✅ TGrass включён!",
                         reply_markup=build_admin_keyboard())
    elif call.data == "tgrass_off_confirm":
        set_setting("tgrass", "off")
        bot.answer_callback_query(call.id, "❌ TGrass выключен!")
        bot.send_message(call.message.chat.id, "❌ TGrass выключен!",
                         reply_markup=build_admin_keyboard())
    elif call.data == "tgrass_set_ch":
        set_state(call.from_user.id, "tgrass_set_ch")
        bot.send_message(call.message.chat.id,
            "⚙️ Введите @username канала TGrass:")
        bot.answer_callback_query(call.id)

# ── Удалить спонсора/addlist ──────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("delspon_") and c.from_user.id == ADMIN_ID)
def cb_del_sponsor(call):
    doc_id = call.data[len("delspon_"):]
    del_sponsor(doc_id)
    bot.send_message(call.message.chat.id, "✅ Спонсор удалён!",
                     reply_markup=build_admin_keyboard())
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("deladdl_") and c.from_user.id == ADMIN_ID)
def cb_del_addlist(call):
    doc_id = call.data[len("deladdl_"):]
    del_addlist(doc_id)
    bot.send_message(call.message.chat.id, "✅ Addlist удалён!",
                     reply_markup=build_admin_keyboard())
    bot.answer_callback_query(call.id)

# ── Отправка в каналы ─────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("sendch_") and (c.from_user.id == ADMIN_ID or is_extra_admin(c.from_user.id)))
def cb_sendch(call):
    target = call.data[len("sendch_"):]
    all_ch = list(get_sponsors()) + list(get_addlist())

    if target == "all":
        set_state(call.from_user.id, "adm_sendch_post", target="all")
        names = ", ".join(name for _, _, name, _ in all_ch)
        bot.send_message(call.message.chat.id,
            f"🚀 <b>Во все каналы</b>\n\nКаналы: <b>{names}</b>\n\n"
            f"Отправьте рекламный пост (текст, фото, видео — любой тип)\n\nОтмена: /cancel")
    else:
        found = [(cid, cl, nm, un) for cid, cl, nm, un in all_ch if cid == target]
        if not found:
            bot.answer_callback_query(call.id, "Канал не найден!", show_alert=True)
            return
        set_state(call.from_user.id, "adm_sendch_post", target=target)
        bot.send_message(call.message.chat.id,
            f"📺 Отправьте пост для канала <b>{found[0][2]}</b>\n\nОтмена: /cancel")
    bot.answer_callback_query(call.id)

# ╔══════════════════════════════════════════════════════════╗
#                   FSM — ОБРАБОТЧИК СООБЩЕНИЙ
# ╚══════════════════════════════════════════════════════════╝
@bot.message_handler(
    func=lambda m: get_state(m.from_user.id) is not None,
    content_types=["text","photo","video","document","audio","animation","sticker"]
)
def fsm_handler(message):
    uid   = message.from_user.id
    state = get_state(uid)

    # Только для администратора — дальше
    if uid != ADMIN_ID and not is_extra_admin(uid):
        clear_state(uid)
        return
    # Extra admin sadece bu işlemleri yapabilir
    if is_extra_admin(uid) and uid != ADMIN_ID:
        allowed = {"adm_broadcast", "adm_sendch_post", "adm_code", "pch_add", "pch_send_post"}
        if state not in allowed:
            clear_state(uid)
            return

    # ── Добавить спонсора ─────────────────────────────────────────────────────
    if state == "adm_add_sponsor":
        txt = "/x " + (message.text or "")
        name, link, username = parse_channel_args(txt)
        if not name:
            bot.send_message(message.chat.id,
                "❌ Неверный формат!\nПример: <code>🌟НазваниеКанала @username</code>")
            return
        add_sponsor(link, name, username)
        clear_state(uid)
        bot.send_message(message.chat.id,
            f"✅ Спонсор добавлен!\n📢 <b>{name}</b> — <code>{username}</code>",
            reply_markup=build_admin_keyboard())

    # ── Добавить addlist ──────────────────────────────────────────────────────
    elif state == "adm_add_addlist":
        txt = "/x " + (message.text or "")
        name, link, username = parse_channel_args(txt)
        if not name:
            bot.send_message(message.chat.id,
                "❌ Неверный формат!\nПример: <code>✨НазваниеКанала @username</code>")
            return
        add_addlist(link, name, username)
        clear_state(uid)
        bot.send_message(message.chat.id,
            f"✅ Addlist добавлен!\n📋 <b>{name}</b> — <code>{username}</code>",
            reply_markup=build_admin_keyboard())

    # ── Изменить VPN код ──────────────────────────────────────────────────────
    elif state == "adm_code":
        new_vpn = (message.text or "").strip()
        if not new_vpn:
            bot.send_message(message.chat.id, "❌ Код boş olamaz!")
            return
        set_setting("vpn_code", new_vpn)
        clear_state(uid)
        kb = build_extra_admin_kb() if is_extra_admin(uid) and uid != ADMIN_ID else build_admin_keyboard()
        bot.send_message(
            message.chat.id,
            f"✅ <b>VPN-код обновлён!</b>\n\n🔑 Täze kod:\n<code>{new_vpn}</code>",
            reply_markup=kb
        )

    # ── Рассылка ─────────────────────────────────────────────────────────────
    elif state == "adm_broadcast":
        users = db_get_all_users()
        total = len(users)
        ok = fail = 0
        prog = bot.send_message(message.chat.id, f"📢 Рассылка...\n0 / {total}")
        for i, uid2 in enumerate(users, 1):
            try:
                bot.copy_message(uid2, message.chat.id, message.message_id,
                                 reply_markup=message.reply_markup)
                ok += 1
            except Exception:
                fail += 1
            if i % 25 == 0 or i == total:
                try:
                    bot.edit_message_text(
                        f"📢 Рассылка...\n{i} / {total}",
                        message.chat.id, prog.message_id)
                except Exception:
                    pass
            time.sleep(0.05)
        clear_state(uid)
        bot.edit_message_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"✔️ Доставлено: <b>{ok}</b>\n"
            f"❌ Ошибок: <b>{fail}</b>\n"
            f"👥 Всего: <b>{total}</b>",
            message.chat.id, prog.message_id, parse_mode="HTML"
        )
        bot.send_message(message.chat.id, "Панель:", reply_markup=build_admin_keyboard())

    # ── Пост-каналы: добавить ────────────────────────────────────────────────
    elif state == "pch_add":
        parts = (message.text or "").strip().split(maxsplit=1)
        if len(parts) < 2:
            bot.send_message(message.chat.id,
                "❌ Формат: <code>Название @username</code>\n\nПример: <code>HAPP_VPN @HAPP_VPN</code>")
            return
        name  = parts[0].strip()
        uname = parts[1].strip().lstrip("@")
        add_post_channel(name, uname)
        clear_state(uid)
        bot.send_message(message.chat.id,
            f"✅ Канал <b>{name}</b> (@{uname}) добавлен!")
        _show_post_channels_menu(message.chat.id)

    # ── Пост-каналы: отправить ────────────────────────────────────────────────
    elif state == "pch_send_post":
        d      = user_data.get(uid, {})
        target = d.get("target", "all")

        if target == "all":
            channels = get_post_channels()
        else:
            ch = col_post_channels.find_one({"_id": ObjectId(target)})
            channels = [ch] if ch else []

        if not channels:
            clear_state(uid)
            bot.send_message(message.chat.id, "❌ Каналов нет.",
                             reply_markup=build_admin_keyboard())
            return

        markup    = message.reply_markup
        ok        = 0
        fail      = 0
        fail_list = []

        prog = bot.send_message(
            message.chat.id,
            f"📡 Отправка...\n0 / {len(channels)}"
        )

        for i, ch in enumerate(channels, 1):
            tgt = "@" + ch.get("username", "").lstrip("@")
            if not tgt or tgt == "@":
                fail += 1
                fail_list.append(f"{ch.get('name','?')}: адрес отсутствует")
                continue
            try:
                sent = bot.copy_message(
                    tgt,
                    message.chat.id,
                    message.message_id,
                    reply_markup=markup
                )
                save_reklam(tgt, sent.message_id)
                ok += 1
            except telebot.apihelper.ApiTelegramException as e:
                fail += 1
                fail_list.append(f"{ch.get('name','?')} ({tgt}): {str(e)[:60]}")
            except Exception as e:
                fail += 1
                fail_list.append(f"{ch.get('name','?')} ({tgt}): {str(e)[:60]}")

            if i % 5 == 0 or i == len(channels):
                try:
                    bot.edit_message_text(
                        f"📡 Отправка...\n{i} / {len(channels)}",
                        message.chat.id, prog.message_id)
                except Exception:
                    pass
            time.sleep(0.3)

        fail_txt = ("\n\n❌ Ошибки:\n" + "\n".join(f"• {f}" for f in fail_list)) if fail_list else ""
        clear_state(uid)
        bot.edit_message_text(
            f"✅ <b>Отправка завершена!</b>\n\n"
            f"📡 Каналов: <b>{len(channels)}</b>\n"
            f"✔️ Успешно: <b>{ok}</b>\n"
            f"❌ Ошибок: <b>{fail}</b>{fail_txt}",
            message.chat.id, prog.message_id, parse_mode="HTML"
        )
        kb = build_extra_admin_kb() if is_extra_admin(uid) and uid != ADMIN_ID else build_admin_keyboard()
        bot.send_message(message.chat.id, "Панель:", reply_markup=kb)

    # ── Отправка в каналы (старая система) ───────────────────────────────────
    elif state == "adm_sendch_post":
        d      = user_data.get(uid, {})
        target = d.get("target", "all")
        all_ch = list(get_sponsors()) + list(get_addlist())
        send_list = all_ch if target == "all" else [c for c in all_ch if c[0] == target]
        if not send_list:
            clear_state(uid)
            bot.send_message(message.chat.id, "❌ Каналов нет.",
                             reply_markup=build_admin_keyboard())
            return
        markup = message.reply_markup
        ok = fail = 0
        fail_list = []
        prog = bot.send_message(message.chat.id,
                                f"📡 Отправка...\n0 / {len(send_list)}")
        for i, (ch_id, ch_link, name, uname) in enumerate(send_list, 1):
            tgt = "@" + uname.lstrip("@")
            try:
                sent = bot.copy_message(tgt, message.chat.id, message.message_id,
                                        reply_markup=markup)
                save_reklam(tgt, sent.message_id)
                ok += 1
            except Exception as e:
                fail += 1
                fail_list.append(f"{name}: {str(e)[:40]}")
            if i % 5 == 0 or i == len(send_list):
                try:
                    bot.edit_message_text(
                        f"📡 Отправка...\n{i} / {len(send_list)}",
                        message.chat.id, prog.message_id)
                except Exception:
                    pass
            time.sleep(0.3)
        fail_txt = ("\n\n❌ Ошибки:\n" + "\n".join(f"• {f}" for f in fail_list)) if fail_list else ""
        clear_state(uid)
        bot.edit_message_text(
            f"✅ <b>Отправка завершена!</b>\n\n"
            f"📡 Каналов: <b>{len(send_list)}</b>\n"
            f"✔️ Успешно: <b>{ok}</b>\n"
            f"❌ Ошибок: <b>{fail}</b>{fail_txt}",
            message.chat.id, prog.message_id, parse_mode="HTML"
        )
        bot.send_message(message.chat.id, "Панель:", reply_markup=build_admin_keyboard())

    # ── Admin ekleme ─────────────────────────────────────────────────────────
    elif state == "adm_add_admin":
        try:
            new_adm_id = int((message.text or "").strip())
        except ValueError:
            bot.send_message(message.chat.id, "❌ Ýalňyş ID!"); return
        # Extra admin kaydet (sadece broadcast + kanal post + reklam silme)
        try:
            adm_user = bot.get_chat(new_adm_id)
            adm_name = f"@{adm_user.username}" if adm_user.username else str(new_adm_id)
        except Exception:
            adm_name = str(new_adm_id)
        col_settings.update_one(
            {"key": f"extra_admin_{new_adm_id}"},
            {"$set": {"key": f"extra_admin_{new_adm_id}", "value": adm_name}},
            upsert=True
        )
        clear_state(uid)
        bot.send_message(message.chat.id,
            f"✅ <b>{adm_name}</b> admin yapıldı!\n\n"
            f"Yetkileri: Рассылка, Пост в каналы, Удалить рекламу",
            reply_markup=build_admin_keyboard())
        try:
            bot.send_message(new_adm_id, "🎉 Boda admin edildiňiz!\n/admin ýazyp bilersiňiz.")
        except Exception:
            pass

    # ── TGrass канал ─────────────────────────────────────────────────────────
    elif state == "tgrass_set_ch":
        uname = (message.text or "").strip().lstrip("@")
        set_setting("tgrass_username", uname)
        clear_state(uid)
        bot.send_message(message.chat.id,
            f"✅ TGrass канал установлен: @{uname}",
            reply_markup=build_admin_keyboard())

    # ── Изменить приветствие ──────────────────────────────────────────────────
    elif state == "adm_welcome":
        set_setting("welcome_text", (message.text or "").strip())
        clear_state(uid)
        bot.send_message(message.chat.id, "✅ Приветствие обновлено!",
                         reply_markup=build_admin_keyboard())

# ╔══════════════════════════════════════════════════════════╗
#                   FLASK + SELF-PING
# ╚══════════════════════════════════════════════════════════╝
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    total = col_users.count_documents({})
    return f"✅ Bot is Alive! | Users: {total}", 200

@flask_app.route("/health")
def health():
    return "OK", 200

def self_ping():
    while True:
        try:
            r = requests.get(RENDER_URL, timeout=10)
            print(f"[Ping] {r.status_code}")
        except Exception as e:
            print(f"[Ping] Error: {e}")
        time.sleep(300)

def run_bot():
    print("🤖 ShadowVip Bot запущен (MongoDB + Flask)...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"[Polling] {e}")
            time.sleep(5)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# ╔══════════════════════════════════════════════════════════╗
#                        ЗАПУСК
# ╚══════════════════════════════════════════════════════════╝
if __name__ == "__main__":
    threading.Thread(target=self_ping, daemon=True).start()
    threading.Thread(target=run_bot,   daemon=True).start()
    run_flask()
