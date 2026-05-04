import os
import psycopg2
import hashlib
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    print(f"Connecting to database at {DATABASE_URL}...")
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # 1. Enable PostGIS if available (optional)
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        conn.commit()
        print("PostGIS extension created/verified.")
    except Exception as e:
        print(f"PostGIS extension not available (ignoring): {e}")
        conn.rollback()

    # 2. Table Creation Commands
    tables = [
        """
        CREATE TABLE IF NOT EXISTS shops (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) NOT NULL DEFAULT 'shop',
            shop_name VARCHAR(255),
            phone VARCHAR(20) UNIQUE,
            address TEXT,
            city VARCHAR(100),
            pin_code VARCHAR(20),
            latitude NUMERIC,
            longitude NUMERIC,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "ALTER TABLE shops ADD COLUMN IF NOT EXISTS geom geometry(Point, 4326)",
        """
        CREATE TABLE IF NOT EXISTS otp_log (
            id SERIAL PRIMARY KEY,
            phone VARCHAR(20) NOT NULL,
            otp_code VARCHAR(10) NOT NULL,
            purpose VARCHAR(50) NOT NULL,
            used BOOLEAN DEFAULT FALSE,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            current_stock NUMERIC NOT NULL DEFAULT 0,
            threshold NUMERIC NOT NULL DEFAULT 0,
            unit VARCHAR(50) NOT NULL,
            base_unit VARCHAR(50) NOT NULL,
            price NUMERIC NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            product_name VARCHAR(255) NOT NULL,
            quantity NUMERIC NOT NULL,
            transaction_type VARCHAR(50) NOT NULL,
            unit VARCHAR(50),
            old_stock NUMERIC,
            new_stock NUMERIC,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id SERIAL PRIMARY KEY,
            shop_user_id INTEGER REFERENCES shops(id),
            wholesaler_user_id INTEGER REFERENCES shops(id),
            last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(shop_user_id, wholesaler_user_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS chat_keys (
            id SERIAL PRIMARY KEY,
            conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
            encrypted_key VARCHAR(255) NOT NULL,
            key_iv VARCHAR(255) NOT NULL,
            key_auth_tag VARCHAR(255) NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            conversation_id INTEGER REFERENCES conversations(id),
            sender_id INTEGER REFERENCES shops(id),
            encrypted_body TEXT NOT NULL,
            iv VARCHAR(255) NOT NULL,
            auth_tag VARCHAR(255) NOT NULL,
            message_type VARCHAR(50) DEFAULT 'text',
            is_read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            conversation_id INTEGER REFERENCES conversations(id),
            message_id INTEGER REFERENCES messages(id),
            shop_user_id INTEGER REFERENCES shops(id),
            wholesaler_user_id INTEGER REFERENCES shops(id),
            product_name VARCHAR(255),
            requested_qty NUMERIC,
            confirmed_qty NUMERIC,
            unit VARCHAR(50),
            status VARCHAR(50) DEFAULT 'pending',
            wholesaler_note TEXT,
            items_json JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS wholesaler_shop_links (
            id SERIAL PRIMARY KEY,
            wholesaler_id INTEGER REFERENCES shops(id),
            shop_id INTEGER REFERENCES shops(id),
            is_active BOOLEAN DEFAULT TRUE,
            UNIQUE(wholesaler_id, shop_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bills (
            id SERIAL PRIMARY KEY,
            shop_id INTEGER REFERENCES shops(id),
            bill_number VARCHAR(50) NOT NULL,
            customer_name VARCHAR(255),
            customer_phone VARCHAR(20),
            subtotal NUMERIC(10,2) NOT NULL DEFAULT 0,
            discount NUMERIC(10,2) NOT NULL DEFAULT 0,
            gst_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
            gst_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            total NUMERIC(10,2) NOT NULL DEFAULT 0,
            payment_mode VARCHAR(20) DEFAULT 'cash',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bill_items (
            id SERIAL PRIMARY KEY,
            bill_id INTEGER REFERENCES bills(id) ON DELETE CASCADE,
            product_name VARCHAR(255) NOT NULL,
            quantity NUMERIC NOT NULL,
            unit VARCHAR(50),
            unit_price NUMERIC(10,2),
            line_total NUMERIC(10,2),
            price_per_unit NUMERIC(10,2)
        )
        """,
        "CREATE SEQUENCE IF NOT EXISTS bill_number_seq START 1",
        # Fixes for existing local databases
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS wholesaler_note TEXT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS items_json JSONB",
        "ALTER TABLE bills ADD COLUMN IF NOT EXISTS notes TEXT"
    ]

    for sql in tables:
        try:
            cur.execute(sql)
            conn.commit()
            print(f"Executed: {sql.strip().split()[0:3]}...")
        except Exception as e:
            conn.rollback()
            # Ignore error about PostGIS types if extension failed earlier
            if "type \"geometry\" does not exist" in str(e):
                print("Skipped geometry column (PostGIS missing).")
            else:
                print(f"Error executing:\n{sql}\nError: {e}")

    # 3. Seed Default Users
    print("\nSeeding default users...")
    default_users = [
        ("admin", "quickstock2026", "admin", "QuickStock Admin HQ", "0000000000"),
        ("shop_shrey", "shrey2026", "shop", "Shrey Mart - Mumbai", "1111111111"),
        ("wholesaler1", "wholesaler2026", "wholesaler", "Metro Cash & Carry", "2222222222")
    ]

    for username, password, role, shop_name, phone in default_users:
        try:
            cur.execute("""
                INSERT INTO shops (username, password_hash, role, shop_name, phone)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (username) DO NOTHING
            """, (username, hash_password(password), role, shop_name, phone))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Error seeding user {username}: {e}")

    # Link shop to wholesaler
    try:
        cur.execute("SELECT id FROM shops WHERE username = 'wholesaler1'")
        w_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM shops WHERE username = 'shop_shrey'")
        s_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO wholesaler_shop_links (wholesaler_id, shop_id)
            VALUES (%s, %s) ON CONFLICT DO NOTHING
        """, (w_id, s_id))
        conn.commit()
        print("Linked shop_shrey to wholesaler1.")
    except Exception as e:
        conn.rollback()
        print("Could not link default shop to wholesaler automatically.")

    cur.close()
    conn.close()
    print("\nDatabase initialization complete! You can now start the server.")

if __name__ == '__main__':
    init_db()
