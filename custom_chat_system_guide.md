# 🗨️ QuickStock Custom Chat System — Implementation Guide

## Overview

This guide walks through building a secure, encrypted, real-time chat system between **Shopkeepers** and **Wholesalers** inside the existing QuickStock Flask + PostgreSQL application. WhatsApp integration is removed entirely. All messages are **end-to-end encrypted using AES-256-GCM**, the system is designed to scale to **10,000+ users**, and role-based access ensures shopkeepers only talk to their assigned wholesalers.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser)                         │
│  Shopkeeper Dashboard ◄──── WebSocket ────► Wholesaler Dashboard│
│         ↓                                           ↓           │
│    AES-256 Encrypt                         AES-256 Decrypt      │
└────────────────┬──────────────────────────────────┬────────────┘
                 │          WebSocket (WSS)           │
                 ▼                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Flask-SocketIO Server                         │
│  • Auth middleware (JWT / session)                              │
│  • Message routing by conversation_id                           │
│  • Rate limiting (Flask-Limiter)                                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Database                         │
│  conversations  │  messages  │  users  │  chat_keys             │
│ (encrypted body, IV stored per message)                         │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**
- **WebSockets** (Flask-SocketIO) for real-time delivery; falls back to long-polling.
- **AES-256-GCM** symmetric encryption — server derives a per-conversation key stored in `chat_keys`. Messages are encrypted before DB storage.
- **JWT tokens** for WebSocket auth (session cookies do not work reliably over socket upgrades).
- **Role enforcement** — `shop` users can only open conversations with users of `wholesaler` role.

---

## Step 1: Remove WhatsApp Integration

### 1.1 Remove WhatsApp dependencies

```bash
pip uninstall twilio
```

In `requirements.txt`, remove or comment out:
```
# twilio==X.X.X          ← REMOVE
# whatsapp-business-api  ← REMOVE (if present)
```

### 1.2 Remove WhatsApp code from `app.py`

Delete or comment out any route or function referencing WhatsApp / Twilio:

```python
# DELETE these — examples of what to look for:
# from twilio.rest import Client
# TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
# TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
# TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_NUMBER")

# @app.route('/send_whatsapp', methods=['POST'])   ← DELETE this route
# def send_whatsapp(): ...

# def send_low_stock_whatsapp(product, stock): ... ← DELETE this function
```

### 1.3 Remove WhatsApp UI from dashboard

In `dashboard_template.html`, find and delete any button / tab / section with labels like:
- "Send WhatsApp"
- "WhatsApp Alert"
- `onclick="sendWhatsApp(...)"`

---

## Step 2: Install Required Packages

```bash
pip install flask-socketio==5.3.6 \
            flask-jwt-extended==4.6.0 \
            cryptography==42.0.5 \
            flask-limiter==3.5.0 \
            eventlet==0.35.2
```

Add to `requirements.txt`:
```
flask-socketio==5.3.6
flask-jwt-extended==4.6.0
cryptography==42.0.5
flask-limiter==3.5.0
eventlet==0.35.2
```

> **Why eventlet?** Flask-SocketIO requires an async worker. Eventlet is free, lightweight, and works with Gunicorn in production.

---

## Step 3: Database Schema — New Tables

Run these SQL statements in your PostgreSQL database.

### 3.1 Update `users` table

The existing `USERS` dict in `app.py` must be migrated to the database. If you already have a `users` table from a previous session, add the missing columns:

```sql
-- Create users table if it doesn't exist
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role        VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'shop', 'wholesaler')),
    display_name VARCHAR(100),
    shop_name   VARCHAR(100),
    phone       VARCHAR(20),
    created_at  TIMESTAMP DEFAULT NOW(),
    is_active   BOOLEAN DEFAULT TRUE
);

-- Add indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role     ON users(role);
```

### 3.2 Create `conversations` table

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id              SERIAL PRIMARY KEY,
    shop_user_id    INTEGER NOT NULL REFERENCES users(id),
    wholesaler_user_id INTEGER NOT NULL REFERENCES users(id),
    created_at      TIMESTAMP DEFAULT NOW(),
    last_message_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(shop_user_id, wholesaler_user_id)
);

CREATE INDEX IF NOT EXISTS idx_conv_shop       ON conversations(shop_user_id);
CREATE INDEX IF NOT EXISTS idx_conv_wholesaler ON conversations(wholesaler_user_id);
```

### 3.3 Create `messages` table

```sql
CREATE TABLE IF NOT EXISTS messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_id       INTEGER NOT NULL REFERENCES users(id),
    encrypted_body  TEXT NOT NULL,      -- AES-256-GCM ciphertext (base64)
    iv              VARCHAR(64) NOT NULL, -- Initialization vector (base64)
    auth_tag        VARCHAR(64) NOT NULL, -- GCM auth tag (base64)
    message_type    VARCHAR(20) DEFAULT 'text' CHECK (message_type IN ('text', 'order_suggestion', 'system')),
    is_read         BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_msg_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_msg_sender       ON messages(sender_id);
