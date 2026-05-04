import os, psycopg2, json
from dotenv import load_dotenv
load_dotenv()
from app import find_product, get_all_products_db

inventory = get_all_products_db()
res = find_product('Tea', inventory=inventory)
print(f"find_product('Tea') -> {res}")
res2 = find_product('Wheat Flour', inventory=inventory)
print(f"find_product('Wheat Flour') -> {res2}")
