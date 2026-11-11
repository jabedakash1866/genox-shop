
import os
import re
import uuid
import html
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==================================================
# GENOX SHOP BACKEND SETTINGS
# Private credentials must remain in Vercel Environment Variables.
# ==================================================

SHOP_NAME = "GENOX SHOP"
ADMIN_NAME = "GENOX"

PLAYER_API_URL = os.getenv(
    "PLAYER_API_URL",
    "https://jexarcodexplayer.vercel.app/ffinfo"
)
PLAYER_API_REGION = os.getenv("PLAYER_API_REGION", "BD")
GUILD_API = os.getenv("GUILD_API", "").strip()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN1_CHAT_ID = os.getenv("ADMIN1_CHAT_ID", "")

TIMEOUT = 20

# ==================================================
# SERVER-SIDE PACKAGE PRICES
# These prices are authoritative.
# ==================================================

LIKE_PACKAGES = {
    "200": {
        "07 Days": {"likes": 1400, "price": 55},
        "15 Days": {"likes": 3000, "price": 90},
        "30 Days": {"likes": 6000, "price": 150},
        "60 Days": {"likes": 12000, "price": 300},
        "90 Days": {"likes": 18000, "price": 450},
    },
    "400": {
        "07 Days": {"likes": 2800, "price": 150},
        "15 Days": {"likes": 6000, "price": 240},
        "30 Days": {"likes": 12000, "price": 400},
        "60 Days": {"likes": 24000, "price": 800},
        "90 Days": {"likes": 36000, "price": 1200},
    },
    "1000": {
        "07 Days": {"likes": 7000, "price": 300},
        "15 Days": {"likes": 15000, "price": 550},
        "30 Days": {"likes": 30000, "price": 1000},
        "60 Days": {"likes": 60000, "price": 2000},
        "90 Days": {"likes": 90000, "price": 3000},
    }
}

TCP_PACKAGES = {
    "07 Days": 130,
    "15 Days": 275,
    "30 Days": 550,
    "60 Days": 1100,
}

GLORY_PACKAGES = {
    "4 Glory Bot": 120,
    "8 Glory Bot": 240,
    "12 Glory Bot": 360,
    "16 Glory Bot": 480,
}

ALLOWED_PAYMENT_METHODS = {
    "Nagad",
    "bKash",
    "Rocket"
}

# ==================================================
# HELPERS
# ==================================================

def response_error(message, status=400):
    return jsonify({
        "success": False,
        "error": message
    }), status


def clean(value, limit=200):
    return str(value or "").strip()[:limit]


def valid_uid(value):
    return bool(re.fullmatch(r"[0-9]{1,25}", str(value or "").strip()))


def find_value(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            for actual_key, value in obj.items():
                if (
                    isinstance(actual_key, str)
                    and actual_key.lower() == key.lower()
                    and value not in (None, "")
                ):
                    return value

        for value in obj.values():
            result = find_value(value, keys)
            if result not in (None, ""):
                return result

    elif isinstance(obj, list):
        for item in obj:
            result = find_value(item, keys)
            if result not in (None, ""):
                return result

    return None


def fetch_player(uid):
    try:
        response = requests.get(
            PLAYER_API_URL,
            params={
                "uid": uid,
                "region": PLAYER_API_REGION
            },
            timeout=TIMEOUT
        )

        response.raise_for_status()
        result = response.json()

        if not isinstance(result, (dict, list)):
            raise ValueError()

        player_name = find_value(
            result,
            ["player_name", "nickname", "nickName", "name"]
        )

        if not player_name:
            raise ValueError()

        bio = find_value(
            result,
            ["bio", "signature", "player_bio"]
        )

        return {
            "success": True,
            "player_name": str(player_name),
            "bio": str(bio) if bio is not None else ""
        }

    except (requests.RequestException, ValueError, TypeError):
        raise ValueError(
            "Player information is temporarily unavailable"
        )


def save_order(order):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Database configuration is incomplete")

    url = SUPABASE_URL + "/rest/v1/orders"

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": "Bearer " + SUPABASE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

    response = requests.post(
        url,
        headers=headers,
        json=order,
        timeout=TIMEOUT
    )

    if response.status_code not in (200, 201, 204):
        raise ValueError("Order could not be saved in database")


def send_telegram(message):
    if not BOT_TOKEN or not ADMIN1_CHAT_ID:
        return False

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": ADMIN1_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=TIMEOUT
        )

        return (
            response.status_code == 200
            and response.json().get("ok") is True
        )

    except (requests.RequestException, ValueError):
        return False