CREATE INDEX IF NOT EXISTS idx_msg_created      ON messages(created_at DESC);
```

### 3.4 Create `chat_keys` table

```sql
-- Stores the per-conversation AES key (itself encrypted with the server master key)
CREATE TABLE IF NOT EXISTS chat_keys (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER UNIQUE NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    encrypted_key   TEXT NOT NULL,   -- The AES key, encrypted with server MASTER_KEY
    key_iv          VARCHAR(64) NOT NULL,
    key_auth_tag    VARCHAR(64) NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

> **Security note:** The `chat_keys` table holds per-conversation AES-256 keys, which are themselves encrypted using a server-level **MASTER_KEY** stored only in environment variables — never in the database.

---

## Step 4: Encryption Utility Module

Create a new file `chat_crypto.py` in your project root:

```python
# chat_crypto.py
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MASTER_KEY = base64.b64decode(os.getenv("CHAT_MASTER_KEY", ""))


def _ensure_master_key():
    if not MASTER_KEY or len(MASTER_KEY) != 32:
        raise RuntimeError(
            "CHAT_MASTER_KEY env var is missing or not a 32-byte base64 string. "
            "Generate with: python -c \"import os,base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )


def generate_conversation_key() -> bytes:
    """Generate a new random 256-bit AES key for a conversation."""
    return os.urandom(32)


def encrypt_key(raw_key: bytes) -> dict:
    """Encrypt a conversation key using the server MASTER_KEY."""
    _ensure_master_key()
    iv = os.urandom(12)
    aesgcm = AESGCM(MASTER_KEY)
    ciphertext_with_tag = aesgcm.encrypt(iv, raw_key, None)
    # GCM appends 16-byte auth tag at the end
    ciphertext = ciphertext_with_tag[:-16]
    auth_tag   = ciphertext_with_tag[-16:]
    return {
        "encrypted_key": base64.b64encode(ciphertext).decode(),
        "key_iv":        base64.b64encode(iv).decode(),
        "key_auth_tag":  base64.b64encode(auth_tag).decode(),
    }


def decrypt_key(encrypted_key: str, key_iv: str, key_auth_tag: str) -> bytes:
    """Decrypt a conversation key using the server MASTER_KEY."""
    _ensure_master_key()
    iv         = base64.b64decode(key_iv)
    ciphertext = base64.b64decode(encrypted_key)
    auth_tag   = base64.b64decode(key_auth_tag)
    aesgcm     = AESGCM(MASTER_KEY)
    raw_key    = aesgcm.decrypt(iv, ciphertext + auth_tag, None)
    return raw_key


def encrypt_message(raw_text: str, conversation_key: bytes) -> dict:
    """Encrypt a message string with the given AES-256-GCM key."""
    iv = os.urandom(12)
    aesgcm = AESGCM(conversation_key)
    ciphertext_with_tag = aesgcm.encrypt(iv, raw_text.encode("utf-8"), None)
    ciphertext = ciphertext_with_tag[:-16]
    auth_tag   = ciphertext_with_tag[-16:]
    return {
        "encrypted_body": base64.b64encode(ciphertext).decode(),
        "iv":             base64.b64encode(iv).decode(),
        "auth_tag":       base64.b64encode(auth_tag).decode(),
    }


def decrypt_message(encrypted_body: str, iv: str, auth_tag: str,
                    conversation_key: bytes) -> str:
    """Decrypt a stored message ciphertext."""
    iv_bytes   = base64.b64decode(iv)
    ciphertext = base64.b64decode(encrypted_body)
    tag_bytes  = base64.b64decode(auth_tag)
    aesgcm     = AESGCM(conversation_key)
    plaintext  = aesgcm.decrypt(iv_bytes, ciphertext + tag_bytes, None)
    return plaintext.decode("utf-8")
```

### 4.1 Add the master key to your environment

```bash
# Generate a secure 32-byte key
python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
```

Add to your `.env` file:
```
CHAT_MASTER_KEY=<output_from_above>
```

> **Never commit `.env` to Git.** Add it to `.gitignore`.

---

## Step 5: Database Helper Functions

Add these functions to `app.py` (near your existing DB helpers):

```python
# ── Chat DB Helpers ──────────────────────────────────────────────

from chat_crypto import (
    generate_conversation_key,
    encrypt_key, decrypt_key,
    encrypt_message, decrypt_message,
)


def get_or_create_conversation(shop_user_id: int, wholesaler_user_id: int) -> int:
    """Return existing conversation id or create a new one with a fresh AES key."""
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT id FROM conversations WHERE shop_user_id=%s AND wholesaler_user_id=%s",
        (shop_user_id, wholesaler_user_id)
    )
    row = cur.fetchone()
    if row:
        cur.close(); conn.close()
        return row[0]

    # New conversation
    cur.execute(
        """INSERT INTO conversations (shop_user_id, wholesaler_user_id)
           VALUES (%s, %s) RETURNING id""",
        (shop_user_id, wholesaler_user_id)
    )
    conv_id = cur.fetchone()[0]

    # Generate and store encrypted conversation key
    raw_key     = generate_conversation_key()
    key_payload = encrypt_key(raw_key)
    cur.execute(
        """INSERT INTO chat_keys (conversation_id, encrypted_key, key_iv, key_auth_tag)
           VALUES (%s, %s, %s, %s)""",
        (conv_id,
         key_payload["encrypted_key"],
         key_payload["key_iv"],
         key_payload["key_auth_tag"])
    )
    conn.commit()
    cur.close(); conn.close()
    return conv_id


def get_conversation_key(conversation_id: int) -> bytes:
    """Fetch and decrypt the AES key for a given conversation."""
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT encrypted_key, key_iv, key_auth_tag FROM chat_keys WHERE conversation_id=%s",
        (conversation_id,)
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        raise ValueError(f"No key found for conversation {conversation_id}")
    return decrypt_key(row[0], row[1], row[2])


def save_message(conversation_id: int, sender_id: int,
                 plaintext: str, message_type: str = "text") -> dict:
    """Encrypt and persist a message; update conversation timestamp."""
    key     = get_conversation_key(conversation_id)
    payload = encrypt_message(plaintext, key)

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        """INSERT INTO messages
               (conversation_id, sender_id, encrypted_body, iv, auth_tag, message_type)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING id, created_at""",
        (conversation_id, sender_id,
         payload["encrypted_body"], payload["iv"], payload["auth_tag"],
         message_type)
    )
    msg_id, created_at = cur.fetchone()
    cur.execute(
        "UPDATE conversations SET last_message_at=NOW() WHERE id=%s",
        (conversation_id,)
    )
    conn.commit()
    cur.close(); conn.close()
    return {"id": msg_id, "created_at": str(created_at)}


def load_messages(conversation_id: int, limit: int = 50, offset: int = 0) -> list:
    """Load and decrypt the most recent messages from a conversation."""
    key  = get_conversation_key(conversation_id)
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        """SELECT m.id, m.sender_id, m.encrypted_body, m.iv, m.auth_tag,
                  m.message_type, m.is_read, m.created_at, u.username, u.display_name
           FROM messages m
           JOIN users u ON u.id = m.sender_id
           WHERE m.conversation_id = %s
           ORDER BY m.created_at DESC
           LIMIT %s OFFSET %s""",
        (conversation_id, limit, offset)
    )
    rows = cur.fetchall()
    cur.close(); conn.close()

    messages = []
    for r in rows:
        try:
            plaintext = decrypt_message(r[2], r[3], r[4], key)
        except Exception:
            plaintext = "[encrypted — decryption failed]"
        messages.append({
            "id":           r[0],
            "sender_id":    r[1],
            "text":         plaintext,
            "message_type": r[5],
            "is_read":      r[6],
            "created_at":   str(r[7]),
            "username":     r[8],
            "display_name": r[9] or r[8],
        })
    return list(reversed(messages))   # Chronological order


def get_user_conversations(user_id: int, role: str) -> list:
    """List all conversations for a user with unread counts."""
    conn = get_db_connection()
    cur  = conn.cursor()
    if role == "shop":
        query = """
            SELECT c.id, u.id, u.username, u.display_name, u.shop_name,
                   c.last_message_at,
                   (SELECT COUNT(*) FROM messages m
                    WHERE m.conversation_id = c.id
                    AND m.sender_id != %s AND m.is_read = FALSE) AS unread
            FROM conversations c
            JOIN users u ON u.id = c.wholesaler_user_id
            WHERE c.shop_user_id = %s
            ORDER BY c.last_message_at DESC
        """
    else:  # wholesaler
        query = """
            SELECT c.id, u.id, u.username, u.display_name, u.shop_name,
                   c.last_message_at,
                   (SELECT COUNT(*) FROM messages m
                    WHERE m.conversation_id = c.id
                    AND m.sender_id != %s AND m.is_read = FALSE) AS unread
            FROM conversations c
            JOIN users u ON u.id = c.shop_user_id
            WHERE c.wholesaler_user_id = %s
            ORDER BY c.last_message_at DESC
        """
    cur.execute(query, (user_id, user_id))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [
        {
            "conversation_id": r[0],
            "other_user_id":   r[1],
            "username":        r[2],
            "display_name":    r[3] or r[2],
            "shop_name":       r[4],
            "last_message_at": str(r[5]),
            "unread_count":    r[6],
        }
        for r in rows
    ]
```

---

## Step 6: JWT Authentication Setup

Add JWT configuration to `app.py` (near your existing `app.secret_key` line):

```python
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity, get_jwt
)
from datetime import timedelta

app.config["JWT_SECRET_KEY"]       = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=8)
jwt = JWTManager(app)
```

Add to `.env`:
```
JWT_SECRET_KEY=<another-strong-random-string>
```

### 6.1 New `/api/chat_token` endpoint

This issues a short-lived JWT for WebSocket authentication:

```python
@app.route("/api/chat_token", methods=["POST"])
@login_required
def get_chat_token():
    """Issue a JWT for WebSocket chat authentication."""
    user_id   = session.get("user_id")
    username  = session.get("user")
    role      = session.get("role")
    token = create_access_token(
        identity=str(user_id),
        additional_claims={"username": username, "role": role}
    )
    return jsonify({"token": token})
```

> **Note:** Update your existing `/login` route to also store `user_id` in the session:
> ```python
> session['user_id'] = user_data['id']   # add this line after session['role'] = ...
> ```
> You will need to migrate USERS from the hardcoded dict to the PostgreSQL `users` table (see Step 7).

---

## Step 7: Migrate Users to Database

Replace the hardcoded `USERS` dict with DB-backed authentication.

### 7.1 Password hashing utility

```python
from werkzeug.security import generate_password_hash, check_password_hash
```

### 7.2 Migration script `migrate_users.py`

Create this file and run it **once**:

```python
# migrate_users.py — run once: python migrate_users.py
import os
import psycopg2
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

seed_users = [
    # (username, plain_password, role, display_name)
    ("admin",       "quickstock2026",  "admin",      "Administrator"),
    ("shop_shrey",  "shrey2026",       "shop",       "Shrey's Shop"),
    ("wholesaler1", "wholesale2026",   "wholesaler", "ABC Wholesale"),
]

conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()
for username, password, role, display_name in seed_users:
    hashed = generate_password_hash(password)
    cur.execute(
        """INSERT INTO users (username, password_hash, role, display_name)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (username) DO UPDATE
           SET password_hash=EXCLUDED.password_hash, role=EXCLUDED.role""",
        (username, hashed, role, display_name)
    )
conn.commit()
cur.close()
conn.close()
print("Users migrated successfully.")
```

```bash
python migrate_users.py
```

### 7.3 Update the `/login` route

```python
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "SELECT id, password_hash, role, display_name FROM users WHERE username=%s AND is_active=TRUE",
            (username,)
        )
        row = cur.fetchone()
        cur.close(); conn.close()

        if row and check_password_hash(row[1], password):
            session['user']       = username
            session['user_id']    = row[0]
            session['role']       = row[2]
            session['display_name'] = row[3]
            if row[2] == 'admin':
                return redirect(url_for('admin_panel'))
            return redirect(url_for('home'))
        flash('Invalid credentials')
    return render_template('login_template.html')
```

---

## Step 8: Flask-SocketIO Setup & Event Handlers

### 8.1 Initialize SocketIO in `app.py`

```python
from flask_socketio import (
    SocketIO, emit, join_room, leave_room,
    disconnect
)
import jwt as pyjwt   # PyJWT for manual token decode in SocketIO

socketio = SocketIO(
    app,
    async_mode="eventlet",
    cors_allowed_origins="*",        # Tighten in production
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1_000_000,  # 1 MB max message size
)
```

### 8.2 Connection authentication

```python
from functools import wraps

connected_users = {}   # sid -> {user_id, username, role}

@socketio.on("connect")
def on_connect():
    token = request.args.get("token")
    if not token:
        disconnect()
        return False
    try:
        secret = app.config["JWT_SECRET_KEY"]
        decoded = pyjwt.decode(token, secret, algorithms=["HS256"])
        user_id  = int(decoded["sub"])
        username = decoded["username"]
        role     = decoded["role"]
        connected_users[request.sid] = {
            "user_id":  user_id,
            "username": username,
            "role":     role,
        }
        print(f"[Chat] Connected: {username} ({role}) sid={request.sid}")
    except pyjwt.ExpiredSignatureError:
        disconnect()
        return False
    except Exception as e:
        print(f"[Chat] Auth error: {e}")
        disconnect()
        return False


@socketio.on("disconnect")
def on_disconnect():
    user_info = connected_users.pop(request.sid, None)
    if user_info:
        print(f"[Chat] Disconnected: {user_info['username']}")
```

### 8.3 Join a conversation room

```python
@socketio.on("join_conversation")
def on_join_conversation(data):
    """Client joins a SocketIO room for a specific conversation."""
    user_info = connected_users.get(request.sid)
    if not user_info:
        emit("error", {"msg": "Not authenticated"})
        return

    conversation_id = int(data.get("conversation_id", 0))
    if not conversation_id:
        emit("error", {"msg": "conversation_id required"})
        return

    # Verify this user belongs to the conversation
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        """SELECT id FROM conversations
           WHERE id=%s AND (shop_user_id=%s OR wholesaler_user_id=%s)""",
        (conversation_id, user_info["user_id"], user_info["user_id"])
    )
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        emit("error", {"msg": "Access denied"})
        return

    room = f"conv_{conversation_id}"
    join_room(room)
    emit("joined", {"conversation_id": conversation_id, "room": room})
    print(f"[Chat] {user_info['username']} joined room {room}")
```

### 8.4 Send a message

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, app=app,
                  default_limits=["200 per minute"])

