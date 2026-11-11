import os
import re
import uuid
import html
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


def response_error(message, status=400):
    return jsonify({"success": False, "error": message}), status


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
            params={"uid": uid, "region": PLAYER_API_REGION},
            timeout=TIMEOUT
        )
        response.raise_for_status()
        result = response.json()

        if not isinstance(result, (dict, list)):
            raise ValueError("Invalid API response")

        player_name = find_value(
            result,
            ["player_name", "nickname", "nickName", "name"]
        )

        if not player_name:
            raise ValueError("Player information unavailable")

        bio = find_value(result, ["bio", "signature", "player_bio"])

        return {
            "success": True,
            "player_name": str(player_name),
            "bio": str(bio) if bio is not None else "",
            "raw": result
        }

    except requests.RequestException:
        raise ValueError("Player API is temporarily unavailable")
    except (ValueError, TypeError):
        raise ValueError("Player information could not be verified")


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
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        requests.post(
            url,
            json={
                "chat_id": ADMIN1_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=TIMEOUT
        )
    except requests.RequestException:
        pass


@app.get("/api/player")
def player():
    uid = request.args.get("uid", "").strip()

    if not uid or not uid.isdigit():
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


@app.get("/api/guild")
def guild():
    uid = request.args.get("uid", "").strip()

    if not uid or not uid.isdigit():
        return response_error("Valid Guild UID required")

    if not GUILD_API:
        return response_error(
            "Guild API is not configured yet",
            503
        )

    try:
        response = requests.get(
            GUILD_API,
            params={"uid": uid, "region": PLAYER_API_REGION},
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
        return response_error("Guild information unavailable", 502)


@app.post("/api/orders")
def create_order():
    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return response_error("Invalid order data")

    service = str(body.get("service", "")).lower()
    data = body.get("data")

    if service not in ("likes", "tcp", "glory"):
        return response_error("Invalid service")

    if not isinstance(data, dict):
        return response_error("Invalid customer information")

    if service == "likes":
        required = ["pack", "duration", "uid", "playerName"]
        if any(not str(data.get(k, "")).strip() for k in required):
            return response_error("Complete all required Likes fields")

    elif service == "tcp":
        required = ["duration", "botName", "guildJoin"]
        if any(not str(data.get(k, "")).strip() for k in required):
            return response_error("Complete all required TCP fields")

        if len(str(data["botName"])) > 9:
            return response_error("Bot name must be 9 characters or less")

        if data["guildJoin"] == "YES" and not data.get("guildId"):
            return response_error("Guild ID is required")

    elif service == "glory":
        if not data.get("package") or not data.get("guildId"):
            return response_error("Complete all Glory fields")

    try:
        price = float(data.get("price", 0))

        if price <= 0:
            return response_error("Invalid package price")

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

        save_order(order)

        lines = [
            "🛒 <b>NEW ORDER — GENOX SHOP</b>",
            "",
            f"Service: {html.escape(service.upper())}",
        ]

        if service == "likes":
            lines.extend([
                f"Package: {html.escape(str(data.get('pack')))} Likes",
                f"Duration: {html.escape(str(data.get('duration')))}",
                f"UID: {html.escape(str(data.get('uid')))}",
                f"Player: {html.escape(str(data.get('playerName')))}",
                f"Total Likes: {html.escape(str(data.get('totalLikes')))}"
            ])

        elif service == "tcp":
            lines.extend([
                f"Package Duration: {html.escape(str(data.get('duration')))}",
                f"Bot Name: {html.escape(str(data.get('botName')))}",
                f"Guild Join: {html.escape(str(data.get('guildJoin')))}",
                f"Guild ID: {html.escape(str(data.get('guildId') or 'N/A'))}"
            ])

            for i in range(1, 5):
                lines.append(
                    f"Friend UID {i}: "
                    f"{html.escape(str(data.get('friend' + str(i)) or 'N/A'))}"
                )

        else:
            lines.extend([
                f"Package: {html.escape(str(data.get('package')))}",
                f"Guild ID: {html.escape(str(data.get('guildId')))}"
            ])

        lines.extend([
            "",
            f"Total Price: ৳{price:g}",
            "Order Status: Pending Payment",
            f"Order ID: {order_id}",
            f"Order Date & Time: {order_time}"
        ])

        send_telegram("\n".join(lines))

        return jsonify({
            "success": True,
            "order_id": order_id,
            "status": "Pending Payment"
        })

    except (ValueError, requests.RequestException) as error:
        return response_error(str(error), 500)


@app.get("/api/health")
def health():
    return jsonify({"success": True, "message": "GENOX SHOP API is running"})
