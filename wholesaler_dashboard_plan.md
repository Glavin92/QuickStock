# 🏭 Wholesaler Dashboard — Design & Implementation Plan

## Overview

The Wholesaler Dashboard is a **separate, role-specific view** served when `session['role'] == 'wholesaler'`. Unlike the Shopkeeper dashboard (which is voice-first and inventory-focused), the Wholesaler dashboard is **order-management and business-intelligence focused** — wholesalers don't talk to Vosk, they manage supply, respond to orders, and track revenue across multiple shopkeepers.

The existing `home()` route will be split by role:

```python
@app.route('/')
@login_required
def home():
    if session.get('role') == 'wholesaler':
        return render_template('wholesaler_dashboard.html')
    return render_template('dashboard_template.html')   # shopkeeper
```

---

## Dashboard Layout Blueprint

```
┌────────────────────────────────────────────────────────────────────┐
│  🏭 QuickStock Wholesaler          [👤 ABC Wholesale]  [Logout]     │
├────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────┐  │
│  │ 📦 Orders    │ │ 🏪 My Shops  │ │ 📊 Analytics │ │ 💬 Chat  │  │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────┘  │
├────────────────────────────────────────────────────────────────────┤
│                       [TAB CONTENT AREA]                            │
└────────────────────────────────────────────────────────────────────┘
```

The dashboard has **4 tabs**, each serving a distinct purpose. No voice input UI. No transaction queue.

---

## Tab 1 — 📦 Orders (Default Tab)

This is the most important tab. It shows **incoming order suggestions** from shopkeepers (the `order_suggestion` messages sent automatically when stock drops below threshold), plus the wholesaler's ability to manually create dispatch orders.

### Layout

```
┌────────────────────────────────────────────────────────┐
│  📦 Incoming Order Requests                [Filter ▼]   │
│  ─────────────────────────────────────────────────────  │
│  🔴 [NEW]  Shrey's Shop — Parle-G                        │
│            Current: 18 pkt | Threshold: 20 | Suggest: 60│
│            📅 Today 3:45 PM                              │
│            [✅ Confirm Order]  [✏️ Edit Qty]  [❌ Reject] │
│  ─────────────────────────────────────────────────────  │
│  🟡 [SEEN] Ramesh Kirana — Rice                          │
│            Current: 25 kg  | Threshold: 30 | Suggest: 90│
│            📅 Today 1:20 PM                              │
│            [✅ Confirm Order]  [✏️ Edit Qty]  [❌ Reject] │
│  ─────────────────────────────────────────────────────  │
│  🟢 [DONE] Thane Shop — Coke                             │
│            Dispatched: 120 btl  📅 Yesterday 5:00 PM    │
└────────────────────────────────────────────────────────┘
```

### New Database Table — `orders`

```sql
CREATE TABLE IF NOT EXISTS orders (
    id                  SERIAL PRIMARY KEY,
    conversation_id     INTEGER REFERENCES conversations(id),
    message_id          INTEGER REFERENCES messages(id),    -- the order_suggestion message
    shop_user_id        INTEGER NOT NULL REFERENCES users(id),
    wholesaler_user_id  INTEGER NOT NULL REFERENCES users(id),
    product_name        VARCHAR(100) NOT NULL,
    requested_qty       FLOAT NOT NULL,
    confirmed_qty       FLOAT,
    unit                VARCHAR(30),
    status              VARCHAR(20) DEFAULT 'pending'
                            CHECK (status IN ('pending','confirmed','dispatched','rejected')),
    wholesaler_note     TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_wholesaler ON orders(wholesaler_user_id);
CREATE INDEX IF NOT EXISTS idx_orders_shop       ON orders(shop_user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status     ON orders(status);
```

### Backend Endpoints

