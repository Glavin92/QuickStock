import os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'orders'")
cols = [c[0] for c in cur.fetchall()]
print(f"Columns in 'orders': {cols}")
conn.close()
