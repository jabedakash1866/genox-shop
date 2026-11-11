import os
import uuid
import html
from decimal import Decimal, InvalidOperation
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

PLAYER_API_URL = os.getenv(
    "PLAYER_API_URL",
    "https://jexarcodexplayer.vercel.app/ffinfo"
)
PLAYER_API_REGION = os.getenv("PLAYER_API_REGION", "BD")
GUILD_API = os.getenv("GUILD_API", "")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN1_CHAT_ID = os.getenv("ADMIN1_CHAT_ID", "")

TIMEOUT = 20

LIKE_PACKAGES = {
    "200": {
        "07 Days": (1400, 55),
        "15 Days": (3000, 90),
        "30 Days": (6000, 150),
        "60 Days": (12000, 300),
        "90 Days": (18000, 450),
    },
    "400": {
        "07 Days": (2800, 150),
        "15 Days": (6000, 240),
        "30 Days": (12000, 400),
        "60 Days": (24000, 800),
        "90 Days": (36000, 1200),
    },
    "1000": {
        "07 Days": (7000, 300),
        "15 Days": (15000, 550),
        "30 Days": (30000, 1000),
        "60 Days": (60000, 2000),
        "90 Days": (90000, 3000),
    },
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


def error(message, status=400):
    return jsonify({
        "success": False,
        "error": message
    }), status


def find_value(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            for actual_key, value in obj.items():
                if actual_key.lower() == key.lower():
                    if value not in (None, ""):
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
            "player_name": str(player_name),
            "bio": str(bio) if bio is not None else ""
        }

    except (requests.RequestException, ValueError, TypeError):
        raise ValueError("Player information could not be verified")


def save_order(order):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Database configuration is incomplete")

    response = requests.post(
        SUPABASE_URL + "/rest/v1/orders",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": "Bearer " + SUPABASE_KEY,
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        },
        json=order,
        timeout=TIMEOUT
    )

    if response.status_code not in (200, 201, 204):
        raise ValueError("Database could not save the order")


def send_telegram(message):
    if not BOT_TOKEN or not ADMIN1_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

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
        return response.ok

    except requests.RequestException:
        return False


def safe(value):
    return html.escape(str(value if value not in (None, "") else "N/A"))


@app.get("/api/health")
def health():
    return jsonify({
        "success": True,
        "message": "GENOX SHOP API is running"
    })


@app.get("/api/player")
def player():
    uid = request.args.get("uid", "").strip()

    if not uid.isdigit():
        return error("Valid Player UID required")

    try:
        result = fetch_player(uid)

        return jsonify({
            "success": True,
            "player_name": result["player_name"],
            "bio": result["bio"]
        })

    except ValueError as exc:
        return error(str(exc), 502)


@app.get("/api/guild")
def guild():
    uid = request.args.get("uid", "").strip()

    if not uid.isdigit():
        return error("Valid Guild UID required")

    if not GUILD_API:
        return error("Guild API is not configured yet", 503)

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
        return error("Guild information unavailable", 502)