```python
# GET /api/wholesaler/orders?status=pending
@app.route('/api/wholesaler/orders', methods=['GET'])
@login_required
def api_wholesaler_orders():
    """Returns all orders for the logged-in wholesaler, optionally filtered by status."""
    if session.get('role') != 'wholesaler':
        return jsonify({'error': 'Forbidden'}), 403

    wholesaler_id = session.get('user_id')
    status_filter = request.args.get('status', None)   # pending | confirmed | dispatched | rejected

    conn = get_db_connection()
    cur  = conn.cursor()
    query = """
        SELECT o.id, o.product_name, o.requested_qty, o.confirmed_qty,
               o.unit, o.status, o.wholesaler_note, o.created_at,
               u.display_name AS shop_name, u.username AS shop_username
        FROM orders o
        JOIN users u ON u.id = o.shop_user_id
        WHERE o.wholesaler_user_id = %s
    """
    params = [wholesaler_id]
    if status_filter:
        query += " AND o.status = %s"
        params.append(status_filter)
    query += " ORDER BY o.created_at DESC"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify({'orders': [
        {
            'id': r[0], 'product_name': r[1], 'requested_qty': r[2],
            'confirmed_qty': r[3], 'unit': r[4], 'status': r[5],
            'note': r[6], 'created_at': str(r[7]),
            'shop_name': r[8] or r[9],
        }
        for r in rows
    ]})


# POST /api/wholesaler/orders/<id>/action
@app.route('/api/wholesaler/orders/<int:order_id>/action', methods=['POST'])
@login_required
def api_wholesaler_order_action(order_id):
    """Confirm, edit qty, dispatch, or reject an order."""
    if session.get('role') != 'wholesaler':
        return jsonify({'error': 'Forbidden'}), 403

    wholesaler_id = session.get('user_id')
    data          = request.get_json()
    action        = data.get('action')          # confirm | dispatch | reject
    confirmed_qty = data.get('confirmed_qty')
    note          = data.get('note', '')

    valid_actions = {'confirm', 'dispatch', 'reject'}
    if action not in valid_actions:
        return jsonify({'error': f'Invalid action. Must be one of {valid_actions}'}), 400

    status_map = {'confirm': 'confirmed', 'dispatch': 'dispatched', 'reject': 'rejected'}
    new_status = status_map[action]

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        """UPDATE orders
           SET status=%s, confirmed_qty=%s, wholesaler_note=%s, updated_at=NOW()
           WHERE id=%s AND wholesaler_user_id=%s
           RETURNING shop_user_id, product_name, confirmed_qty""",
        (new_status, confirmed_qty, note, order_id, wholesaler_id)
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    if not row:
        return jsonify({'error': 'Order not found or access denied'}), 404

    # Notify shopkeeper via chat if dispatch confirmed
    if action == 'dispatch' and row:
        shop_user_id = row[0]
        conv_id = get_or_create_conversation(shop_user_id, wholesaler_id)
        msg = (
            f"✅ ORDER DISPATCHED: {row[1]}\n"
            f"Quantity: {row[2]} {data.get('unit','')}\n"
            f"Note: {note or 'On the way!'}"
        )
        save_message(conv_id, wholesaler_id, msg, message_type='order_suggestion')
        socketio.emit('new_message', {
            'conversation_id': conv_id,
            'sender_id': wholesaler_id,
            'text': msg,
            'message_type': 'order_suggestion',
        }, to=f'conv_{conv_id}')

    return jsonify({'success': True, 'new_status': new_status})
```

### Auto-create order from order_suggestion message

In the existing `send_order_suggestion()` function (from the Chat guide), add this after `save_message()`:

```python
# After saving the order_suggestion message, also create an orders row
conn = get_db_connection()
cur  = conn.cursor()
cur.execute(
    """INSERT INTO orders
           (conversation_id, shop_user_id, wholesaler_user_id,
            product_name, requested_qty, unit, status)
       VALUES (%s, %s, %s, %s, %s, %s, 'pending')""",
    (conv_id, shop_user_id, wholesaler_id,
     product_name, suggested_qty, unit)
)
conn.commit()
cur.close()
conn.close()
```

### Frontend — Orders Tab JS