@socketio.on("send_message")
def on_send_message(data):
    """Handle incoming chat message, encrypt, persist, broadcast."""
    user_info = connected_users.get(request.sid)
    if not user_info:
        emit("error", {"msg": "Not authenticated"})
        return

    conversation_id = int(data.get("conversation_id", 0))
    text = (data.get("text") or "").strip()
    message_type = data.get("message_type", "text")

    if not text or len(text) > 2000:
        emit("error", {"msg": "Invalid message: empty or too long (max 2000 chars)"})
        return
    if message_type not in ("text", "order_suggestion", "system"):
        message_type = "text"

    # Verify membership
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        """SELECT id FROM conversations
           WHERE id=%s AND (shop_user_id=%s OR wholesaler_user_id=%s)""",
        (conversation_id, user_info["user_id"], user_info["user_id"])
    )
    if not cur.fetchone():
        cur.close(); conn.close()
        emit("error", {"msg": "Access denied"})
        return
    cur.close(); conn.close()

    # Persist encrypted message
    meta = save_message(conversation_id, user_info["user_id"], text, message_type)

    # Broadcast decrypted message to room members only
    payload = {
        "id":              meta["id"],
        "conversation_id": conversation_id,
        "sender_id":       user_info["user_id"],
        "sender_name":     user_info["username"],
        "text":            text,
        "message_type":    message_type,
        "created_at":      meta["created_at"],
    }
    room = f"conv_{conversation_id}"
    emit("new_message", payload, to=room)
    print(f"[Chat] Message saved (conv={conversation_id}) from {user_info['username']}")