@app.post("/api/orders")
def create_order():
    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return error("Invalid order data")

    service = str(body.get("service", "")).lower()
    data = body.get("data")

    if service not in ("likes", "tcp", "glory"):
        return error("Invalid service")

    if not isinstance(data, dict):
        return error("Invalid customer information")

    # Payment information
    payment_method = str(
        data.get("paymentMethod", "")
    ).strip()

    transaction_id = str(
        data.get("transactionId", "")
    ).strip()

    if payment_method != "Nagad":
        return error("Please select Nagad payment")

    if not transaction_id or len(transaction_id) > 100:
        return error("Valid Transaction ID required")

    # Verify package and server-side price
    try:
        if service == "likes":
            pack = str(data.get("pack", "")).strip()
            duration = str(data.get("duration", "")).strip()
            uid = str(data.get("uid", "")).strip()

            if pack not in LIKE_PACKAGES:
                return error("Invalid Likes package")

            if duration not in LIKE_PACKAGES[pack]:
                return error("Invalid Likes duration")

            if not uid.isdigit():
                return error("Valid Player UID required")

            package_likes, price = LIKE_PACKAGES[pack][duration]

            player = fetch_player(uid)

            data["playerName"] = player["player_name"]
            data["totalLikes"] = package_likes
            data["price"] = price

        elif service == "tcp":
            duration = str(data.get("duration", "")).strip()
            bot_name = str(data.get("botName", "")).strip()
            guild_join = str(data.get("guildJoin", "")).strip()

            if duration not in TCP_PACKAGES:
                return error("Invalid TCP package")

            if not bot_name or len(bot_name) > 9:
                return error("Bot Name must be 1-9 characters")

            if guild_join not in ("YES", "NO", "SKIP"):
                return error("Invalid Guild Join selection")

            guild_id = str(data.get("guildId", "")).strip()

            if guild_join == "YES" and not guild_id.isdigit():
                return error("Valid Guild ID required")

            friends = []

            for i in range(1, 5):
                friend_uid = str(
                    data.get("friend" + str(i), "")
                ).strip()

                if friend_uid and not friend_uid.isdigit():
                    return error("Friend UID must contain digits only")

                if friend_uid:
                    friends.append(friend_uid)

            if len(friends) != len(set(friends)):
                return error("Duplicate Friend UID found")

            price = TCP_PACKAGES[duration]
            data["price"] = price

        else:
            package = str(data.get("package", "")).strip()
            guild_id = str(data.get("guildId", "")).strip()

            if package not in GLORY_PACKAGES:
                return error("Invalid Glory package")

            if not guild_id.isdigit():
                return error("Valid Guild ID required")

            price = GLORY_PACKAGES[package]
            data["price"] = price

        # Never trust the price sent by the browser
        submitted_price = Decimal(str(body["data"].get("price", "0")))
        if submitted_price != Decimal(str(price)):
            return error("Package price mismatch. Please refresh your order.")

    except (InvalidOperation, KeyError, ValueError):
        return error("Order information could not be verified")

    data["paymentMethod"] = payment_method
    data["transactionId"] = transaction_id

    order_id = "GX-" + uuid.uuid4().hex[:10].upper()

    now = datetime.now(ZoneInfo("Asia/Dhaka"))
    order_time = now.strftime("%d-%m-%Y %I:%M:%S %p")

    order = {
        "order_id": order_id,
        "service": service.upper(),
        "customer_data": data,
        "total_price": price,
        "status": "Pending Payment"
    }

    try:
        save_order(order)
    except (ValueError, requests.RequestException) as exc:
        return error(str(exc), 500)

    lines = [
        "🛒 <b>NEW ORDER — GENOX SHOP</b>",
        "",
        f"Service: {safe(service.upper())}",
    ]

    if service == "likes":
        lines.extend([
            f"Package: {safe(data.get('pack'))} Likes",
            f"Duration: {safe(data.get('duration'))}",
            f"UID: {safe(data.get('uid'))}",
            f"Player: {safe(data.get('playerName'))}",
            f"Total Likes: {safe(data.get('totalLikes'))}",
        ])

    elif service == "tcp":
        lines.extend([
            f"Package Duration: {safe(data.get('duration'))}",
            f"Bot Name: {safe(data.get('botName'))}",
            f"Guild Join: {safe(data.get('guildJoin'))}",
            f"Guild ID: {safe(data.get('guildId'))}",
        ])

        for i in range(1, 5):
            lines.append(
                f"Friend UID {i}: {safe(data.get('friend' + str(i)))}"
            )

    else:
        lines.extend([
            f"Package: {safe(data.get('package'))}",
            f"Guild ID: {safe(data.get('guildId'))}",
        ])

    lines.extend([
        "",
        f"Payment Method: {safe(payment_method)}",
        f"Transaction ID: {safe(transaction_id)}",
        f"Total Price: ৳{price}",
        "Order Status: Pending Payment",
        f"Order ID: {order_id}",
        f"Order Date & Time: {order_time}",
    ])

    telegram_sent = send_telegram("\n".join(lines))

    return jsonify({
        "success": True,
        "order_id": order_id,
        "status": "Pending Payment",
        "telegram_sent": telegram_sent
    })
