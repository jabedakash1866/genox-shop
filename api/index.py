import os
import re
import secrets
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN1_CHAT_ID", "")
PLAYER_API_URL = os.environ.get("PLAYER_API_URL", "")
PLAYER_API_REGION = os.environ.get("PLAYER_API_REGION", "BD")
GUILD_API = os.environ.get("GUILD_API", "")

LIKES = {
    "200": {7: (1400, 55), 15: (3000, 90), 30: (6000, 150), 60: (12000, 300), 90: (18000, 450)},
    "400": {7: (2800, 150), 15: (6000, 240), 30: (12000, 400), 60: (24000, 800), 90: (36000, 1200)},
    "1000": {7: (7000, 300), 15: (15000, 550), 30: (30000, 1000), 60: (60000, 2000), 90: (90000, 3000)},
}
TCP = {7: 130, 15: 275, 30: 550, 60: 1100}
GLORY = {4: 120, 8: 240, 12: 360, 16: 480}

CATALOG = {}
for cat, rows in LIKES.items():
    for days, (total, price) in rows.items():
        CATALOG["l%s_%d" % (cat, days)] = {
            "service": "likes", "category": cat,
            "label": "%s Likes - %02d Days" % (cat, days),
            "days": days, "quantity": total, "price": price}
for days, price in TCP.items():
    CATALOG["tcp_%d" % days] = {
        "service": "tcp", "category": None,
        "label": "TCP Bot - %02d Days" % days,
        "days": days, "quantity": None, "price": price}
for bots, price in GLORY.items():
    CATALOG["glory_%d" % bots] = {
        "service": "glory", "category": None,
        "label": "%d BOT" % bots,
        "days": None, "quantity": bots, "price": price}

PAY_METHODS = ("nagad", "bkash", "rocket")
SVC_NAME = {"likes": "Free Fire Likes", "tcp": "TCP Bot", "glory": "Guild Glory Bot"}


def both(path, **kw):
    def deco(f):
        app.add_url_rule("/api" + path, f.__name__ + "_a", f, **kw)
        app.add_url_rule(path, f.__name__ + "_b", f, **kw)
        return f
    return deco


def err(msg, code=400):
    return jsonify(ok=False, error=msg), code


def sb_headers():
    h = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if SUPABASE_KEY.startswith("eyJ"):
        h["Authorization"] = "Bearer " + SUPABASE_KEY
    return h


def get_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    try:
        r = requests.get(
            SUPABASE_URL + "/auth/v1/user",
            headers={"apikey": SUPABASE_KEY, "Authorization": "Bearer " + token},
            timeout=10)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    u = r.json()
    return u if u.get("id") else None


