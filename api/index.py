
import os
import uuid
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN1_CHAT_ID = os.getenv("ADMIN1_CHAT_ID", "")
PLAYER_API_URL = os.getenv(
    "PLAYER_API_URL",
    "https://jexarcodexplayer.vercel.app/ffinfo"
)
PLAYER_API_REGION = os.getenv("PLAYER_API_REGION", "BD")
GUILD_API = os.getenv("GUILD_API", "")

TIMEOUT = 20


def response(data, status=200):
    return jsonify(data), status


def supabase_headers(token=None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": "Bearer " + (token or SUPABASE_KEY),
        "Content-Type": "application/json",
    }
    return headers


def get_user():
    auth = request.headers.get("Authorization", "")

    if not auth.startswith("Bearer "):
        return None, "লগইন করুন"

    token = auth[7:].strip()

    if not token or not SUPABASE_URL or not SUPABASE_KEY:
        return None, "Authentication configuration missing"

    try:
        r = requests.get(
            SUPABASE_URL + "/auth/v1/user",
            headers=supabase_headers(token),
            timeout=TIMEOUT
        )

        if r.status_code != 200:
            return None, "লগইন সেশন সঠিক নয়"

        user = r.json()

        if not user.get("id"):
            return None, "User পাওয়া যায়নি"

        return user, None

    except requests.RequestException:
        return None, "Authentication server unavailable"


def make_order_code():
    chars = string.ascii_uppercase + string.digits
    return "GX-" + "".join(
        secrets.choice(chars) for _ in range(9)
    )