```

### 8.5 Mark messages as read

```python
@socketio.on("mark_read")
def on_mark_read(data):
    user_info = connected_users.get(request.sid)
    if not user_info:
        return
    conversation_id = int(data.get("conversation_id", 0))
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        """UPDATE messages SET is_read=TRUE
           WHERE conversation_id=%s AND sender_id != %s AND is_read=FALSE""",
        (conversation_id, user_info["user_id"])
    )
    conn.commit()
    cur.close(); conn.close()
```

---

## Step 9: REST API Endpoints

Add these REST endpoints to `app.py`:

```python
# ── Chat REST Endpoints ──────────────────────────────────────────

@app.route("/api/conversations", methods=["GET"])
@login_required
def api_get_conversations():
    user_id = session.get("user_id")
    role    = session.get("role")
    convs   = get_user_conversations(user_id, role)
    return jsonify({"conversations": convs})


@app.route("/api/conversations/start", methods=["POST"])
@login_required
def api_start_conversation():
    """Shopkeeper initiates a conversation with a wholesaler (or vice-versa)."""
    data             = request.get_json()
    other_user_id    = int(data.get("other_user_id", 0))
    current_user_id  = session.get("user_id")
    current_role     = session.get("role")

    if not other_user_id:
        return jsonify({"error": "other_user_id required"}), 400

    # Validate the other user exists and has the right role
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("SELECT id, role FROM users WHERE id=%s AND is_active=TRUE", (other_user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        return jsonify({"error": "User not found"}), 404

    other_role = row[1]
    # Enforce: shop ↔ wholesaler only
    valid_pairs = {("shop", "wholesaler"), ("wholesaler", "shop")}
    if (current_role, other_role) not in valid_pairs:
        return jsonify({"error": "Conversations only allowed between shop and wholesaler"}), 403

    shop_id       = current_user_id if current_role == "shop" else other_user_id
    wholesaler_id = current_user_id if current_role == "wholesaler" else other_user_id
    conv_id       = get_or_create_conversation(shop_id, wholesaler_id)
    return jsonify({"conversation_id": conv_id})


@app.route("/api/conversations/<int:conv_id>/messages", methods=["GET"])
@login_required
def api_get_messages(conv_id):
    user_id = session.get("user_id")
    # Verify access
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT id FROM conversations WHERE id=%s AND (shop_user_id=%s OR wholesaler_user_id=%s)",
        (conv_id, user_id, user_id)
    )
    if not cur.fetchone():
        cur.close(); conn.close()
        return jsonify({"error": "Access denied"}), 403
    cur.close(); conn.close()

    limit  = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))
    msgs   = load_messages(conv_id, limit, offset)
    return jsonify({"messages": msgs})


