import os, psycopg2, json
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute('SELECT id, product_name, requested_qty, confirmed_qty, items_json, status, shop_user_id FROM orders')
orders = cur.fetchall()
cur.execute('SELECT name, current_stock FROM products')
prods = cur.fetchall()
with open('scratch/db_state.txt', 'w', encoding='utf-8') as f:
    f.write(f"Orders: {orders}\n")
    f.write(f"Products: {prods}\n")
conn.close()
print("Done.")
