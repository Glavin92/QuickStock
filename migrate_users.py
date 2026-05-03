# migrate_users.py — Run once to seed a test wholesaler user
# Usage: python migrate_users.py
import os
import psycopg2
import hashlib
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

seed_users = [
    # (username, password, role, shop_name, phone)
    ("wholesaler1", "wholesale2026", "wholesaler", "ABC Wholesale Distributors", "9876543210"),
]

conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()

for username, password, role, shop_name, phone in seed_users:
    hashed = hash_password(password)
    try:
        cur.execute(
            """INSERT INTO shops (username, password_hash, role, shop_name, phone)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (username) DO UPDATE
               SET password_hash=EXCLUDED.password_hash, role=EXCLUDED.role, shop_name=EXCLUDED.shop_name""",
            (username, hashed, role, shop_name, phone)
        )
        print(f"  OK: {username} ({role}) -- password: {password}")
    except Exception as e:
        print(f"  FAIL: {username}: {e}")
        conn.rollback()

conn.commit()
cur.close()
conn.close()
print("\nWholesaler user seeded successfully.")
print("Login with: username=wholesaler1, password=wholesale2026")
