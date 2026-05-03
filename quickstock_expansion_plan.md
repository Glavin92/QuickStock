# QuickStock Expansion Plan — Detailed Implementation Guide

> **Project:** QuickStock Voice Inventory Management System  
> **Stack:** Flask + PostgreSQL (Neon) + Jinja2 + SpeechRecognition  
> **Target:** Real small shopkeepers in India, scaling to 10,000+ users  
> **Constraint:** Free APIs only, open-source/self-hosted preferred  

---

## Table of Contents

1. [Security Fix — Rotate Exposed Credentials](#0-critical-security-fix)
2. [System Changes — Location, Login & Onboarding](#1-system-changes)
3. [Billing System](#2-billing-system)
4. [Location-Based Analytics](#3-location-based-analytics)
5. [WhatsApp Integration](#4-whatsapp-integration)
6. [Wholesaler Dashboard](#5-wholesaler-dashboard)
7. [Database Schema — Full Reference](#6-full-database-schema)
8. [Deployment & Scaling Notes](#7-deployment--scaling-notes)

---

## 0. CRITICAL SECURITY FIX

**Do this before anything else.** Your `DATABASE_URL` (including password) is exposed inside `copyai.json`.

### Steps

1. Go to [https://console.neon.tech](https://console.neon.tech)
2. Select your project → **Settings → Reset Password**
3. Copy the new `DATABASE_URL`
4. Update your local `.env` file:
   ```env
   DATABASE_URL=postgresql://neondb_owner:<NEW_PASSWORD>@ep-sweet-field-a1ir3s6u-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```
5. Delete or `.gitignore` `copyai.json` immediately
6. Add `*.json` exports to `.gitignore`

---

## 1. System Changes

### 1.1 Database — Add New Tables

Run this SQL in your Neon console before writing any Python code.

```sql
-- Shops table (replaces hardcoded USERS dict)
CREATE TABLE IF NOT EXISTS shops (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    shop_name VARCHAR(100) NOT NULL,
    owner_name VARCHAR(100),
    phone VARCHAR(15) UNIQUE NOT NULL,
    role VARCHAR(20) DEFAULT 'shop',           -- 'shop' | 'admin' | 'wholesaler'
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    address TEXT,
    city VARCHAR(50),
    state VARCHAR(50),
    pin_code VARCHAR(10),
    whatsapp_number VARCHAR(15),
    is_verified BOOLEAN DEFAULT FALSE,
    otp_secret TEXT,
    otp_expiry TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- OTP log (for audit trail)
CREATE TABLE IF NOT EXISTS otp_log (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(15) NOT NULL,
    otp_code VARCHAR(6) NOT NULL,
    purpose VARCHAR(30),                       -- 'login' | 'register' | 'reset'
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    used BOOLEAN DEFAULT FALSE
);
```

---

### 1.2 Capture Location During Onboarding

The goal is to get GPS coordinates when the shopkeeper first registers or logs in.

#### Step 1 — Update `register_template.html`

Add a hidden location field and a JS block at the bottom of your existing registration form:

```html
<!-- Add inside your registration <form> -->
<input type="hidden" id="lat" name="latitude">
<input type="hidden" id="lng" name="longitude">
<input type="text" name="address" placeholder="Shop Address (Street, Area)" required>
<input type="text" name="city" placeholder="City" required>
<input type="text" name="pin_code" placeholder="PIN Code" required>

<button type="button" id="get-location-btn" onclick="getLocation()">
  📍 Auto-Detect My Location (Optional)
</button>
<small id="location-status"></small>
```

```html
<!-- Add before </body> -->
<script>
function getLocation() {
  const status = document.getElementById('location-status');
  if (!navigator.geolocation) {
    status.textContent = 'GPS not supported on this device.';
    return;
  }
  status.textContent = '📡 Detecting location...';
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      document.getElementById('lat').value = pos.coords.latitude;
      document.getElementById('lng').value = pos.coords.longitude;
      status.textContent = '✅ Location captured!';
    },
    (err) => {
      status.textContent = '⚠️ Could not auto-detect. Please enter PIN code manually.';
    }
  );
}
</script>
```

#### Step 2 — Update `app.py` Registration Route

Replace your current hardcoded `USERS` dict logic with a DB-driven register route:

```python
import hashlib, secrets

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        username   = data.get('username', '').strip()
        password   = data.get('password', '').strip()
        shop_name  = data.get('shop_name', '').strip()
        phone      = data.get('phone', '').strip()
        address    = data.get('address', '').strip()
        city       = data.get('city', '').strip()
        pin_code   = data.get('pin_code', '').strip()
        lat        = data.get('latitude') or None
        lng        = data.get('longitude') or None

        if not all([username, password, shop_name, phone]):
            return render_template('register_template.html', error='All fields required')

        try:
            conn = get_db_connection()
            cur  = conn.cursor()
            cur.execute("""
                INSERT INTO shops
                  (username, password_hash, shop_name, phone, address, city, pin_code, latitude, longitude)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (username, hash_password(password), shop_name, phone,
                  address, city, pin_code, lat, lng))
            conn.commit()
            cur.close(); conn.close()
            return redirect(url_for('login'))
        except Exception as e:
            return render_template('register_template.html', error=f'Username or phone already exists.')

    return render_template('register_template.html')
```

#### Step 3 — Update Login to Use DB

Replace the `USERS` dict check in your existing `/login` route:

```python
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute(
            "SELECT id, username, password_hash, role, shop_name FROM shops WHERE username = %s",
            (username,)
        )
        row = cur.fetchone()
        cur.close(); conn.close()

        if row and row[2] == hash_password(password):
            session['user']    = row[1]
            session['user_id'] = row[0]
            session['role']    = row[3]
            session['shop']    = row[4]
            if row[3] == 'admin':
                return redirect(url_for('admin_panel'))
            return redirect(url_for('home'))
        else:
            flash('Invalid credentials')
    return render_template('login_template.html')
```

---

### 1.3 OTP Login Verification (Free — Using Fast2SMS)

[Fast2SMS](https://www.fast2sms.com) offers a free tier (₹50 credits on sign-up, ~1000 OTPs) and has a simple REST API. No payment required to start.

#### Step 1 — Get Free API Key

1. Register at [https://www.fast2sms.com](https://www.fast2sms.com)
2. Go to **Dev API → API Keys → Copy Key**
3. Add to `.env`:
   ```env
   FAST2SMS_API_KEY=your_key_here
   ```

#### Step 2 — OTP Helper Functions

Add these to `app.py`:

```python
import random, requests as http_requests
from datetime import datetime, timedelta

def generate_otp() -> str:
    return str(random.randint(100000, 999999))

def send_otp_fast2sms(phone: str, otp: str) -> bool:
    """Send OTP via Fast2SMS free DLT route."""
    api_key = os.getenv('FAST2SMS_API_KEY')
    url = "https://www.fast2sms.com/dev/bulkV2"
    payload = {
        "route":   "q",           # Quick/Transactional route
        "message": f"Your QuickStock OTP is {otp}. Valid for 10 minutes. Do not share.",
        "language": "english",
        "flash":   0,
        "numbers": phone,
    }
    headers = {"authorization": api_key, "Content-Type": "application/json"}
    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=8)
        data = resp.json()
        return data.get("return") == True
    except Exception as e:
        print(f"OTP send failed: {e}")
        return False

def save_otp_to_db(phone: str, otp: str, purpose: str = 'login'):
    conn = get_db_connection()
    cur  = conn.cursor()
    expires = datetime.utcnow() + timedelta(minutes=10)
    cur.execute("""
        INSERT INTO otp_log (phone, otp_code, purpose, expires_at)
        VALUES (%s, %s, %s, %s)
    """, (phone, otp, purpose, expires))
    conn.commit()
    cur.close(); conn.close()

def verify_otp_from_db(phone: str, otp: str) -> bool:
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id FROM otp_log
        WHERE phone = %s AND otp_code = %s
          AND used = FALSE AND expires_at > NOW()
        ORDER BY created_at DESC LIMIT 1
    """, (phone, otp))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE otp_log SET used = TRUE WHERE id = %s", (row[0],))
        conn.commit()
    cur.close(); conn.close()
    return row is not None
```

#### Step 3 — OTP Login Flow Routes

```python
@app.route('/login/otp/send', methods=['POST'])
def send_login_otp():
    phone = request.form.get('phone', '').strip()
    conn  = get_db_connection()
    cur   = conn.cursor()
    cur.execute("SELECT id, username, role, shop_name FROM shops WHERE phone = %s", (phone,))
    shop  = cur.fetchone()
    cur.close(); conn.close()

    if not shop:
        flash('Phone number not registered.')
        return redirect(url_for('login'))

    otp = generate_otp()
    save_otp_to_db(phone, otp, 'login')
    success = send_otp_fast2sms(phone, otp)
    if not success:
        flash('Could not send OTP. Try password login.')
        return redirect(url_for('login'))

    session['otp_phone'] = phone
    return render_template('otp_verify_template.html', phone=phone)

@app.route('/login/otp/verify', methods=['POST'])
def verify_login_otp():
    phone    = session.get('otp_phone')
    otp_code = request.form.get('otp', '').strip()

    if not phone or not verify_otp_from_db(phone, otp_code):
        flash('Invalid or expired OTP.')
        return render_template('otp_verify_template.html', phone=phone, error=True)

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("SELECT id, username, role, shop_name FROM shops WHERE phone = %s", (phone,))
    row  = cur.fetchone()
    cur.close(); conn.close()

    session['user']    = row[1]
    session['user_id'] = row[0]
    session['role']    = row[2]
    session['shop']    = row[3]
    session.pop('otp_phone', None)
    return redirect(url_for('home'))
```

#### Step 4 — Update `login_template.html`

Add a tab or second section for OTP login:

```html
<!-- Add a phone+OTP login form alongside the existing password form -->
<form action="/login/otp/send" method="POST">
  <input type="tel" name="phone" placeholder="Registered Mobile Number" required>
  <button type="submit">Send OTP</button>
</form>
```

---

## 2. Billing System

### Overview

The billing system generates printable invoices for items sold via voice or manual entry. It stores bills in PostgreSQL and supports PDF download via the browser's print function (no PDF library needed).

### 2.1 Database Tables

```sql
CREATE TABLE IF NOT EXISTS bills (
    id SERIAL PRIMARY KEY,
    bill_number VARCHAR(30) UNIQUE NOT NULL,
    shop_id INT REFERENCES shops(id),
    customer_name VARCHAR(100),
    customer_phone VARCHAR(15),
    subtotal NUMERIC(10,2) DEFAULT 0,
    discount NUMERIC(10,2) DEFAULT 0,
    gst_percent NUMERIC(5,2) DEFAULT 0,
    gst_amount NUMERIC(10,2) DEFAULT 0,
    total NUMERIC(10,2) DEFAULT 0,
    payment_method VARCHAR(20) DEFAULT 'cash',  -- 'cash' | 'upi' | 'credit'
    payment_status VARCHAR(20) DEFAULT 'paid',  -- 'paid' | 'pending'
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bill_items (
    id SERIAL PRIMARY KEY,
    bill_id INT REFERENCES bills(id) ON DELETE CASCADE,
    product_name VARCHAR(100) NOT NULL,
    quantity NUMERIC(10,3) NOT NULL,
    unit VARCHAR(20),
    price_per_unit NUMERIC(10,2) NOT NULL,
    line_total NUMERIC(10,2) NOT NULL
);

-- Index for fast date-range queries
CREATE INDEX IF NOT EXISTS idx_bills_created_at ON bills(created_at);
CREATE INDEX IF NOT EXISTS idx_bills_shop_id ON bills(shop_id);
```

### 2.2 Bill Number Generator

Add to `app.py`:

```python
def generate_bill_number() -> str:
    """Generate bill number like QS-20260503-0042"""
    today = datetime.now().strftime('%Y%m%d')
    conn  = get_db_connection()
    cur   = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM bills WHERE DATE(created_at) = CURRENT_DATE"
    )
    count = cur.fetchone()[0] + 1
    cur.close(); conn.close()
    return f"QS-{today}-{str(count).zfill(4)}"
```

### 2.3 Create Bill Route

```python
@app.route('/billing/create', methods=['GET', 'POST'])
@login_required
def create_bill():
    if request.method == 'POST':
        data            = request.get_json()
        customer_name   = data.get('customer_name', 'Walk-in Customer')
        customer_phone  = data.get('customer_phone', '')
        items           = data.get('items', [])      # list of {product, qty, unit, price}
        discount        = float(data.get('discount', 0))
        gst_percent     = float(data.get('gst_percent', 0))
        payment_method  = data.get('payment_method', 'cash')

        if not items:
            return jsonify({'error': 'No items in bill'}), 400

        subtotal = sum(i['qty'] * i['price'] for i in items)
        gst_amt  = round(subtotal * gst_percent / 100, 2)
        total    = round(subtotal - discount + gst_amt, 2)
        bill_no  = generate_bill_number()

        try:
            conn = get_db_connection()
            cur  = conn.cursor()
            cur.execute("""
                INSERT INTO bills
                  (bill_number, shop_id, customer_name, customer_phone,
                   subtotal, discount, gst_percent, gst_amount, total,
                   payment_method)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (bill_no, session.get('user_id'), customer_name, customer_phone,
                  subtotal, discount, gst_percent, gst_amt, total, payment_method))
            bill_id = cur.fetchone()[0]

            for item in items:
                line = round(item['qty'] * item['price'], 2)
                cur.execute("""
                    INSERT INTO bill_items
                      (bill_id, product_name, quantity, unit, price_per_unit, line_total)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (bill_id, item['product'], item['qty'],
                      item.get('unit', 'unit'), item['price'], line))

                # Deduct stock automatically
                update_product_stock_in_db(
                    item['product'],
                    max(0, get_all_products_db().get(item['product'], {}).get('current_stock', 0) - item['qty'])
                )
                log_transaction_in_db('sale', item['product'], item['qty'],
                                      item.get('unit', 'unit'))

            conn.commit()
            cur.close(); conn.close()
            return jsonify({'success': True, 'bill_id': bill_id, 'bill_number': bill_no, 'total': total})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # GET — render billing UI with current products
    products_data = get_all_products_db()
    return render_template('billing_template.html', products=products_data)
```

### 2.4 Bill Print / PDF Route

```python
@app.route('/billing/print/<int:bill_id>')
@login_required
def print_bill(bill_id):
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT b.*, s.shop_name, s.address, s.phone
        FROM bills b
        LEFT JOIN shops s ON b.shop_id = s.id
        WHERE b.id = %s
    """, (bill_id,))
    bill = cur.fetchone()
    cur.execute("SELECT * FROM bill_items WHERE bill_id = %s", (bill_id,))
    items = cur.fetchall()
    cur.close(); conn.close()

    if not bill:
        return "Bill not found", 404
    return render_template('bill_print_template.html', bill=bill, items=items)
```

### 2.5 Bill Print Template (`bill_print_template.html`)

Create `templates/bill_print_template.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Bill {{ bill[1] }}</title>
  <style>
    @media print { .no-print { display: none; } }
    body { font-family: Arial, sans-serif; max-width: 400px; margin: 0 auto; padding: 16px; }
    h2 { text-align: center; margin-bottom: 4px; }
    .divider { border-top: 1px dashed #333; margin: 8px 0; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    td, th { padding: 4px 2px; text-align: left; }
    th { border-bottom: 1px solid #333; }
    .right { text-align: right; }
    .total-row { font-weight: bold; font-size: 15px; }
  </style>
</head>
<body>
  <h2>{{ bill[10] }}</h2>           {# shop_name #}
  <p style="text-align:center; font-size:12px;">{{ bill[11] }}<br>📞 {{ bill[12] }}</p>
  <div class="divider"></div>
  <p>Bill No: <strong>{{ bill[1] }}</strong><br>
     Date: {{ bill[15].strftime('%d %b %Y %I:%M %p') }}<br>
     Customer: {{ bill[3] }}
     {% if bill[4] %} | 📞 {{ bill[4] }}{% endif %}
  </p>
  <div class="divider"></div>
  <table>
    <thead><tr><th>Item</th><th>Qty</th><th>Rate</th><th class="right">Amount</th></tr></thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td>{{ item[2] }}</td>
        <td>{{ item[3] }} {{ item[4] }}</td>
        <td>₹{{ item[5] }}</td>
        <td class="right">₹{{ item[6] }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <div class="divider"></div>
  <table>
    <tr><td>Subtotal</td><td class="right">₹{{ bill[5] }}</td></tr>
    {% if bill[6] > 0 %}<tr><td>Discount</td><td class="right">- ₹{{ bill[6] }}</td></tr>{% endif %}
    {% if bill[7] > 0 %}<tr><td>GST ({{ bill[7] }}%)</td><td class="right">₹{{ bill[8] }}</td></tr>{% endif %}
    <tr class="total-row"><td>TOTAL</td><td class="right">₹{{ bill[9] }}</td></tr>
  </table>
  <div class="divider"></div>
  <p style="text-align:center; font-size:12px;">
    Payment: {{ bill[10] | upper }}<br>Thank you for shopping! 🙏
  </p>
  <div class="no-print" style="text-align:center; margin-top:16px;">
    <button onclick="window.print()">🖨️ Print / Save PDF</button>
  </div>
</body>
</html>
```

**How PDF works:** The shopkeeper clicks "Print", selects "Save as PDF" in the browser print dialog. Zero library cost.

### 2.6 Bill History Route

```python
@app.route('/billing/history')
@login_required
def bill_history():
    shop_id = session.get('user_id')
    page    = int(request.args.get('page', 1))
    limit   = 20
    offset  = (page - 1) * limit

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, bill_number, customer_name, total, payment_method, created_at
        FROM bills WHERE shop_id = %s
        ORDER BY created_at DESC LIMIT %s OFFSET %s
    """, (shop_id, limit, offset))
    bills = cur.fetchall()
    cur.close(); conn.close()
    return render_template('bill_history_template.html', bills=bills, page=page)
```

### 2.7 Wire Billing into Voice Commands

In your existing `process_text_command()` function, add this detection block **before** the sale logic:

```python
billing_keywords = ['bill banao', 'bill do', 'receipt do', 'bill bana do', 'invoice']
if any(kw in text.lower() for kw in billing_keywords):
    # Extract items from the command (reuse existing multi-product parser)
    items_parsed = parse_multiple_products(text)
    if items_parsed:
        bill_items_payload = []
        for qty, product_key, unit in items_parsed:
            product = current_products.get(product_key, {})
            bill_items_payload.append({
                'product': product_key,
                'qty': qty,
                'unit': unit,
                'price': product.get('price', 0)
            })
        return {
            'action': 'bill_ready',
            'items': bill_items_payload,
            'message': f'📄 Bill ready with {len(bill_items_payload)} items. Confirm?',
            'pending_bill': True
        }
```

---

## 3. Location-Based Analytics

### Overview

Uses **PostGIS** (available free on Neon via extension) for spatial queries. No external paid API required. The analytics show: nearby shops, low-stock comparison, and sales heatmaps.

### 3.1 Enable PostGIS on Neon

Run in Neon SQL console:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

-- Add geometry column to shops
ALTER TABLE shops ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);

-- Update geom from existing lat/lng
UPDATE shops
SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Auto-update geom on insert/update
CREATE OR REPLACE FUNCTION update_shop_geom()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
    NEW.geom = ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER shops_geom_trigger
BEFORE INSERT OR UPDATE ON shops
FOR EACH ROW EXECUTE FUNCTION update_shop_geom();
```

### 3.2 Analytics Helper Functions

Add to `app.py`:

```python
def get_nearby_shops(shop_id: int, radius_km: float = 2.0) -> list:
    """Find all shops within radius_km of the given shop."""
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT s2.id, s2.shop_name, s2.owner_name,
               ROUND(ST_Distance(
                   s1.geom::geography,
                   s2.geom::geography
               ) / 1000.0, 2) AS distance_km
        FROM shops s1
        JOIN shops s2 ON s1.id != s2.id
        WHERE s1.id = %s
          AND s2.geom IS NOT NULL
          AND ST_DWithin(
              s1.geom::geography,
              s2.geom::geography,
              %s * 1000      -- convert km to metres
          )
        ORDER BY distance_km
    """, (shop_id, radius_km))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{'id': r[0], 'shop_name': r[1], 'owner': r[2], 'distance_km': r[3]} for r in rows]

def get_product_sales_trend(shop_id: int, days: int = 30) -> list:
    """Daily sales totals for the past N days."""
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT DATE(b.created_at) AS sale_date,
               SUM(b.total)       AS daily_total,
               COUNT(b.id)        AS bill_count
        FROM bills b
        WHERE b.shop_id = %s
          AND b.created_at >= NOW() - INTERVAL '%s days'
        GROUP BY sale_date
        ORDER BY sale_date
    """, (shop_id, days))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{'date': str(r[0]), 'total': float(r[1]), 'bills': r[2]} for r in rows]

def get_top_selling_products(shop_id: int, limit: int = 10) -> list:
    """Top products by revenue for the current month."""
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT bi.product_name,
               SUM(bi.quantity)   AS total_qty,
               SUM(bi.line_total) AS total_revenue
        FROM bill_items bi
        JOIN bills b ON bi.bill_id = b.id
        WHERE b.shop_id = %s
          AND DATE_TRUNC('month', b.created_at) = DATE_TRUNC('month', NOW())
        GROUP BY bi.product_name
        ORDER BY total_revenue DESC
        LIMIT %s
    """, (shop_id, limit))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{'product': r[0], 'qty': float(r[1]), 'revenue': float(r[2])} for r in rows]
```

### 3.3 Analytics API Routes

```python
@app.route('/analytics/dashboard')
@login_required
def analytics_dashboard():
    shop_id = session.get('user_id')
    days    = int(request.args.get('days', 30))
    return render_template('analytics_template.html',
        nearby_shops   = get_nearby_shops(shop_id),
        sales_trend    = get_product_sales_trend(shop_id, days),
        top_products   = get_top_selling_products(shop_id),
        days           = days
    )

@app.route('/analytics/api/sales')
@login_required
def api_sales():
    shop_id = session.get('user_id')
    days    = int(request.args.get('days', 30))
    return jsonify({
        'trend':    get_product_sales_trend(shop_id, days),
        'top':      get_top_selling_products(shop_id),
        'nearby':   get_nearby_shops(shop_id),
    })
```

### 3.4 Analytics Frontend — Map + Charts

Create `templates/analytics_template.html`. The map uses **Leaflet.js** (100% free and open-source):

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Analytics — QuickStock</title>
  <!-- Leaflet CSS (free, no API key) -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <!-- Chart.js (free) -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; padding: 16px; background: #f5f5f5; }
    #map { height: 300px; border-radius: 8px; margin-bottom: 24px; }
    .card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); }
    h2 { font-size: 16px; color: #333; margin: 0 0 12px; }
  </style>
</head>
<body>
  <h1 style="font-size:20px; margin-bottom:16px;">📊 My Shop Analytics</h1>

  <!-- Map of nearby shops -->
  <div class="card">
    <h2>📍 Nearby Shops (2 km radius)</h2>
    <div id="map"></div>
  </div>

  <!-- Sales trend chart -->
  <div class="card">
    <h2>📈 Daily Sales (Last {{ days }} days)</h2>
    <canvas id="salesChart" height="200"></canvas>
  </div>

  <!-- Top products chart -->
  <div class="card">
    <h2>🏆 Top Products This Month</h2>
    <canvas id="productsChart" height="200"></canvas>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    // --- Map ---
    const map = L.map('map').setView([20.5937, 78.9629], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    // Add markers for nearby shops from Jinja2 data
    const nearbyShops = {{ nearby_shops | tojson }};
    nearbyShops.forEach(shop => {
      if (shop.latitude && shop.longitude) {
        L.marker([shop.latitude, shop.longitude])
          .addTo(map)
          .bindPopup(`<b>${shop.shop_name}</b><br>${shop.distance_km} km away`);
      }
    });

    // Try to centre map on user's position
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(pos => {
        map.setView([pos.coords.latitude, pos.coords.longitude], 14);
        L.circle([pos.coords.latitude, pos.coords.longitude], { radius: 2000, color: '#4CAF50', fillOpacity: 0.1 }).addTo(map);
      });
    }

    // --- Sales Trend Chart ---
    const salesData = {{ sales_trend | tojson }};
    new Chart(document.getElementById('salesChart'), {
      type: 'line',
      data: {
        labels: salesData.map(d => d.date),
        datasets: [{
          label: 'Daily Sales (₹)',
          data: salesData.map(d => d.total),
          borderColor: '#4CAF50',
          backgroundColor: 'rgba(76,175,80,0.1)',
          tension: 0.4,
          fill: true
        }]
      },
      options: { responsive: true, plugins: { legend: { display: false } } }
    });

    // --- Top Products Chart ---
    const topData = {{ top_products | tojson }};
    new Chart(document.getElementById('productsChart'), {
      type: 'bar',
      data: {
        labels: topData.map(d => d.product),
        datasets: [{
          label: 'Revenue (₹)',
          data: topData.map(d => d.revenue),
          backgroundColor: '#2196F3'
        }]
      },
      options: { responsive: true, plugins: { legend: { display: false } } }
    });
  </script>
</body>
</html>
```

**Note:** OpenStreetMap tiles via Leaflet are completely free with no API key required.

---

## 4. WhatsApp Integration

### Overview

Uses the **WhatsApp Cloud API (Meta)** free tier — 1,000 free service conversations per month per phone number. This covers most small shops easily. We use it for two flows:
1. **Low-stock alerts:** Automatically notify the shopkeeper and optionally the wholesaler when stock drops below threshold
2. **Restock order request:** Shopkeeper can trigger a WhatsApp message to the wholesaler directly from the app

### 4.1 Setup Meta WhatsApp Cloud API (Free)

1. Go to [https://developers.facebook.com](https://developers.facebook.com) → Create App → Business
2. Add **WhatsApp** product to your app
3. Go to **WhatsApp → API Setup** → Copy:
   - `Phone Number ID`
   - `Access Token` (temporary or permanent)
   - `WABA ID` (WhatsApp Business Account ID)
4. Add a test number (your own number) under **To** in the API setup
5. Add to `.env`:
   ```env
   WHATSAPP_TOKEN=your_access_token
   WHATSAPP_PHONE_ID=your_phone_number_id
   WHATSAPP_VERIFY_TOKEN=quickstock_webhook_2026
   ```

> **Free tier:** 1,000 conversations/month. For a small shop sending ~30 alerts/month, this is more than enough.

### 4.2 WhatsApp Helper

Add to `app.py`:

```python
WHATSAPP_API_URL = "https://graph.facebook.com/v19.0/{phone_id}/messages"

def send_whatsapp_message(to_number: str, message: str) -> bool:
    """Send a free-form WhatsApp message (only works within 24hr window)."""
    phone_id = os.getenv('WHATSAPP_PHONE_ID')
    token    = os.getenv('WHATSAPP_TOKEN')
    url      = WHATSAPP_API_URL.format(phone_id=phone_id)
    payload  = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message}
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"WhatsApp send failed: {e}")
        return False

def send_whatsapp_template(to_number: str, template_name: str, params: list) -> bool:
    """Send an approved WhatsApp template message (works anytime)."""
    phone_id = os.getenv('WHATSAPP_PHONE_ID')
    token    = os.getenv('WHATSAPP_TOKEN')
    url      = WHATSAPP_API_URL.format(phone_id=phone_id)
    components = [{
        "type": "body",
        "parameters": [{"type": "text", "text": p} for p in params]
    }]
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
            "components": components
        }
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"WhatsApp template send failed: {e}")
        return False
```

### 4.3 Automatic Low-Stock Alert

Modify `update_product_stock_in_db()` to trigger WhatsApp alert when stock crosses threshold:

```python
def update_product_stock_in_db(product_name, new_stock, new_threshold=None, new_price=None):
    # ... existing update code ...

    # After DB commit, check threshold and alert
    try:
        conn2 = get_db_connection()
        cur2  = conn2.cursor()
        cur2.execute("""
            SELECT p.threshold, s.whatsapp_number, s.shop_name, s.id
            FROM products p
            JOIN shops s ON p.shop_id = s.id     -- assumes products have shop_id FK
            WHERE p.name = %s
        """, (product_name,))
        row = cur2.fetchone()
        cur2.close(); conn2.close()

        if row:
            threshold, wa_number, shop_name, shop_id = row
            if new_stock is not None and threshold and new_stock <= threshold and wa_number:
                msg = (
                    f"⚠️ *Low Stock Alert — {shop_name}*\n\n"
                    f"Product: *{product_name}*\n"
                    f"Current Stock: {new_stock}\n"
                    f"Threshold: {threshold}\n\n"
                    f"Please restock soon! Reply to this message or visit QuickStock."
                )
                send_whatsapp_message(wa_number, msg)
    except Exception as e:
        print(f"Low stock WhatsApp alert failed: {e}")
```

> **Note:** Add `shop_id` column to the `products` table to link products to a shop:
> ```sql
> ALTER TABLE products ADD COLUMN IF NOT EXISTS shop_id INT REFERENCES shops(id);
> UPDATE products SET shop_id = (SELECT id FROM shops WHERE role = 'shop' LIMIT 1);
> ```

### 4.4 Wholesaler Suggestion on Low Stock

When stock drops below threshold, also message the wholesaler (if linked):

```python
def notify_wholesaler_on_low_stock(shop_id: int, product_name: str, current_stock: float, threshold: float):
    """Send auto-suggestion to wholesaler when shop stock is low."""
    conn = get_db_connection()
    cur  = conn.cursor()
    # Find the wholesaler linked to this shop (from wholesaler_shop_links table — see Section 5)
    cur.execute("""
        SELECT w.whatsapp_number, w.shop_name AS wholesaler_name, s.shop_name AS shopkeeper_name
        FROM wholesaler_shop_links wsl
        JOIN shops w ON wsl.wholesaler_id = w.id
        JOIN shops s ON wsl.shop_id = s.id
        WHERE wsl.shop_id = %s AND w.role = 'wholesaler'
        LIMIT 1
    """, (shop_id,))
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        return

    wholesaler_wa, wholesaler_name, shopkeeper_name = row
    suggested_qty = max(10, int(threshold * 3))   # Suggest 3x threshold as reorder qty
    msg = (
        f"📦 *Restock Suggestion — QuickStock*\n\n"
        f"Shop: *{shopkeeper_name}*\n"
        f"Product running low: *{product_name}*\n"
        f"Current stock: {current_stock} | Threshold: {threshold}\n\n"
        f"Suggested reorder quantity: *{suggested_qty} units*\n\n"
        f"Reply YES to confirm delivery or call the shop directly."
    )
    send_whatsapp_message(wholesaler_wa, msg)
```

Call `notify_wholesaler_on_low_stock()` after the shopkeeper alert in `update_product_stock_in_db()`.

### 4.5 Manual Restock Request Route

Allow the shopkeeper to send a manual order request to wholesaler:

```python
@app.route('/whatsapp/request-restock', methods=['POST'])
@login_required
def request_restock_whatsapp():
    data         = request.get_json()
    product_name = data.get('product')
    quantity     = data.get('quantity')
    shop_id      = session.get('user_id')
    shop_name    = session.get('shop')

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT w.whatsapp_number
        FROM wholesaler_shop_links wsl
        JOIN shops w ON wsl.wholesaler_id = w.id
        WHERE wsl.shop_id = %s LIMIT 1
    """, (shop_id,))
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        return jsonify({'error': 'No wholesaler linked to your shop'}), 404

    wholesaler_wa = row[0]
    msg = (
        f"🛒 *Order Request from {shop_name}*\n\n"
        f"Product: *{product_name}*\n"
        f"Requested Quantity: *{quantity}*\n\n"
        f"Please confirm delivery schedule."
    )
    success = send_whatsapp_message(wholesaler_wa, msg)
    return jsonify({'success': success, 'message': 'Request sent via WhatsApp' if success else 'Send failed'})
```

### 4.6 WhatsApp Webhook (Receive Replies)

Add this route to receive wholesaler's YES/NO replies:

```python
@app.route('/webhook/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    # Verification (GET)
    if request.method == 'GET':
        token     = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        if token == os.getenv('WHATSAPP_VERIFY_TOKEN'):
            return challenge, 200
        return 'Unauthorized', 403

    # Incoming message (POST)
    data = request.get_json()
    try:
        entry   = data['entry'][0]
        changes = entry['changes'][0]['value']
        msgs    = changes.get('messages', [])
        for msg in msgs:
            from_number = msg['from']
            body        = msg.get('text', {}).get('body', '').strip().upper()
            if body in ['YES', 'CONFIRM', 'HAA', 'OK']:
                # Wholesaler confirmed — notify shopkeeper
                # (Look up shop linked to this wholesaler number and send confirmation)
                reply = "✅ Delivery confirmed! We'll contact you shortly."
                send_whatsapp_message(from_number, reply)
            elif body in ['NO', 'NAA', 'CANCEL']:
                send_whatsapp_message(from_number, "❌ Request cancelled.")
    except Exception as e:
        print(f"Webhook error: {e}")
    return 'OK', 200
```

Register the webhook URL in Meta Developer Console → WhatsApp → Configuration → Webhook.

---

## 5. Wholesaler Dashboard

### 5.1 Database — Wholesaler Tables

```sql
-- Link wholesaler accounts to shops they serve
CREATE TABLE IF NOT EXISTS wholesaler_shop_links (
    id            SERIAL PRIMARY KEY,
    wholesaler_id INT REFERENCES shops(id),
    shop_id       INT REFERENCES shops(id),
    linked_at     TIMESTAMP DEFAULT NOW(),
    UNIQUE(wholesaler_id, shop_id)
);

-- Delivery/order tracking
CREATE TABLE IF NOT EXISTS wholesale_orders (
    id              SERIAL PRIMARY KEY,
    wholesaler_id   INT REFERENCES shops(id),
    shop_id         INT REFERENCES shops(id),
    product_name    VARCHAR(100) NOT NULL,
    quantity        NUMERIC(10,3) NOT NULL,
    unit            VARCHAR(20),
    price_per_unit  NUMERIC(10,2),
    total_amount    NUMERIC(10,2),
    status          VARCHAR(20) DEFAULT 'pending',  -- 'pending' | 'confirmed' | 'delivered' | 'cancelled'
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    delivered_at    TIMESTAMP
);
```

### 5.2 Wholesaler Registration

Wholesalers register the same way as shopkeepers, but with `role = 'wholesaler'`. Add a toggle to the registration form:

```html
<!-- In register_template.html -->
<select name="role">
  <option value="shop">I'm a Shopkeeper</option>
  <option value="wholesaler">I'm a Wholesaler/Supplier</option>
</select>
```

Update `app.py` register route to accept `role` from form.

### 5.3 Wholesaler Dashboard Route

```python
@app.route('/wholesaler/dashboard')
@login_required
def wholesaler_dashboard():
    if session.get('role') != 'wholesaler':
        return redirect(url_for('home'))

    wholesaler_id = session.get('user_id')
    conn = get_db_connection()
    cur  = conn.cursor()

    # Linked shops
    cur.execute("""
        SELECT s.id, s.shop_name, s.city, s.phone,
               COUNT(DISTINCT bi.id) AS total_orders
        FROM wholesaler_shop_links wsl
        JOIN shops s ON wsl.shop_id = s.id
        LEFT JOIN wholesale_orders wo ON wo.shop_id = s.id AND wo.wholesaler_id = %s
        LEFT JOIN bill_items bi ON bi.product_name IS NOT NULL
        WHERE wsl.wholesaler_id = %s
        GROUP BY s.id
    """, (wholesaler_id, wholesaler_id))
    linked_shops = cur.fetchall()

    # Pending orders
    cur.execute("""
        SELECT wo.id, s.shop_name, wo.product_name, wo.quantity, wo.unit,
               wo.total_amount, wo.status, wo.created_at
        FROM wholesale_orders wo
        JOIN shops s ON wo.shop_id = s.id
        WHERE wo.wholesaler_id = %s AND wo.status = 'pending'
        ORDER BY wo.created_at DESC
    """, (wholesaler_id,))
    pending_orders = cur.fetchall()

    # Nearby shops that don't have a wholesaler (potential customers)
    cur.execute("""
        SELECT s.id, s.shop_name, s.city,
               ROUND(ST_Distance(
                   (SELECT geom FROM shops WHERE id = %s)::geography,
                   s.geom::geography
               ) / 1000.0, 1) AS distance_km
        FROM shops s
        WHERE s.role = 'shop'
          AND s.geom IS NOT NULL
          AND s.id NOT IN (
              SELECT shop_id FROM wholesaler_shop_links WHERE wholesaler_id = %s
          )
          AND ST_DWithin(
              (SELECT geom FROM shops WHERE id = %s)::geography,
              s.geom::geography,
              10000
          )
        ORDER BY distance_km
        LIMIT 20
    """, (wholesaler_id, wholesaler_id, wholesaler_id))
    nearby_unlinked = cur.fetchall()

    cur.close(); conn.close()
    return render_template('wholesaler_dashboard_template.html',
        linked_shops    = linked_shops,
        pending_orders  = pending_orders,
        nearby_unlinked = nearby_unlinked
    )
```

### 5.4 Order Management Routes

```python
@app.route('/wholesaler/order/<int:order_id>/confirm', methods=['POST'])
@login_required
def confirm_order(order_id):
    if session.get('role') != 'wholesaler':
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE wholesale_orders SET status = 'confirmed'
        WHERE id = %s AND wholesaler_id = %s
        RETURNING shop_id, product_name, quantity
    """, (order_id, session.get('user_id')))
    row = cur.fetchone()
    conn.commit()
    cur.close(); conn.close()

    if row:
        # Notify shopkeeper via WhatsApp
        shop_id, product, qty = row
        conn2 = get_db_connection()
        cur2  = conn2.cursor()
        cur2.execute("SELECT whatsapp_number, shop_name FROM shops WHERE id = %s", (shop_id,))
        shop  = cur2.fetchone()
        cur2.close(); conn2.close()
        if shop and shop[0]:
            msg = (
                f"✅ *Order Confirmed — QuickStock*\n\n"
                f"Your order for *{qty} {product}* has been confirmed by your wholesaler.\n"
                f"Delivery will be arranged shortly."
            )
            send_whatsapp_message(shop[0], msg)

    return jsonify({'success': True})

@app.route('/wholesaler/link-shop', methods=['POST'])
@login_required
def link_shop():
    if session.get('role') != 'wholesaler':
        return jsonify({'error': 'Unauthorized'}), 403

    shop_id       = request.get_json().get('shop_id')
    wholesaler_id = session.get('user_id')
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO wholesaler_shop_links (wholesaler_id, shop_id)
        VALUES (%s, %s) ON CONFLICT DO NOTHING
    """, (wholesaler_id, shop_id))
    conn.commit()
    cur.close(); conn.close()
    return jsonify({'success': True, 'message': 'Shop linked successfully'})
```

### 5.5 Wholesaler Dashboard Template

Create `templates/wholesaler_dashboard_template.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Wholesaler Dashboard — QuickStock</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; padding: 16px; background: #f5f5f5; }
    .card { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 16px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08); }
    h2 { font-size: 16px; color: #333; border-bottom: 1px solid #eee; padding-bottom: 8px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    td, th { padding: 8px 6px; text-align: left; border-bottom: 1px solid #f0f0f0; }
    th { background: #f8f8f8; font-weight: 600; }
    .badge-pending  { background: #FFF3E0; color: #E65100; padding: 2px 8px; border-radius: 12px; font-size:12px; }
    .badge-confirmed{ background: #E8F5E9; color: #2E7D32; padding: 2px 8px; border-radius: 12px; font-size:12px; }
    .btn { padding: 6px 14px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; }
    .btn-green { background: #4CAF50; color: #fff; }
    .btn-blue  { background: #2196F3; color: #fff; }
  </style>
</head>
<body>
  <h1 style="font-size:20px; margin-bottom:16px;">🏭 Wholesaler Dashboard</h1>

  <!-- Pending Orders -->
  <div class="card">
    <h2>📦 Pending Orders ({{ pending_orders | length }})</h2>
    {% if pending_orders %}
    <table>
      <thead><tr><th>Shop</th><th>Product</th><th>Qty</th><th>Amount</th><th>Date</th><th>Action</th></tr></thead>
      <tbody>
        {% for o in pending_orders %}
        <tr>
          <td>{{ o[1] }}</td>
          <td>{{ o[2] }}</td>
          <td>{{ o[3] }} {{ o[4] }}</td>
          <td>₹{{ o[5] or '—' }}</td>
          <td>{{ o[7].strftime('%d %b') }}</td>
          <td>
            <button class="btn btn-green" onclick="confirmOrder({{ o[0] }})">✅ Confirm</button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p style="color:#888;">No pending orders.</p>
    {% endif %}
  </div>

  <!-- Linked Shops -->
  <div class="card">
    <h2>🏪 My Shops ({{ linked_shops | length }})</h2>
    <table>
      <thead><tr><th>Shop</th><th>City</th><th>Phone</th></tr></thead>
      <tbody>
        {% for s in linked_shops %}
        <tr><td>{{ s[1] }}</td><td>{{ s[2] }}</td><td>{{ s[3] }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Nearby Unlinked Shops (Growth Opportunities) -->
  <div class="card">
    <h2>🔍 Nearby Shops (Not Yet Your Customers)</h2>
    <table>
      <thead><tr><th>Shop</th><th>City</th><th>Distance</th><th>Action</th></tr></thead>
      <tbody>
        {% for s in nearby_unlinked %}
        <tr>
          <td>{{ s[1] }}</td>
          <td>{{ s[2] }}</td>
          <td>{{ s[3] }} km</td>
          <td><button class="btn btn-blue" onclick="linkShop({{ s[0] }})">Link</button></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <script>
    async function confirmOrder(orderId) {
      const res = await fetch(`/wholesaler/order/${orderId}/confirm`, { method: 'POST' });
      const data = await res.json();
      if (data.success) { alert('Order confirmed! Shopkeeper notified via WhatsApp.'); location.reload(); }
    }

    async function linkShop(shopId) {
      const res = await fetch('/wholesaler/link-shop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ shop_id: shopId })
      });
      const data = await res.json();
      if (data.success) { alert('Shop linked!'); location.reload(); }
    }
  </script>
</body>
</html>
```

---

## 6. Full Database Schema

Here is the complete set of SQL statements to run once on your Neon instance, in order:

```sql
-- 1. Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Shops (replaces USERS dict)
CREATE TABLE IF NOT EXISTS shops (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    shop_name VARCHAR(100) NOT NULL,
    owner_name VARCHAR(100),
    phone VARCHAR(15) UNIQUE NOT NULL,
    role VARCHAR(20) DEFAULT 'shop',
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    address TEXT,
    city VARCHAR(50),
    state VARCHAR(50),
    pin_code VARCHAR(10),
    whatsapp_number VARCHAR(15),
    is_verified BOOLEAN DEFAULT FALSE,
    otp_secret TEXT,
    otp_expiry TIMESTAMP,
    geom geometry(Point, 4326),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. Migrate existing products: add shop_id FK
ALTER TABLE products ADD COLUMN IF NOT EXISTS shop_id INT REFERENCES shops(id);

-- 4. OTP log
CREATE TABLE IF NOT EXISTS otp_log (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(15) NOT NULL,
    otp_code VARCHAR(6) NOT NULL,
    purpose VARCHAR(30),
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    used BOOLEAN DEFAULT FALSE
);

-- 5. Bills
CREATE TABLE IF NOT EXISTS bills (
    id SERIAL PRIMARY KEY,
    bill_number VARCHAR(30) UNIQUE NOT NULL,
    shop_id INT REFERENCES shops(id),
    customer_name VARCHAR(100),
    customer_phone VARCHAR(15),
    subtotal NUMERIC(10,2) DEFAULT 0,
    discount NUMERIC(10,2) DEFAULT 0,
    gst_percent NUMERIC(5,2) DEFAULT 0,
    gst_amount NUMERIC(10,2) DEFAULT 0,
    total NUMERIC(10,2) DEFAULT 0,
    payment_method VARCHAR(20) DEFAULT 'cash',
    payment_status VARCHAR(20) DEFAULT 'paid',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 6. Bill items
CREATE TABLE IF NOT EXISTS bill_items (
    id SERIAL PRIMARY KEY,
    bill_id INT REFERENCES bills(id) ON DELETE CASCADE,
    product_name VARCHAR(100) NOT NULL,
    quantity NUMERIC(10,3) NOT NULL,
    unit VARCHAR(20),
    price_per_unit NUMERIC(10,2) NOT NULL,
    line_total NUMERIC(10,2) NOT NULL
);

-- 7. Wholesaler links
CREATE TABLE IF NOT EXISTS wholesaler_shop_links (
    id SERIAL PRIMARY KEY,
    wholesaler_id INT REFERENCES shops(id),
    shop_id INT REFERENCES shops(id),
    linked_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(wholesaler_id, shop_id)
);

-- 8. Wholesale orders
CREATE TABLE IF NOT EXISTS wholesale_orders (
    id SERIAL PRIMARY KEY,
    wholesaler_id INT REFERENCES shops(id),
    shop_id INT REFERENCES shops(id),
    product_name VARCHAR(100) NOT NULL,
    quantity NUMERIC(10,3) NOT NULL,
    unit VARCHAR(20),
    price_per_unit NUMERIC(10,2),
    total_amount NUMERIC(10,2),
    status VARCHAR(20) DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    delivered_at TIMESTAMP
);

-- 9. Indexes
CREATE INDEX IF NOT EXISTS idx_bills_created_at   ON bills(created_at);
CREATE INDEX IF NOT EXISTS idx_bills_shop_id       ON bills(shop_id);
CREATE INDEX IF NOT EXISTS idx_shops_geom          ON shops USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_products_shop_id    ON products(shop_id);

-- 10. Geometry trigger
CREATE OR REPLACE FUNCTION update_shop_geom()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
    NEW.geom = ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER shops_geom_trigger
BEFORE INSERT OR UPDATE ON shops
FOR EACH ROW EXECUTE FUNCTION update_shop_geom();
```

---

## 7. Deployment & Scaling Notes

### New `.env` Variables to Add

```env
# Existing
DATABASE_URL=...
FLASK_SECRET_KEY=...

# New — OTP
FAST2SMS_API_KEY=your_key

# New — WhatsApp
WHATSAPP_TOKEN=your_meta_access_token
WHATSAPP_PHONE_ID=your_phone_number_id
WHATSAPP_VERIFY_TOKEN=quickstock_webhook_2026
```

### New pip Dependencies

Add to `requirements.txt`:

```
requests          # already likely installed; needed for Fast2SMS + WhatsApp HTTP calls
psycopg2-binary   # already installed
python-dotenv     # already installed
```

No new paid libraries needed.

### Implementation Order (Recommended)

| Step | Task | Time Estimate |
|------|------|---------------|
| 0 | Rotate DB credentials | 5 min |
| 1 | Run full schema SQL on Neon | 15 min |
| 2 | Shop registration + DB login | 2-3 hrs |
| 3 | OTP login (Fast2SMS) | 1-2 hrs |
| 4 | Location capture on register | 1 hr |
| 5 | Billing system + print template | 3-4 hrs |
| 6 | Analytics routes + Leaflet map | 3-4 hrs |
| 7 | WhatsApp low-stock alerts | 2-3 hrs |
| 8 | Wholesaler dashboard | 3-4 hrs |
| 9 | Wire voice commands → billing | 1-2 hrs |

### Scaling to 10,000+ Shops

- Neon PostgreSQL auto-scales on the free tier up to 0.5 CPU / 1 GB RAM; upgrade to Neon Pro ($19/month) for 10,000+ active shops
- PostGIS spatial indexes handle 10,000+ shop geolocation queries in < 50ms
- WhatsApp free tier (1,000 conversations/month) is per phone number; register a dedicated business number for production
- Fast2SMS: upgrade to paid plan (~₹0.20/SMS) for >1,000 OTPs/month; budget ₹200/month for 1,000 shops

---

*Generated for QuickStock v1.0 — Flask + Neon PostgreSQL + WhatsApp Cloud API + Fast2SMS*