```javascript
// ── Orders Tab ─────────────────────────────────────────────────
let currentOrderFilter = 'pending';

async function loadOrders(status = 'pending') {
    currentOrderFilter = status;
    const res  = await fetch(`/api/wholesaler/orders?status=${status}`);
    const data = await res.json();
    renderOrders(data.orders || []);
    updateFilterButtons(status);
}

function renderOrders(orders) {
    const container = document.getElementById('orders-list');
    if (orders.length === 0) {
        container.innerHTML = `<div class="empty-state">No ${currentOrderFilter} orders</div>`;
        return;
    }
    container.innerHTML = orders.map(o => `
        <div class="order-card ${o.status}" id="order-${o.id}">
            <div class="order-header">
                <span class="order-badge ${o.status}">${o.status.toUpperCase()}</span>
                <span class="order-shop">🏪 ${escapeHtml(o.shop_name)}</span>
                <span class="order-time">${new Date(o.created_at).toLocaleString()}</span>
            </div>
            <div class="order-product">
                <strong>${escapeHtml(o.product_name)}</strong>
                — Requested: <b>${o.requested_qty} ${o.unit || ''}</b>
            </div>
            ${o.note ? `<div class="order-note">📝 ${escapeHtml(o.note)}</div>` : ''}
            ${o.status === 'pending' ? `
            <div class="order-actions">
                <input type="number" id="qty-${o.id}" value="${o.requested_qty}"
                       min="1" style="width:80px;" placeholder="Qty" />
                <button onclick="orderAction(${o.id},'confirm')" class="btn-confirm">✅ Confirm</button>
                <button onclick="orderAction(${o.id},'dispatch')" class="btn-dispatch">🚚 Dispatch</button>
                <button onclick="orderAction(${o.id},'reject')" class="btn-reject">❌ Reject</button>
            </div>` : ''}
        </div>
    `).join('');
}

async function orderAction(orderId, action) {
    const qtyInput = document.getElementById(`qty-${orderId}`);
    const qty = qtyInput ? parseFloat(qtyInput.value) : null;
    const note = action === 'reject'
        ? prompt('Reason for rejection (optional):') || ''
        : '';
    const res = await fetch(`/api/wholesaler/orders/${orderId}/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, confirmed_qty: qty, note })
    });
    const data = await res.json();
    if (data.success) {
        showToast(`Order ${action}ed successfully!`);
        loadOrders(currentOrderFilter);
        loadOrderSummaryCards();   // refresh header stats
    }
}
```

---

## Tab 2 — 🏪 My Shops

This tab shows **all shopkeepers** linked to this wholesaler, their current order count, and quick-access actions.

### Layout

```
┌──────────────────────────────────────────────────────────┐
│  🏪 Connected Shops              [+ Link New Shop]        │
│  ──────────────────────────────────────────────────────  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │ Shrey Shop │  │ Ramesh K   │  │ Thane Shop │          │
│  │ 🟢 Online  │  │ 🔴 Offline │  │ 🟢 Online  │          │
│  │ 3 orders   │  │ 1 order    │  │ 0 orders   │          │
│  │ [💬 Chat]  │  │ [💬 Chat]  │  │ [💬 Chat]  │          │
│  └────────────┘  └────────────┘  └────────────┘          │
└──────────────────────────────────────────────────────────┘
```

### New DB Table — `wholesaler_shop_links`

```sql
-- Explicit link table so a wholesaler serves multiple shops
CREATE TABLE IF NOT EXISTS wholesaler_shop_links (
    id              SERIAL PRIMARY KEY,
    wholesaler_id   INTEGER NOT NULL REFERENCES users(id),
    shop_id         INTEGER NOT NULL REFERENCES users(id),
    linked_at       TIMESTAMP DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE,
    UNIQUE(wholesaler_id, shop_id)
);
```

### Backend Endpoint

```python
@app.route('/api/wholesaler/shops', methods=['GET'])
@login_required
def api_wholesaler_shops():
    if session.get('role') != 'wholesaler':
        return jsonify({'error': 'Forbidden'}), 403

    wholesaler_id = session.get('user_id')
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT u.id, u.username, u.display_name, u.shop_name,
               (SELECT COUNT(*) FROM orders o
                WHERE o.shop_user_id = u.id
                AND o.wholesaler_user_id = %s
                AND o.status = 'pending') AS pending_orders,
               (SELECT MAX(c.last_message_at)
                FROM conversations c
                WHERE c.shop_user_id = u.id
                AND c.wholesaler_user_id = %s) AS last_active
        FROM wholesaler_shop_links wsl
        JOIN users u ON u.id = wsl.shop_id
        WHERE wsl.wholesaler_id = %s AND wsl.is_active = TRUE
    """, (wholesaler_id, wholesaler_id, wholesaler_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify({'shops': [
        {
            'id': r[0], 'username': r[1],
            'display_name': r[2] or r[1], 'shop_name': r[3],
            'pending_orders': r[4], 'last_active': str(r[5]) if r[5] else None
        }
        for r in rows
    ]})


@app.route('/api/wholesaler/shops/link', methods=['POST'])
@login_required
def api_link_shop():
    """Link a shop user to this wholesaler by username."""
    if session.get('role') != 'wholesaler':
        return jsonify({'error': 'Forbidden'}), 403

    data          = request.get_json()
    shop_username = data.get('shop_username', '').strip()
    wholesaler_id = session.get('user_id')

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT id FROM users WHERE username=%s AND role='shop' AND is_active=TRUE",
        (shop_username,)
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({'error': 'Shop not found'}), 404

    shop_id = row[0]
    cur.execute(
        """INSERT INTO wholesaler_shop_links (wholesaler_id, shop_id)
           VALUES (%s, %s) ON CONFLICT DO NOTHING""",
        (wholesaler_id, shop_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'shop_id': shop_id})
```

### Frontend — Shops Tab JS

```javascript
async function loadShops() {
    const res  = await fetch('/api/wholesaler/shops');
    const data = await res.json();
    const grid = document.getElementById('shops-grid');
    grid.innerHTML = (data.shops || []).map(s => `
        <div class="shop-card">
            <div class="shop-avatar">${(s.display_name || '?')[0].toUpperCase()}</div>
            <div class="shop-name">${escapeHtml(s.display_name)}</div>
            <div class="shop-meta">${escapeHtml(s.shop_name || '')}</div>
            <div class="shop-status ${s.last_active ? 'online' : 'offline'}">
                ${s.last_active ? '🟢 Active' : '🔴 No messages yet'}
            </div>
            ${s.pending_orders > 0
              ? `<div class="shop-orders-badge">${s.pending_orders} pending orders</div>`
              : ''}
            <div class="shop-actions">
                <button onclick="openChatWithShop(${s.id})" class="btn-chat-sm">💬 Chat</button>
                <button onclick="viewShopOrders(${s.id})" class="btn-orders-sm">📦 Orders</button>
            </div>
        </div>
    `).join('');
}

async function linkNewShop() {
    const username = prompt('Enter the shopkeeper\'s username to link:');
    if (!username) return;
    const res = await fetch('/api/wholesaler/shops/link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop_username: username.trim() })
    });
    const data = await res.json();
    if (data.success) { showToast('Shop linked!'); loadShops(); }
    else alert(data.error || 'Failed to link shop');
}

// Open chat in the Chat tab for a specific shop
function openChatWithShop(shopUserId) {
    document.querySelector('[data-tab="chat"]').click();
    // Auto-open conversation after chat tab initializes
    setTimeout(async () => {
        const res  = await fetch('/api/conversations/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ other_user_id: shopUserId })
        });
        const data = await res.json();
        if (data.conversation_id) openConversation(data.conversation_id, `Shop #${shopUserId}`);
    }, 300);
}
```

---

## Tab 3 — 📊 Analytics

This gives the wholesaler a business overview — which shops are ordering the most, which products move fastest, and revenue trends.

### Layout

```
┌───────────────────────────────────────────────────────────────┐
│  Summary Cards                                                 │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐          │
│  │ Total Orders │ │ Revenue MTD  │ │ Top Product  │          │
│  │     42       │ │  ₹1,84,500   │ │  Rice (28%)  │          │
│  └──────────────┘ └──────────────┘ └──────────────┘          │
│                                                               │
│  ┌─────────────────────────────┐  ┌────────────────────────┐ │
│  │  Orders by Product (Bar)    │  │  Revenue This Week     │ │
│  │  [Chart Placeholder]        │  │  [Line Chart]          │ │
│  └─────────────────────────────┘  └────────────────────────┘ │
│                                                               │
│  📋 Top Ordering Shops                                        │
│  Shop Name     | Orders | Total Qty | Revenue                 │
│  Shrey Shop    | 18     | 240 pkt   | ₹72,000                │
│  Ramesh Kirana | 12     | 180 kg    | ₹54,000                │
└───────────────────────────────────────────────────────────────┘
```

### Backend Endpoint

```python
@app.route('/api/wholesaler/analytics', methods=['GET'])
@login_required
def api_wholesaler_analytics():
    if session.get('role') != 'wholesaler':
        return jsonify({'error': 'Forbidden'}), 403

    wholesaler_id = session.get('user_id')
    conn = get_db_connection()
    cur  = conn.cursor()

    # 1. Summary counts
    cur.execute("""
        SELECT
            COUNT(*) FILTER (WHERE status != 'rejected') AS total_orders,
            COUNT(*) FILTER (WHERE status = 'pending')   AS pending_orders,
            COUNT(*) FILTER (WHERE status = 'dispatched') AS dispatched
        FROM orders WHERE wholesaler_user_id = %s
    """, (wholesaler_id,))
    summary = cur.fetchone()

    # 2. Top products by order count
    cur.execute("""
        SELECT product_name, COUNT(*) AS order_count,
               SUM(confirmed_qty) AS total_qty
        FROM orders
        WHERE wholesaler_user_id = %s AND status != 'rejected'
        GROUP BY product_name
        ORDER BY order_count DESC
        LIMIT 5
    """, (wholesaler_id,))
    top_products = cur.fetchall()

    # 3. Top shops by order volume
    cur.execute("""
        SELECT u.display_name, u.shop_name,
               COUNT(*) AS orders,
               SUM(o.confirmed_qty) AS total_qty
        FROM orders o
        JOIN users u ON u.id = o.shop_user_id
        WHERE o.wholesaler_user_id = %s AND o.status != 'rejected'
        GROUP BY u.id, u.display_name, u.shop_name
        ORDER BY orders DESC
        LIMIT 5
    """, (wholesaler_id,))
    top_shops = cur.fetchall()

    # 4. Orders per day this week
    cur.execute("""
        SELECT DATE(created_at) AS day, COUNT(*) AS cnt
        FROM orders
        WHERE wholesaler_user_id = %s
          AND created_at >= NOW() - INTERVAL '7 days'
        GROUP BY day ORDER BY day
    """, (wholesaler_id,))
    daily_orders = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify({
        'summary': {
            'total_orders': summary[0],
            'pending_orders': summary[1],
            'dispatched': summary[2],
        },
        'top_products': [
            {'product': r[0], 'order_count': r[1], 'total_qty': float(r[2] or 0)}
            for r in top_products
        ],
        'top_shops': [
            {'name': r[0] or r[1], 'orders': r[2], 'total_qty': float(r[3] or 0)}
            for r in top_shops
        ],
        'daily_orders': [
            {'day': str(r[0]), 'count': r[1]}
            for r in daily_orders
        ],
    })
```

### Frontend — Analytics JS (uses Chart.js, CDN)

```javascript
// Add to <head>: <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

let productChart = null;
let trendsChart  = null;

async function loadAnalytics() {
    const res  = await fetch('/api/wholesaler/analytics');
    const data = await res.json();

    // Summary cards
    document.getElementById('stat-total').textContent  = data.summary.total_orders;
    document.getElementById('stat-pending').textContent = data.summary.pending_orders;
    document.getElementById('stat-done').textContent   = data.summary.dispatched;
    document.getElementById('stat-top').textContent    =
        data.top_products[0]?.product || '—';

    // Product bar chart
    const prodCtx = document.getElementById('product-chart').getContext('2d');
    if (productChart) productChart.destroy();
    productChart = new Chart(prodCtx, {
        type: 'bar',
        data: {
            labels: data.top_products.map(p => p.product),
            datasets: [{
                label: 'Order Count',
                data: data.top_products.map(p => p.order_count),
                backgroundColor: '#1976d2cc',
            }]
        },
        options: { responsive: true, plugins: { legend: { display: false } } }
    });

    // Daily trend line chart
    const trendCtx = document.getElementById('trend-chart').getContext('2d');
    if (trendsChart) trendsChart.destroy();
    trendsChart = new Chart(trendCtx, {
        type: 'line',
        data: {
            labels: data.daily_orders.map(d => d.day),
            datasets: [{
                label: 'Orders / Day',
                data: data.daily_orders.map(d => d.count),
                borderColor: '#43a047',
                tension: 0.4, fill: true,
                backgroundColor: '#43a04720',
            }]
        },
        options: { responsive: true }
    });

    // Top shops table
    const tbody = document.getElementById('top-shops-body');
    tbody.innerHTML = data.top_shops.map((s, i) => `
        <tr>
            <td>${i + 1}. ${escapeHtml(s.name)}</td>
            <td>${s.orders}</td>
            <td>${s.total_qty.toFixed(1)}</td>
        </tr>
    `).join('');
}
```

---

## Tab 4 — 💬 Chat

This tab is **shared logic with the shopkeeper chat** from the previous guide, but with two differences in the Wholesaler view:

1. The conversation list shows **shop names** (not wholesaler names).
2. There is **no "＋ New Chat" button** — wholesalers receive incoming conversations; shopkeepers initiate them. A wholesaler can reply but not cold-start.
3. Order suggestion messages display with a special **"Create Order"** action button directly in the chat bubble.

```javascript
// Override appendMessage to handle order_suggestion with action button
function appendMessage(msg, scroll = true) {
    const box    = document.getElementById('chat-messages');
    const isMine = msg.sender_id === currentUserId;
    const div    = document.createElement('div');
    const time   = new Date(msg.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});

    let extraHtml = '';
    // Wholesaler sees "Create Order" on order suggestions from shops
    if (msg.message_type === 'order_suggestion' && !isMine && userRole === 'wholesaler') {
        const productMatch = msg.text.match(/LOW STOCK ALERT: (.+)/);
        const qtyMatch     = msg.text.match(/Suggested order: ([\d.]+)/);
        const unitMatch    = msg.text.match(/Threshold: [\d.]+ (.+)/);
        if (productMatch) {
            extraHtml = `
                <div style="margin-top:8px;">
                    <button onclick="quickCreateOrder(
                        ${msg.conversation_id},
                        '${escapeHtml(productMatch[1])}',
                        ${qtyMatch ? qtyMatch[1] : 0}
                    )" class="btn-create-order">📦 Create Order</button>
                </div>`;
        }
    }

    div.className = `msg-bubble ${isMine ? 'mine' : 'theirs'} ${msg.message_type !== 'text' ? msg.message_type : ''}`;
    div.innerHTML = `${escapeHtml(msg.text)}${extraHtml}<div class="msg-time">${time}</div>`;
    box.appendChild(div);
    if (scroll) box.scrollTop = box.scrollHeight;
}
```

---

## Header Stats Bar

At the very top below the navbar, show live summary KPIs in a bar:

```html
<div class="stats-bar" id="stats-bar">
    <div class="stat-card">
        <div class="stat-value" id="stat-pending">—</div>
        <div class="stat-label">Pending Orders</div>
    </div>
    <div class="stat-card">
        <div class="stat-value" id="stat-total">—</div>
        <div class="stat-label">Total Orders</div>
    </div>
    <div class="stat-card">
        <div class="stat-value" id="stat-done">—</div>
        <div class="stat-label">Dispatched</div>
    </div>
    <div class="stat-card">
        <div class="stat-value" id="stat-top">—</div>
        <div class="stat-label">Top Product</div>
    </div>
    <div class="stat-card">
        <div class="stat-value" id="stat-shops">—</div>
        <div class="stat-label">Linked Shops</div>
    </div>
</div>
```

```javascript
async function loadOrderSummaryCards() {
    const [analyticsRes, shopsRes] = await Promise.all([
        fetch('/api/wholesaler/analytics'),
        fetch('/api/wholesaler/shops')
    ]);
    const analytics = await analyticsRes.json();
    const shops     = await shopsRes.json();

    document.getElementById('stat-pending').textContent = analytics.summary.pending_orders;
    document.getElementById('stat-total').textContent   = analytics.summary.total_orders;
    document.getElementById('stat-done').textContent    = analytics.summary.dispatched;
    document.getElementById('stat-top').textContent     = analytics.top_products[0]?.product || '—';
    document.getElementById('stat-shops').textContent   = shops.shops.length;
}
```

---

## Real-Time Notifications via SocketIO

When a new order arrives (a new `order_suggestion` message is saved), push a real-time desktop notification to the wholesaler even if they are on a different tab.

In `send_order_suggestion()` in `app.py`, after the socketio.emit call, also emit a direct wholesaler notification:

```python
# Notify wholesaler's personal room (not conversation room)
wholesaler_room = f"user_{wholesaler_id}"
socketio.emit('new_order_alert', {
    'shop_name':    session.get('display_name', 'A shop'),
    'product_name': product_name,
    'suggested_qty': suggested_qty,
    'unit':         unit,
}, to=wholesaler_room)
```

In the socketio connection handler, join the personal user room:

```python
@socketio.on("connect")
def on_connect():
    # ... existing JWT auth ...
    user_room = f"user_{user_id}"
    join_room(user_room)   # personal notification room
```

On the frontend:

```javascript
chatSocket.on('new_order_alert', (data) => {
    showToast(`📦 New order from ${data.shop_name}: ${data.product_name} × ${data.suggested_qty} ${data.unit}`);
    // Increment orders tab badge
    const badge = document.getElementById('orders-tab-badge');
    badge.textContent = parseInt(badge.textContent || '0') + 1;
    badge.style.display = 'inline-flex';
    // If on orders tab, reload it
    if (activeTab === 'orders') loadOrders('pending');
});
```

---

## Route Setup in `app.py`

```python
@app.route('/wholesaler')
@login_required
def wholesaler_home():
    if session.get('role') != 'wholesaler':
        return redirect(url_for('home'))
    return render_template('wholesaler_dashboard.html')

# Update the main home() route:
@app.route('/')
@login_required
def home():
    role = session.get('role')
    if role == 'wholesaler':
        return redirect(url_for('wholesaler_home'))
    if role == 'admin':
        return redirect(url_for('admin_panel'))
    return render_template('dashboard_template.html')
```

---

## New Files & Modified Files

| File | Type | Purpose |
|---|---|---|
| `wholesaler_dashboard.html` | NEW | Wholesaler-specific Jinja2 template |
| `app.py` | MODIFIED | 5 new REST endpoints + order creation hook |
| DB migration | NEW SQL | `orders` + `wholesaler_shop_links` tables |

---

## Wholesaler vs Shopkeeper — Feature Matrix

| Feature | Shopkeeper | Wholesaler |
|---|---|---|
| Voice inventory input | ✅ Yes | ❌ No |
| Transaction queue | ✅ Yes | ❌ No |
| Manual stock entry | ✅ Yes | ❌ No |
| Order requests (receive) | ❌ No | ✅ Yes |
| Confirm / dispatch orders | ❌ No | ✅ Yes |
| View linked shops | ❌ No | ✅ Yes |
| Analytics (own shop) | ✅ Basic | ✅ Multi-shop |
| Chat — initiate | ✅ Can start | ❌ Replies only |
| Chat — receive | ✅ Yes | ✅ Yes |
| Header KPIs | Stock alerts | Pending orders |
| Order suggestion (auto) | Sends | Receives |