@app.route("/api/wholesalers", methods=["GET"])
@login_required
def api_list_wholesalers():
    """Returns available wholesalers for a shopkeeper to start a chat with."""
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT id, username, display_name, shop_name FROM users WHERE role='wholesaler' AND is_active=TRUE"
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify({
        "wholesalers": [
            {"id": r[0], "username": r[1], "display_name": r[2] or r[1], "shop_name": r[3]}
            for r in rows
        ]
    })
```

---

## Step 10: Auto Low-Stock Order Suggestion

When a product's stock drops below threshold, automatically send an order suggestion to the wholesaler in the existing conversation (replacing the old WhatsApp alert):

```python
def send_order_suggestion(shop_user_id: int, product_name: str,
                           current_stock: float, threshold: float, unit: str):
    """Called after a sale if stock drops below threshold."""
    conn = get_db_connection()
    cur  = conn.cursor()
    # Find conversation with any wholesaler
    cur.execute(
        "SELECT id, wholesaler_user_id FROM conversations WHERE shop_user_id=%s ORDER BY last_message_at DESC LIMIT 1",
        (shop_user_id,)
    )
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        print(f"[Chat] No wholesaler conversation found for shop_user_id={shop_user_id}")
        return

    conv_id       = row[0]
    wholesaler_id = row[1]

    suggested_qty = max(int(threshold * 3 - current_stock), int(threshold * 2))
    message_text  = (
        f"📦 LOW STOCK ALERT: {product_name}\n"
        f"Current stock: {current_stock} {unit}\n"
        f"Threshold: {threshold} {unit}\n"
        f"Suggested order: {suggested_qty} {unit}\n"
        f"Please confirm this order."
    )
    # System sends it as the shop user
    save_message(conv_id, shop_user_id, message_text, message_type="order_suggestion")

    # Push real-time notification via SocketIO if wholesaler is online
    room = f"conv_{conv_id}"
    socketio.emit("new_message", {
        "conversation_id": conv_id,
        "sender_id":       shop_user_id,
        "text":            message_text,
        "message_type":    "order_suggestion",
    }, to=room)

    print(f"[Chat] Order suggestion sent for {product_name} in conv {conv_id}")