def get_payment(data):
    method = clean(data.get("paymentMethod"), 30)
    transaction_id = clean(data.get("transactionId"), 120)

    if method not in ALLOWED_PAYMENT_METHODS:
        raise ValueError("Invalid payment method")

    if not transaction_id:
        raise ValueError("Transaction ID is required")

    if len(transaction_id) < 4:
        raise ValueError("Invalid Transaction ID")

    return method, transaction_id


def telegram_message(order_id, service, data, price, method, txn, order_time):
    lines = [
        "🛒 <b>NEW ORDER — GENOX SHOP</b>",
        "",
        f"Order ID: <code>{html.escape(order_id)}</code>",
        f"Service: {html.escape(service.upper())}",
        f"Admin: {html.escape(ADMIN_NAME)}",
        ""
    ]

    for key, value in data.items():
        if key in ("price", "paymentMethod", "transactionId"):
            continue

        if value not in (None, ""):
            lines.append(
                f"{html.escape(str(key))}: "
                f"{html.escape(str(value))}"
            )

    lines.extend([
        "",
        f"Payment Method: {html.escape(method)}",
        f"Transaction ID: <code>{html.escape(txn)}</code>",
        f"Total Price: ৳{price}",
        "Order Status: Pending Payment",
        f"Order Date: {html.escape(order_time)}",
        "",
        "⚠️ Please verify payment manually."
    ])

    return "\n".join(lines)


# ==================================================
# PLAYER API
# ==================================================

@app.get("/api/player")
def player():
    uid = request.args.get("uid", "").strip()

    if not valid_uid(uid):
        return response_error("Valid Player UID required")

    try:
        result = fetch_player(uid)

        return jsonify({
            "success": True,
            "player_name": result["player_name"],
            "bio": result["bio"]
        })

    except ValueError as error:
        return response_error(str(error), 502)


# ==================================================
# GUILD API
# ==================================================

@app.get("/api/guild")
def guild():
    uid = request.args.get("uid", "").strip()

    if not valid_uid(uid):
        return response_error("Valid Guild UID required")

    if not GUILD_API:
        return response_error(
            "Guild API is not configured yet",
            503
        )

    try:
        response = requests.get(
            GUILD_API,
            params={
                "uid": uid,
                "region": PLAYER_API_REGION
            },
            timeout=TIMEOUT
        )

        response.raise_for_status()
        result = response.json()

        if not isinstance(result, (dict, list)):
            raise ValueError()

        return jsonify({
            "success": True,
            "data": result
        })

    except (requests.RequestException, ValueError):
        return response_error(
            "Guild information unavailable",
            502
        )


# ==================================================
# ORDER VALIDATION AND PRICE CALCULATION
# ==================================================