def send_telegram(message):
    if not BOT_TOKEN or not ADMIN1_CHAT_ID:
        return False

    try:
        r = requests.post(
            "https://api.telegram.org/bot"
            + BOT_TOKEN
            + "/sendMessage",
            json={
                "chat_id": ADMIN1_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=TIMEOUT
        )
        return r.ok
    except requests.RequestException:
        return False


def insert_order(payload):
    url = SUPABASE_URL + "/rest/v1/orders"

    r = requests.post(
        url,
        headers={
            **supabase_headers(),
            "Prefer": "return=representation"
        },
        json=payload,
        timeout=TIMEOUT
    )

    if not r.ok:
        try:
            error = r.json()
        except ValueError:
            error = {"message": r.text[:300]}

        raise RuntimeError(
            "Database order insert failed: "
            + str(error.get("message", error))
        )

    data = r.json()

    if isinstance(data, list) and data:
        return data[0]

    return data


@app.get("/api/health")
def health():
    return response({
        "ok": True,
        "service": "GENOX SHOP API",
        "time": datetime.now(timezone.utc).isoformat()
    })


@app.get("/api/player")
def player():
    uid = request.args.get("uid", "").strip()

    if not uid.isdigit() or not 6 <= len(uid) <= 14:
        return response({
            "ok": False,
            "error": "সঠিক Player UID দিন"
        }, 400)

    try:
        r = requests.get(
            PLAYER_API_URL,
            params={
                "uid": uid,
                "region": PLAYER_API_REGION
            },
            timeout=TIMEOUT
        )

        data = r.json()

        if not r.ok:
            return response({
                "ok": False,
                "error": "Player API unavailable"
            }, 502)

        return response({
            "ok": True,
            "data": data
        })

    except requests.RequestException:
        return response({
            "ok": False,
            "error": "Player API connection failed"
        }, 502)


@app.get("/api/guild")
def guild():
    uid = request.args.get("uid", "").strip()

    if not uid.isdigit() or not 6 <= len(uid) <= 14:
        return response({
            "ok": False,
            "error": "সঠিক Guild ID দিন"
        }, 400)

    if not GUILD_API:
        return response({
            "ok": False,
            "error": "Guild API এখনো configure করা হয়নি"
        }, 503)

    try:
        r = requests.get(
            GUILD_API,
            params={"uid": uid},
            timeout=TIMEOUT
        )

        try:
            data = r.json()
        except ValueError:
            data = {"result": r.text[:1000]}

        if not r.ok:
            return response({
                "ok": False,
                "error": "Guild API request failed"
            }, 502)

        return response({
            "ok": True,
            "data": data
        })

    except requests.RequestException:
        return response({
            "ok": False,
            "error": "Guild API connection failed"
        }, 502)


@app.post("/api/orders")
def create_order():
    user, error = get_user()

    if error:
        return response({
            "ok": False,
            "error": error
        }, 401)

    data = request.get_json(silent=True) or {}

    service = str(data.get("service", "")).strip().lower()
    allowed = {"likes", "tcp", "glory"}

    if service not in allowed:
        return response({
            "ok": False,
            "error": "Invalid service"
        }, 400)

    package_id = str(data.get("package_id", "")).strip()
    package_label = str(data.get("package_label", "")).strip()

    if not package_id or not package_label:
        return response({
            "ok": False,
            "error": "Package information missing"
        }, 400)

    try:
        price = Decimal(str(data.get("price", "0")))

        if not price.is_finite() or price <= 0:
            raise InvalidOperation()

    except (InvalidOperation, ValueError):
        return response({
            "ok": False,
            "error": "Invalid package price"
        }, 400)

    payment_method = str(
        data.get("payment_method", "")
    ).strip().lower()

    if payment_method not in {"nagad", "bkash", "rocket"}:
        return response({
            "ok": False,
            "error": "Invalid payment method"
        }, 400)

    transaction_id = str(
        data.get("transaction_id", "")
    ).strip()

    if len(transaction_id) < 6 or len(transaction_id) > 100:
        return response({
            "ok": False,
            "error": "সঠিক Transaction ID দিন"
        }, 400)

    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    uid = str(data.get("uid", "")).strip()

    if len(name) < 2 or not phone:
        return response({
            "ok": False,
            "error": "Customer information incomplete"
        }, 400)

    if not uid.isdigit() or not 6 <= len(uid) <= 14:
        return response({
            "ok": False,
            "error": "সঠিক UID দিন"
        }, 400)

    try:
        duration = int(data.get("duration_days") or 0)
        quantity = int(data.get("quantity") or 1)

        if duration < 0 or quantity < 1:
            raise ValueError()

    except (ValueError, TypeError):
        return response({
            "ok": False,
            "error": "Invalid package quantity or duration"
        }, 400)

    customer_data = {
        "name": name,
        "phone": phone,
        "uid": uid,
        "friend_uids": data.get("friend_uids", []),
        "package_id": package_id
    }

    order_code = make_order_code()

    order_payload = {
        "user_id": user["id"],
        "order_code": order_code,
        "status": "pending",
        "service": service,
        "category": str(data.get("category", "")),
        "package_label": package_label,
        "duration_days": duration,
        "quantity": quantity,
        "price": float(price),
        "payment_method": payment_method,
        "transaction_id": transaction_id,
        "customer_data": customer_data
    }

    try:
        order = insert_order(order_payload)

    except (requests.RequestException, RuntimeError) as e:
        return response({
            "ok": False,
            "error": str(e)
        }, 500)

    telegram_message = (
        "<b>GENOX SHOP — NEW ORDER</b>\n\n"
        "<b>Order:</b> " + order_code + "\n"
        "<b>Service:</b> " + service.upper() + "\n"
        "<b>Package:</b> " + package_label + "\n"
        "<b>Price:</b> ৳" + str(price) + "\n"
        "<b>Name:</b> " + name + "\n"
        "<b>Phone:</b> " + phone + "\n"
        "<b>UID:</b> " + uid + "\n"
        "<b>Payment:</b> " + payment_method.upper() + "\n"
        "<b>Transaction:</b> " + transaction_id + "\n"
        "<b>User ID:</b> " + user["id"]
    )

    send_telegram(telegram_message)

    return response({
        "ok": True,
        "message": "Order submitted successfully",
        "order": order
    }, 201)


@app.errorhandler(404)
def not_found(_):
    return response({
        "ok": False,
        "error": "API route not found"
    }, 404)


@app.errorhandler(405)
def method_not_allowed(_):
    return response({
        "ok": False,
        "error": "Method not allowed"
    }, 405)


@app.errorhandler(500)
def server_error(_):
    return response({
        "ok": False,
        "error": "Internal server error"
    }, 500)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000"))
    )
    
