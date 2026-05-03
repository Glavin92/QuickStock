import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def setup_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Enable PostGIS
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        conn.commit()
    except Exception as e:
        print(f"PostGIS extension might already exist or failed: {e}")
        conn.rollback()

    # Create shops table
    cur.execute("""
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
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    
    # Create otp_log table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS otp_log (
        id SERIAL PRIMARY KEY,
        phone VARCHAR(15) NOT NULL,
        otp_code VARCHAR(6) NOT NULL,
        purpose VARCHAR(30),
        created_at TIMESTAMP DEFAULT NOW(),
        expires_at TIMESTAMP,
        used BOOLEAN DEFAULT FALSE
    );
    """)
    
    # Create bills table
    cur.execute("""
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
    """)
    
    # Create bill_items table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bill_items (
        id SERIAL PRIMARY KEY,
        bill_id INT REFERENCES bills(id) ON DELETE CASCADE,
        product_name VARCHAR(100) NOT NULL,
        quantity NUMERIC(10,3) NOT NULL,
        unit VARCHAR(20),
        price_per_unit NUMERIC(10,2) NOT NULL,
        line_total NUMERIC(10,2) NOT NULL
    );
    """)

    # Indices
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bills_created_at ON bills(created_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bills_shop_id ON bills(shop_id);")
    
    # Add geom column to shops and trigger
    cur.execute("ALTER TABLE shops ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326);")
    cur.execute("UPDATE shops SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326) WHERE latitude IS NOT NULL AND longitude IS NOT NULL;")
    
    cur.execute("""
    CREATE OR REPLACE FUNCTION update_shop_geom()
    RETURNS TRIGGER AS $$
    BEGIN
      IF NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.geom = ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """)
    
    cur.execute("""
    DROP TRIGGER IF EXISTS shops_geom_trigger ON shops;
    CREATE TRIGGER shops_geom_trigger
    BEFORE INSERT OR UPDATE ON shops
    FOR EACH ROW EXECUTE FUNCTION update_shop_geom();
    """)
    
    # Create wholesaler_orders table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wholesaler_orders (
        id SERIAL PRIMARY KEY,
        shop_id INT REFERENCES shops(id),
        wholesaler_id INT REFERENCES shops(id),
        order_details TEXT NOT NULL,
        status VARCHAR(20) DEFAULT 'pending', -- 'pending' | 'accepted' | 'delivered'
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)

    # ── Chat System Tables ──────────────────────────────────────────

    # Conversations between shop and wholesaler
    cur.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id                  SERIAL PRIMARY KEY,
        shop_user_id        INTEGER NOT NULL REFERENCES shops(id),
        wholesaler_user_id  INTEGER NOT NULL REFERENCES shops(id),
        created_at          TIMESTAMP DEFAULT NOW(),
        last_message_at     TIMESTAMP DEFAULT NOW(),
        UNIQUE(shop_user_id, wholesaler_user_id)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_conv_shop       ON conversations(shop_user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_conv_wholesaler ON conversations(wholesaler_user_id);")

    # Encrypted messages
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id              SERIAL PRIMARY KEY,
        conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        sender_id       INTEGER NOT NULL REFERENCES shops(id),
        encrypted_body  TEXT NOT NULL,
        iv              VARCHAR(64) NOT NULL,
        auth_tag        VARCHAR(64) NOT NULL,
        message_type    VARCHAR(20) DEFAULT 'text' CHECK (message_type IN ('text', 'order_suggestion', 'system', 'order_dispatch')),
        is_read         BOOLEAN DEFAULT FALSE,
        created_at      TIMESTAMP DEFAULT NOW()
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_conversation ON messages(conversation_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_sender       ON messages(sender_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_created      ON messages(created_at DESC);")

    # Per-conversation AES keys (encrypted with server master key)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_keys (
        id              SERIAL PRIMARY KEY,
        conversation_id INTEGER UNIQUE NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        encrypted_key   TEXT NOT NULL,
        key_iv          VARCHAR(64) NOT NULL,
        key_auth_tag    VARCHAR(64) NOT NULL,
        created_at      TIMESTAMP DEFAULT NOW()
    );
    """)

    # Orders table for Wholesaler dashboard
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id                  SERIAL PRIMARY KEY,
        conversation_id     INTEGER REFERENCES conversations(id),
        message_id          INTEGER REFERENCES messages(id),
        shop_user_id        INTEGER NOT NULL REFERENCES shops(id),
        wholesaler_user_id  INTEGER NOT NULL REFERENCES shops(id),
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
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_wholesaler ON orders(wholesaler_user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_shop       ON orders(shop_user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status     ON orders(status);")

    # Wholesaler-Shop Links table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS wholesaler_shop_links (
        id              SERIAL PRIMARY KEY,
        wholesaler_id   INTEGER NOT NULL REFERENCES shops(id),
        shop_id         INTEGER NOT NULL REFERENCES shops(id),
        linked_at       TIMESTAMP DEFAULT NOW(),
        is_active       BOOLEAN DEFAULT TRUE,
        UNIQUE(wholesaler_id, shop_id)
    );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Database tables created successfully.")

if __name__ == "__main__":
    setup_db()
