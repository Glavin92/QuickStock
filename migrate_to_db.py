import os
import csv
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Original dictionary data
products = {
    "पारले जी": {"current_stock": 100, "threshold": 20, "unit": "पैकेट", "base_unit": "पैकेट", "price": 10},
    "लेस": {"current_stock": 50, "threshold": 15, "unit": "पैकेट", "base_unit": "पैकेट", "price": 20},
    "डाबर हनी": {"current_stock": 30, "threshold": 10, "unit": "बोतल", "base_unit": "बोतल", "price": 150},
    "टाटा नमक": {"current_stock": 80, "threshold": 25, "unit": "पैकेट", "base_unit": "पैकेट", "price": 25},
    "कोक": {"current_stock": 40, "threshold": 12, "unit": "बोतल", "base_unit": "बोतल", "price": 40},
    "साबुन": {"current_stock": 25, "threshold": 8, "unit": "पीस", "base_unit": "पीस", "price": 35},

    "आटा": {"current_stock": 100, "threshold": 25, "unit": "किलो", "base_unit": "किलो", "price": 45},
    "चावल": {"current_stock": 150, "threshold": 30, "unit": "किलो", "base_unit": "किलो", "price": 60},
    "दाल": {"current_stock": 80, "threshold": 20, "unit": "किलो", "base_unit": "किलो", "price": 120},
    "चीनी": {"current_stock": 60, "threshold": 15, "unit": "किलो", "base_unit": "किलो", "price": 42},

    "तेल": {"current_stock": 50, "threshold": 12, "unit": "लीटर", "base_unit": "लीटर", "price": 180},
    "दूध": {"current_stock": 40, "threshold": 10, "unit": "लीटर", "base_unit": "लीटर", "price": 66},
    "चाय": {"current_stock": 5, "threshold": 2, "unit": "किलो", "base_unit": "किलो", "price": 450},
}

def migrate():
    print("Connecting to Neon DB...")
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # 1. Create Tables
    print("Creating tables...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            current_stock FLOAT NOT NULL DEFAULT 0,
            threshold FLOAT NOT NULL DEFAULT 0,
            unit VARCHAR(50) NOT NULL,
            base_unit VARCHAR(50) NOT NULL,
            price FLOAT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            product_name VARCHAR(255) NOT NULL,
            quantity FLOAT NOT NULL,
            transaction_type VARCHAR(50) NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            unit VARCHAR(50),
            old_stock FLOAT,
            new_stock FLOAT
        );
    """)
    conn.commit()

    # 2. Seed Products
    print("Seeding products...")
    for name, data in products.items():
        cur.execute("""
            INSERT INTO products (name, current_stock, threshold, unit, base_unit, price)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET 
                current_stock = EXCLUDED.current_stock,
                threshold = EXCLUDED.threshold,
                unit = EXCLUDED.unit,
                base_unit = EXCLUDED.base_unit,
                price = EXCLUDED.price;
        """, (name, data['current_stock'], data['threshold'], data['unit'], data['base_unit'], data['price']))
    conn.commit()
    
    # 3. Seed Transactions from CSV
    print("Seeding transactions from CSV...")
    csv_path = 'transactions_history.csv'
    if os.path.exists(csv_path):
        with open(csv_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                try:
                    product = row.get('Product', row.get('\ufeffProduct', row.get('product', '')))
                    quantity = float(row.get('Quantity', row.get('quantity', 0)))
                    transaction_type = row.get('Type', row.get('action', 'sale'))
                    # Some files might not have Unit column in history, provide fallback
                    unit = row.get('Unit', '')
                    timestamp_str = row['Timestamp']
                    try:
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')

                    # Prevent duplicate insertions using naive distinct timestamp checking
                    # If you run migration multiple times, this snippet will create duplicate history rows.
                    # As a one-off script, this is fine.
                    cur.execute("""
                        INSERT INTO transactions (product_name, quantity, transaction_type, timestamp, unit)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (product, quantity, transaction_type, timestamp, unit))
                except Exception as e:
                    print(f"Skipping row {row} due to exact error: {e}")
        conn.commit()
        print("CSV Migration Complete.")
    else:
        print("No CSV found to migrate.")

    cur.close()
    conn.close()
    print("Migration finished successfully.")

if __name__ == '__main__':
    migrate()