def validate_order(service, data):

    if service == "likes":
        pack = clean(data.get("pack"), 10)
        duration = clean(data.get("duration"), 20)
        uid = clean(data.get("uid"), 25)

        if pack not in LIKE_PACKAGES:
            raise ValueError("Invalid Likes package")

        if duration not in LIKE_PACKAGES[pack]:
            raise ValueError("Invalid Likes duration")

        if not valid_uid(uid):
            raise ValueError("Valid Player UID required")

        player = fetch_player(uid)

        package = LIKE_PACKAGES[pack][duration]

        data["pack"] = pack
        data["duration"] = duration
        data["uid"] = uid
        data["playerName"] = player["player_name"]
        data["totalLikes"] = package["likes"]

        return Decimal(str(package["price"]))

    if service == "tcp":
        duration = clean(data.get("duration"), 20)
        bot_name = clean(data.get("botName"), 9)
        guild_join = clean(data.get("guildJoin"), 10)
        guild_id = clean(data.get("guildId"), 25)

        if duration not in TCP_PACKAGES:
            raise ValueError("Invalid TCP package")

        if not bot_name:
            raise ValueError("Bot Name is required")

        if len(bot_name) > 9:
            raise ValueError("Bot name must be 9 characters or less")

        if guild_join not in ("YES", "NO", "SKIP"):
            raise ValueError("Invalid Guild Join option")

        if guild_join == "YES" and not valid_uid(guild_id):
            raise ValueError("Valid Guild ID is required")

        if guild_id and not valid_uid(guild_id):
            raise ValueError("Invalid Guild ID")

        data["duration"] = duration
        data["botName"] = bot_name
        data["guildJoin"] = guild_join
        data["guildId"] = guild_id

        for i in range(1, 5):
            friend = clean(data.get("friend" + str(i)), 25)

            if friend and not valid_uid(friend):
                raise ValueError("Invalid Friend UID")

            data["friend" + str(i)] = friend

        return Decimal(str(TCP_PACKAGES[duration]))

    if service == "glory":
        package = clean(data.get("package"), 30)
        guild_id = clean(data.get("guildId"), 25)

        if package not in GLORY_PACKAGES:
            raise ValueError("Invalid Glory package")

        if not valid_uid(guild_id):
            raise ValueError("Valid Guild ID required")

        data["package"] = package
        data["guildId"] = guild_id

        return Decimal(str(GLORY_PACKAGES[package]))

    raise ValueError("Invalid service")


# ==================================================
# CREATE ORDER
# ==================================================

@app.post("/api/orders")
def create_order():
    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return response_error("Invalid order data")

    service = clean(body.get("service"), 20).lower()
    data = body.get("data")

    if service not in ("likes", "tcp", "glory"):
        return response_error("Invalid service")

    if not isinstance(data, dict):
        return response_error("Invalid customer information")

    # Copy input so server-controlled fields can be overwritten.
    data = dict(data)

    try:
        # Server calculates price. Never trust browser-submitted price.
        price = validate_order(service, data)

        payment_method, transaction_id = get_payment(data)

        order_id = "GX-" + uuid.uuid4().hex[:10].upper()

        now = datetime.now(ZoneInfo("Asia/Dhaka"))
        order_time = now.strftime("%d-%m-%Y %I:%M:%S %p")

        data["paymentMethod"] = payment_method
        data["transactionId"] = transaction_id

        order = {
            "order_id": order_id,
            "service": service.upper(),
            "customer_data": data,
            "total_price": float(price),
            "status": "Pending Payment"
        }

        # Save first, then notify Telegram.
        save_order(order)

        message = telegram_message(
            order_id,
            service,
            data,
            price,
            payment_method,
            transaction_id,
            order_time
        )

        telegram_sent = send_telegram(message)

        return jsonify({
            "success": True,
            "order_id": order_id,
            "status": "Pending Payment",
            "telegram_sent": telegram_sent
        })

    except ValueError as error:
        return response_error(str(error), 400)

    except requests.RequestException:
        return response_error(
            "A network error occurred. Please try again.",
            502
        )

    except Exception:
        app.logger.exception("Order processing failed")
        return response_error(
            "Order could not be processed. Please contact admin.",
            500
        )


# ==================================================
# HEALTH CHECK
# ==================================================

@app.get("/api/health")
def health():
    return jsonify({
        "success": True,
        "shop": SHOP_NAME,
        "message": "GENOX SHOP API is running"
    })
    