def notify_admin(text):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return False
    try:
        r = requests.post(
            "https://api.telegram.org/bot%s/sendMessage" % BOT_TOKEN,
            json={"chat_id": ADMIN_CHAT_ID, "text": text}, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


@both("/orders", methods=["POST"])
def create_order():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return err("সার্ভার সেটআপ অসম্পূর্ণ", 503)
    user = get_user()
    if not user:
        return err("লগইন প্রয়োজন", 401)

    d = request.get_json(silent=True) or {}
    pkg = CATALOG.get(str(d.get("package_id", "")))
    if not pkg or pkg["service"] != d.get("service"):
        return err("প্যাকেজ সঠিক নয়")

    name = str(d.get("name", "")).strip()[:80]
    phone = str(d.get("phone", "")).strip()
    uid = str(d.get("uid", "")).strip()
    pay = str(d.get("payment_method", "")).strip()
    txn = str(d.get("transaction_id", "")).strip()

    if len(name) < 2:
        return err("নাম লিখুন")
    if not re.fullmatch(r"\+?\d{8,15}", phone):
        return err("সঠিক ফোন নম্বর লিখুন")
    if not re.fullmatch(r"\d{6,14}", uid):
        return err("সঠিক UID লিখুন")
    if pay not in PAY_METHODS:
        return err("পেমেন্ট মেথড সঠিক নয়")
    if not re.fullmatch(r"[A-Za-z0-9]{6,40}", txn):
        return err("Transaction ID সঠিক নয়")

    customer = {"name": name, "phone": phone, "uid": uid, "email": user.get("email") or ""}
    if pkg["service"] == "tcp":
        fr = d.get("friend_uids") or []
        if not isinstance(fr, list) or len(fr) > 4:
            return err("Friend UID সঠিক নয়")
        fr = [str(x).strip() for x in fr if str(x).strip()]
        if any(not re.fullmatch(r"\d{6,14}", x) for x in fr):
            return err("Friend UID সঠিক নয়")
        customer["friend_uids"] = fr

    try:
        dup = requests.get(
            SUPABASE_URL + "/rest/v1/orders",
            headers=sb_headers(),
            params={"transaction_id": "eq." + txn, "select": "id", "limit": "1"},
            timeout=10)
        if dup.status_code == 200 and dup.json():
            return err("এই Transaction ID আগে ব্যবহার হয়েছে")
    except requests.RequestException:
        return err("ডাটাবেসে সংযোগ হয়নি", 502)

    bd = timezone(timedelta(hours=6))
    now = datetime.now(bd)
    code = "GX%s%s" % (now.strftime("%y%m%d"), secrets.token_hex(2).upper())

    row = {
        "user_id": user["id"], "order_code": code, "status": "pending",
        "service": pkg["service"], "category": pkg["category"],
        "package_label": pkg["label"], "duration_days": pkg["days"],
        "quantity": pkg["quantity"], "price": pkg["price"],
        "payment_method": pay, "transaction_id": txn, "customer_data": customer,
    }
    try:
        h = sb_headers()
        h["Prefer"] = "return=representation"
        r = requests.post(SUPABASE_URL + "/rest/v1/orders", headers=h, json=row, timeout=10)
    except requests.RequestException:
        return err("অর্ডার সেভ করা যায়নি", 502)
    if r.status_code not in (200, 201):
        return err("অর্ডার সেভ করা যায়নি", 500)
    saved = r.json()[0]

    qty = ""
    if pkg["quantity"] is not None:
        qty = ("Total Likes: %d" if pkg["service"] == "likes" else "BOT: %d") % pkg["quantity"]
    lines = [
        "🛒 নতুন অর্ডার",
        "Order ID: " + code,
        "Service: " + SVC_NAME[pkg["service"]],
        "Package: " + pkg["label"],
    ]
    if pkg["days"]:
        lines.append("Duration: %02d Days" % pkg["days"])
    if qty:
        lines.append(qty)
    lines += [
        "Price: ৳%d" % pkg["price"],
        "Customer: " + name,
        "Email: " + (user.get("email") or "-"),
        "Phone: " + phone,
        "UID: " + uid,
    ]
    if customer.get("friend_uids"):
        lines.append("Friend UID: " + ", ".join(customer["friend_uids"]))
    lines += [
        "Payment: " + pay,
        "Transaction ID: " + txn,
        "Time: " + now.strftime("%d-%m-%Y %I:%M %p"),
    ]
    notify_admin("\n".join(lines))

    return jsonify(ok=True, order={"order_code": code, "created_at": saved.get("created_at")})


def fetch_json(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=15)
    except requests.RequestException:
        return None, "সার্ভারে সংযোগ হয়নি"
    if r.status_code != 200:
        return None, "তথ্য পাওয়া যায়নি"
    try:
        j = r.json()
    except ValueError:
        return None, "সার্ভার থেকে সঠিক উত্তর আসেনি"
    if not j or (isinstance(j, dict) and j.get("error")):
        return None, "তথ্য পাওয়া যায়নি"
    return j, None


@both("/player")
def player():
    uid = request.args.get("uid", "").strip()
    if not re.fullmatch(r"\d{4,14}", uid):
        return err("সঠিক UID লিখুন")
    if not PLAYER_API_URL:
        return err("Player API সেট করা নেই", 503)
    data, e = fetch_json(PLAYER_API_URL, {"uid": uid, "region": PLAYER_API_REGION})
    if e:
        return err(e, 502)
    return jsonify(ok=True, data=data)


@both("/guild")
def guild():
    gid = request.args.get("id", "").strip()
    if not re.fullmatch(r"\d{4,14}", gid):
        return err("সঠিক Guild ID লিখুন")
    if not GUILD_API:
        return err("Guild API এখনো সেট করা হয়নি", 503)
    if "{id}" in GUILD_API:
        data, e = fetch_json(GUILD_API.replace("{id}", gid))
    else:
        data, e = fetch_json(GUILD_API, {"id": gid, "region": PLAYER_API_REGION})
    if e:
        return err(e, 502)
    return jsonify(ok=True, data=data)
