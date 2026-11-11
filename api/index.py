
import os
import uuid
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# ==========================================
# GENOX SHOP CONFIGURATION
# ==========================================

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

REQUEST_TIMEOUT = 20


# ==========================================
# COMMON HELPERS
# ==========================================

def response_error(message, status=400):
    return jsonify({
        "success": False,
        "message": message
    }), status


def supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }


def get_user():
    """Verify the user's Supabase access token."""

    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1].strip()

    if not token:
        return None

    try:
        result = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {token}"
            },
            timeout=REQUEST_TIMEOUT
        )

        if result.status_code != 200:
            return None

        user = result.json()

        if not user.get("id"):
            return None

        return user

    except requests.RequestException:
        logging.exception("Supabase authentication error")
        return None


def send_telegram_message(message):
    """Send order notification to the shop admin."""

    if not BOT_TOKEN or not ADMIN1_CHAT_ID:
        return False

    try:
        result = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ADMIN1_CHAT_ID,
                "text": message
            },
            timeout=REQUEST_TIMEOUT
        )

        return result.status_code == 200

    except requests.RequestException:
        logging.exception("Telegram notification error")
        return False


# ==========================================
# HEALTH CHECK
# ==========================================

@app.route("/api/health", methods=["GET"])
def health():

    return jsonify({
        "success": True,
        "shop": "GENOX SHOP",
        "server": "running",
        "supabase_configured": bool(
            SUPABASE_URL and SUPABASE_KEY
        ),
        "telegram_configured": bool(
            BOT_TOKEN and ADMIN1_CHAT_ID
        )
    })


# ==========================================
# FREE FIRE PLAYER INFORMATION
# ==========================================

@app.route("/api/player", methods=["GET"])
def player_info():

    uid = request.args.get("uid", "").strip()

    if not uid:
        return response_error("Player UID is required.")

    if not PLAYER_API_URL:
        return response_error(
            "Player API is not configured.",
            503
        )

    try:
        result = requests.get(
            PLAYER_API_URL,
            params={
                "uid": uid,
                "region": PLAYER_API_REGION
            },
            timeout=REQUEST_TIMEOUT
        )

        if result.status_code != 200:
            return response_error(
                "Player API is currently unavailable.",
                502
            )

        try:
            data = result.json()
        except ValueError:
            return response_error(
                "Invalid response from Player API.",
                502
            )

        return jsonify({
            "success": True,
            "data": data
        })

    except requests.Timeout:
        return response_error("Player API timed out.", 504)

    except requests.RequestException:
        logging.exception("Player API error")
        return response_error(
            "Unable to connect to Player API.",
            502
        )


# ==========================================
# GUILD INFORMATION
# ==========================================

@app.route("/api/guild", methods=["GET"])
def guild_info():

    user = get_user()

    if not user:
        return response_error(
            "Please login to use this service.",
            401
        )

    uid = request.args.get("uid", "").strip()

    if not uid:
        return response_error("Guild UID is required.")

    if not GUILD_API:
        return response_error(
            "Guild API is not configured.",
            503
        )

    try:
        result = requests.get(
            GUILD_API,
            params={"uid": uid},
            timeout=REQUEST_TIMEOUT
        )

        if result.status_code != 200:
            return response_error(
                "Guild API is currently unavailable.",
                502
            )

        try:
            data = result.json()
        except ValueError:
            return response_error(
                "Invalid response from Guild API.",
                502
            )

        return jsonify({
            "success": True,
            "data": data
        })

    except requests.Timeout:
        return response_error("Guild API timed out.", 504)

    except requests.RequestException:
        logging.exception("Guild API error")
        return response_error(
            "Unable to connect to Guild API.",
            502
        )


# ==========================================
# CREATE ORDER
# ==========================================