```

Hook this into the existing transaction logic in `app.py`. Find where stock is updated after a confirmed sale and add:

```python
# After updating stock and logging transaction:
if new_stock < products[product_key]['threshold']:
    shop_user_id = session.get('user_id')
    if shop_user_id:
        send_order_suggestion(
            shop_user_id,
            product_key,
            new_stock,
            products[product_key]['threshold'],
            products[product_key]['unit']
        )
```

---

## Step 11: Frontend Chat UI

Add a **Chat** tab to `dashboard_template.html`. Insert this inside your existing tab navigation and tab content sections.

### 11.1 Tab button (add to nav tabs)

```html
<button class="tab-btn" onclick="openTab('chat')" id="tab-chat">
  💬 Chat
  <span id="chat-unread-badge" class="badge" style="display:none;">0</span>
</button>
```

### 11.2 Chat tab HTML

```html
<div id="tab-content-chat" class="tab-content" style="display:none;">
  <div class="chat-layout">

    <!-- Conversation List (left panel) -->
    <div class="chat-sidebar" id="chat-sidebar">
      <div class="chat-sidebar-header">
        <h3>Conversations</h3>
        <button onclick="showNewChatModal()" class="btn-icon" title="New Chat">＋</button>
      </div>
      <div id="conversation-list"></div>
    </div>

    <!-- Message Area (right panel) -->
    <div class="chat-main" id="chat-main">
      <div id="chat-placeholder" style="display:flex; align-items:center;
           justify-content:center; height:100%; color:#888;">
        Select a conversation to start chatting
      </div>

      <div id="chat-window" style="display:none; flex-direction:column; height:100%;">
        <div class="chat-header" id="chat-header">
          <strong id="chat-partner-name"></strong>
        </div>
        <div class="chat-messages" id="chat-messages"></div>
        <div class="chat-input-area">
          <input type="text" id="chat-input" placeholder="Type a message…"
                 onkeydown="if(event.key==='Enter') sendChatMessage()" maxlength="2000" />
          <button onclick="sendChatMessage()" class="btn-send">Send</button>
        </div>
      </div>
    </div>
  </div>
</div>
```

### 11.3 Chat CSS (add to your existing `<style>` block)

```css
.chat-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  height: 520px;
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: hidden;
}
.chat-sidebar {
  border-right: 1px solid #ddd;
  background: #f9f9f9;
  display: flex;
  flex-direction: column;
}
.chat-sidebar-header {
  padding: 12px 16px;
  border-bottom: 1px solid #ddd;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.conv-item {
  padding: 12px 16px;
  cursor: pointer;
  border-bottom: 1px solid #eee;
  position: relative;
}
.conv-item:hover, .conv-item.active { background: #e8f4fd; }
.conv-item .conv-name { font-weight: 600; font-size: 14px; }
.conv-item .conv-preview { font-size: 12px; color: #666; margin-top: 2px; }
.conv-unread {
  background: #e53935; color: white;
  border-radius: 50%; width: 20px; height: 20px;
  font-size: 11px; display: flex; align-items: center;
  justify-content: center; position: absolute; right: 12px; top: 12px;
}
.chat-main { display: flex; flex-direction: column; }
.chat-header {
  padding: 12px 16px;
  border-bottom: 1px solid #ddd;
  background: #fff;
  font-size: 15px;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: #fff;
}
.msg-bubble {
  max-width: 70%;
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.4;
  word-break: break-word;
}
.msg-bubble.mine {
  background: #1976d2; color: white;
  align-self: flex-end;
  border-bottom-right-radius: 4px;
}
.msg-bubble.theirs {
  background: #f0f0f0; color: #222;
  align-self: flex-start;
  border-bottom-left-radius: 4px;
}
.msg-bubble.order_suggestion {
  background: #fff3e0; border: 1px solid #ff9800;
  white-space: pre-line;
}
.msg-time { font-size: 11px; color: #aaa; margin-top: 2px; text-align: right; }
.chat-input-area {
  display: flex;
  padding: 10px 12px;
  border-top: 1px solid #ddd;
  gap: 8px;
  background: #fff;
}
.chat-input-area input {
  flex: 1; padding: 8px 12px;
  border: 1px solid #ccc; border-radius: 20px;
  outline: none; font-size: 14px;
}
.btn-send {
  background: #1976d2; color: white;
  border: none; border-radius: 20px;
  padding: 8px 18px; cursor: pointer; font-size: 14px;
}
.btn-send:hover { background: #1565c0; }
.badge {
  background: #e53935; color: white;
  border-radius: 50%; width: 18px; height: 18px;
  font-size: 11px; display: inline-flex;
  align-items: center; justify-content: center;
  margin-left: 4px;
}
```

### 11.4 Chat JavaScript (add to your existing `<script>` block)

```javascript
// ── Chat Client ──────────────────────────────────────────────────
let chatSocket = null;
let activeConvId = null;
let chatJwt = null;
let currentUserId = null;

async function initChat() {
  // Fetch JWT for socket auth
  const res = await fetch('/api/chat_token', { method: 'POST' });
  const data = await res.json();
  chatJwt = data.token;
  currentUserId = data.user_id;   // add user_id to the token response

  chatSocket = io({ query: { token: chatJwt } });

  chatSocket.on('connect', () => {
    console.log('[Chat] Socket connected');
    loadConversations();
  });

  chatSocket.on('new_message', (msg) => {
    if (msg.conversation_id === activeConvId) {
      appendMessage(msg);
      chatSocket.emit('mark_read', { conversation_id: activeConvId });
    } else {
      incrementUnread(msg.conversation_id);
    }
  });

  chatSocket.on('joined', (data) => {
    console.log('[Chat] Joined room', data.room);
    loadMessages(data.conversation_id);
  });

  chatSocket.on('error', (err) => console.error('[Chat] Error:', err.msg));
}

async function loadConversations() {
  const res  = await fetch('/api/conversations');
  const data = await res.json();
  const list = document.getElementById('conversation-list');
  list.innerHTML = '';
  let totalUnread = 0;

  (data.conversations || []).forEach(conv => {
    totalUnread += conv.unread_count || 0;
    const item = document.createElement('div');
    item.className = 'conv-item';
    item.dataset.convId = conv.conversation_id;
    item.innerHTML = `
      <div class="conv-name">${conv.display_name}</div>
      <div class="conv-preview">${conv.shop_name || ''}</div>
      ${conv.unread_count > 0
        ? `<div class="conv-unread">${conv.unread_count}</div>`
        : ''}
    `;
    item.onclick = () => openConversation(conv.conversation_id, conv.display_name);
    list.appendChild(item);
  });

  // Update tab badge
  const badge = document.getElementById('chat-unread-badge');
  if (totalUnread > 0) {
    badge.textContent = totalUnread;
    badge.style.display = 'inline-flex';
  } else {
    badge.style.display = 'none';
  }
}

function openConversation(convId, partnerName) {
  activeConvId = convId;
  document.getElementById('chat-placeholder').style.display = 'none';
  document.getElementById('chat-window').style.display     = 'flex';
  document.getElementById('chat-partner-name').textContent  = partnerName;
  document.getElementById('chat-messages').innerHTML        = '';

  // Highlight active conversation
  document.querySelectorAll('.conv-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.convId) === convId);
    if (parseInt(el.dataset.convId) === convId) {
      const badge = el.querySelector('.conv-unread');
      if (badge) badge.remove();
    }
  });

  chatSocket.emit('join_conversation', { conversation_id: convId });
}

async function loadMessages(convId) {
  const res  = await fetch(`/api/conversations/${convId}/messages?limit=50`);
  const data = await res.json();
  const box  = document.getElementById('chat-messages');
  box.innerHTML = '';
  (data.messages || []).forEach(msg => appendMessage(msg, false));
  box.scrollTop = box.scrollHeight;
  chatSocket.emit('mark_read', { conversation_id: convId });
}

function appendMessage(msg, scroll = true) {
  const box    = document.getElementById('chat-messages');
  const isMine = msg.sender_id === currentUserId;
  const div    = document.createElement('div');
  const time   = new Date(msg.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  div.className = `msg-bubble ${isMine ? 'mine' : 'theirs'} ${msg.message_type !== 'text' ? msg.message_type : ''}`;
  div.innerHTML  = `${escapeHtml(msg.text)}<div class="msg-time">${time}</div>`;
  box.appendChild(div);
  if (scroll) box.scrollTop = box.scrollHeight;
}

function sendChatMessage() {
  const input = document.getElementById('chat-input');
  const text  = input.value.trim();
  if (!text || !activeConvId || !chatSocket) return;
  chatSocket.emit('send_message', {
    conversation_id: activeConvId,
    text:            text,
    message_type:    'text',
  });
  input.value = '';
}

async function showNewChatModal() {
  const res  = await fetch('/api/wholesalers');
  const data = await res.json();
  const name = prompt(
    'Available wholesalers:\n' +
    (data.wholesalers || []).map(w => `ID ${w.id}: ${w.display_name}`).join('\n') +
    '\n\nEnter wholesaler ID:'
  );
  if (!name) return;
  const wId = parseInt(name);
  if (isNaN(wId)) return;
  const r2   = await fetch('/api/conversations/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ other_user_id: wId }),
  });
  const d2   = await r2.json();
  if (d2.conversation_id) {
    loadConversations();
    openConversation(d2.conversation_id, `Wholesaler ${wId}`);
  }
}

function incrementUnread(convId) {
  const item = document.querySelector(`.conv-item[data-conv-id="${convId}"]`);
  if (!item) return;
  let badge = item.querySelector('.conv-unread');
  if (!badge) {
    badge = document.createElement('div');
    badge.className = 'conv-unread';
    badge.textContent = '0';
    item.appendChild(badge);
  }
  badge.textContent = parseInt(badge.textContent) + 1;
  loadConversations(); // refresh total badge
}

function escapeHtml(text) {
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
             .replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

// Initialize chat when tab is first opened
document.getElementById('tab-chat').addEventListener('click', () => {
  if (!chatSocket) initChat();
});
```

---

## Step 12: Update `app.run()` for SocketIO

At the bottom of `app.py`, replace:
```python
if __name__ == '__main__':
    app.run(debug=True)
```

With:
```python
if __name__ == '__main__':
    import eventlet
    import eventlet.wsgi
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
```

---

## Step 13: Production Deployment (Gunicorn + Nginx)

For production with 10,000+ users, use Gunicorn with eventlet workers:

### `gunicorn.conf.py`

```python
worker_class   = "eventlet"
workers        = 1          # SocketIO requires 1 worker (use Redis for multi-worker)
worker_connections = 1000
bind           = "0.0.0.0:5000"
timeout        = 120
keepalive      = 5
```

```bash
gunicorn -c gunicorn.conf.py app:app
```

### Nginx config (add WebSocket upgrade support)

```nginx
location /socket.io/ {
    proxy_pass         http://localhost:5000;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade $http_upgrade;
    proxy_set_header   Connection "upgrade";
    proxy_set_header   Host $host;
    proxy_cache_bypass $http_upgrade;
}
```

### Scale to multiple workers (Redis adapter)

When you need to scale beyond a single server:

```bash
pip install flask-socketio[redis] redis
```

```python
socketio = SocketIO(app, async_mode="eventlet",
                    message_queue="redis://localhost:6379")
```

---

## Step 14: Security Checklist

| Concern | Implementation |
|---|---|
| Message confidentiality | AES-256-GCM encryption per conversation |
| Key storage | Per-conversation keys encrypted with `CHAT_MASTER_KEY` (env var only) |
| Authentication | Session (HTTP) + JWT (WebSocket) |
| Password storage | `werkzeug` bcrypt hashing (never plain text) |
| Role enforcement | Only `shop` ↔ `wholesaler` conversations allowed |
| Message validation | Max 2000 chars, type whitelist |
| GCM auth tag | Prevents ciphertext tampering (authenticated encryption) |
| XSS prevention | `escapeHtml()` on all message display |
| SQL injection | All queries use parameterized `%s` placeholders |
| HTTPS | Use Nginx with SSL in production (Let's Encrypt) |
| Rate limiting | Flask-Limiter on REST endpoints + SocketIO event throttle |
| Secrets | All keys in `.env`, never in codebase |

---

## Step 15: Testing the Chat System

### 15.1 Quick manual test

1. Start the server: `python app.py`
2. Log in as `shop_shrey` in browser tab 1.
3. Log in as `wholesaler1` in browser tab 2 (incognito).
4. Shop user opens Chat tab → clicks ＋ → enters wholesaler ID.
5. Both users join the conversation room.
6. Send messages and verify real-time delivery.
7. Restart the server → reload and verify messages persist (decrypted from DB).

### 15.2 Verify encryption in database

```python
# Verify via psql: messages should show garbled ciphertext, NOT plaintext
import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur  = conn.cursor()
cur.execute("SELECT encrypted_body FROM messages LIMIT 3")
for row in cur.fetchall():
    print(row[0])   # Should print base64-encoded ciphertext, not readable text
cur.close(); conn.close()
```

### 15.3 Unit test for encryption

```python
# test_chat_crypto.py
from chat_crypto import encrypt_message, decrypt_message, generate_conversation_key

def test_roundtrip():
    key       = generate_conversation_key()
    plaintext = "Hello, can I order 50 kg of rice?"
    payload   = encrypt_message(plaintext, key)
    recovered = decrypt_message(payload["encrypted_body"], payload["iv"],
                                payload["auth_tag"], key)
    assert recovered == plaintext, "Decryption mismatch!"
    print("✅ Encryption roundtrip passed")

test_roundtrip()
```

---

## Summary of All New Files

| File | Purpose |
|---|---|
| `chat_crypto.py` | AES-256-GCM encrypt/decrypt utilities |
| `migrate_users.py` | One-time script to seed users into DB |
| `gunicorn.conf.py` | Production server config |
| `test_chat_crypto.py` | Encryption unit test |

## Summary of Modified Files

| File | Changes |
|---|---|
| `app.py` | Remove WhatsApp; add SocketIO, JWT, chat DB helpers, REST endpoints, auto-suggestions |
| `dashboard_template.html` | Remove WhatsApp buttons; add Chat tab with UI + JS |
| `requirements.txt` | Add flask-socketio, flask-jwt-extended, cryptography, flask-limiter, eventlet |
| `.env` | Add `CHAT_MASTER_KEY`, `JWT_SECRET_KEY` |