@app.route("/api/orders", methods=["POST"])
def create_order():

    # Verify logged-in user
    user = get_user()

    if not user:
        return response_error(
            "Please login before placing an order.",
            401
        )

    if not SUPABASE_URL or not SUPABASE_KEY:
        return response_error(
            "Database is not configured.",
            503
        )

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return response_error("Invalid order information.")

    # Required information
    service = str(data.get("service", "")).strip()
    customer_data = data.get("customer_data", {})

    if not service:
        return response_error("Service name is required.")

    if not isinstance(customer_data, dict):
        return response_error("Invalid customer information.")

    # Price validation
    try:
        price = float(data.get("price", 0))

        if price <= 0 or price != price or price == float("inf"):
            return response_error("Invalid order price.")

    except (TypeError, ValueError):
        return response_error("Invalid order price.")

    # Optional order information
    category = data.get("category")
    package_label = data.get("package_label")
    payment_method = data.get("payment_method")
    transaction_id = data.get("transaction_id")

    try:
        duration_days = data.get("duration_days")
        quantity = data.get("quantity")

        if duration_days is not None:
            duration_days = int(duration_days)

        if quantity is not None:
            quantity = int(quantity)

    except (TypeError, ValueError):
        return response_error("Invalid package information.")

    # Generate unique order number
    order_code = (
        "GX-"
        + datetime.now(timezone.utc).strftime("%Y%m%d")
        + "-"
        + uuid.uuid4().hex[:8].upper()
    )

    # ======================================
    # DATABASE INSERT
    # Supports old required columns too.
    # ======================================

    order_payload = {
        # Existing database required columns
        "order_id": order_code,
        "service": service,
        "customer_data": customer_data,
        "total_price": price,
        "status": "pending",

        # Additional database columns
        "user_id": user["id"],
        "order_code": order_code,
        "category": category,
        "package_label": package_label,
        "duration_days": duration_days,
        "quantity": quantity,
        "price": price,
        "payment_method": payment_method,
        "transaction_id": transaction_id
    }

    try:
        result = requests.post(
            f"{SUPABASE_URL}/rest/v1/orders",
            headers={
                **supabase_headers(),
                "Prefer": "return=representation"
            },
            json=order_payload,
            timeout=REQUEST_TIMEOUT
        )

        if result.status_code not in (200, 201):
            logging.error(
                "Order database error: %s",
                result.text[:1000]
            )

            return response_error(
                "Order could not be saved. Please try again.",
                502
            )

        saved_orders = result.json()

        if not saved_orders:
            return response_error(
                "Order was not confirmed by the database.",
                502
            )

        saved_order = saved_orders[0]

    except requests.RequestException:
        logging.exception("Order database connection error")

        return response_error(
            "Database connection failed.",
            502
        )

    # ======================================
    # TELEGRAM ADMIN NOTIFICATION
    # ======================================

    telegram_message = (
        "🛒 GENOX SHOP - NEW ORDER\n\n"
        f"Order ID: {order_code}\n"
        f"Service: {service}\n"
        f"Category: {category or '-'}\n"
        f"Package: {package_label or '-'}\n"
        f"Duration: {duration_days or '-'} days\n"
        f"Quantity: {quantity or '-'}\n"
        f"Price: ৳{price:g}\n"
        f"Payment: {payment_method or '-'}\n"
        f"Transaction ID: {transaction_id or '-'}\n"
        f"User ID: {user['id']}\n"
        f"Status: pending"
    )

    send_telegram_message(telegram_message)

    # ======================================
    # SUCCESS RESPONSE
    # ======================================

    return jsonify({
        "success": True,
        "message": "Order placed successfully.",
        "order": {
            "id": saved_order.get("id"),
            "order_id": saved_order.get("order_id"),
            "order_code": saved_order.get("order_code"),
            "status": saved_order.get("status"),
            "service": saved_order.get("service"),
            "price": saved_order.get("price"),
            "total_price": saved_order.get("total_price"),
            "created_at": saved_order.get("created_at")
        }
    }), 201


# ==========================================
# VERCEL SERVERLESS APP
# ==========================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
    
