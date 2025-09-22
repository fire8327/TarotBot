import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
from datetime import date

load_dotenv()

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"), cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                readings_balance INTEGER DEFAULT 1,
                total_used INTEGER DEFAULT 0,
                last_card_date DATE,
                daily_card TEXT,
                referral_count INTEGER DEFAULT 0,
                referrer_id BIGINT,
                last_active_date DATE,
                free_readings_used INTEGER DEFAULT 0,
                conversion_step TEXT DEFAULT 'start',
                last_update_notified TEXT DEFAULT 'v1.0',
                created_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                pack_id TEXT,
                readings INTEGER,
                price_stars INTEGER,
                paid_amount INTEGER,
                charge_id TEXT UNIQUE,
                purchase_date DATE DEFAULT CURRENT_DATE
            );

            CREATE TABLE IF NOT EXISTS readings_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                reading_type TEXT,
                reading_text TEXT,
                reading_date TIMESTAMP DEFAULT NOW()
            );
        """)
        conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            cur.execute("""
                INSERT INTO users (user_id, readings_balance)
                VALUES (%s, %s) RETURNING *
            """, (user_id, 1))
            user = cur.fetchone()
            conn.commit()
        else:
            cur.execute("SELECT * FROM readings_history WHERE user_id = %s ORDER BY reading_date DESC LIMIT 5", (user_id,))
            readings = cur.fetchall()
            user['last_readings'] = [
                {'type': r['reading_type'], 'text': r['reading_text'], 'date': r['reading_date'].strftime("%Y-%m-%d %H:%M")}
                for r in readings
            ]
            cur.execute("SELECT * FROM purchases WHERE user_id = %s ORDER BY purchase_date DESC", (user_id,))
            purchases = cur.fetchall()
            user['purchases'] = [
                {
                    'pack_id': p['pack_id'],
                    'readings': p['readings'],
                    'price_stars': p['price_stars'],
                    'paid_amount': p['paid_amount'],
                    'charge_id': p['charge_id'],
                    'date': p['purchase_date'].strftime("%Y-%m-%d")
                }
                for p in purchases
            ]
        conn.close()
        return user

def update_user_name(user_id, name):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET name = %s WHERE user_id = %s", (name, user_id))
        conn.commit()
    conn.close()

def update_user_balance(user_id, new_balance):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET readings_balance = %s WHERE user_id = %s", (new_balance, user_id))
        conn.commit()
    conn.close()

def increment_total_used(user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET total_used = total_used + 1 WHERE user_id = %s", (user_id,))
        conn.commit()
    conn.close()

def save_purchase(user_id, pack_id, readings, price_stars, paid_amount, charge_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO purchases (user_id, pack_id, readings, price_stars, paid_amount, charge_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, pack_id, readings, price_stars, paid_amount, charge_id))
        conn.commit()
    conn.close()

def save_reading(user_id, reading_type, reading_text):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO readings_history (user_id, reading_type, reading_text)
            VALUES (%s, %s, %s)
        """, (user_id, reading_type, reading_text))
        cur.execute("""
            DELETE FROM readings_history
            WHERE id NOT IN (
                SELECT id FROM readings_history
                WHERE user_id = %s
                ORDER BY reading_date DESC
                LIMIT 5
            ) AND user_id = %s
        """, (user_id, user_id))
        conn.commit()
    conn.close()

def update_daily_card(user_id, card_text):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET daily_card = %s, last_card_date = CURRENT_DATE WHERE user_id = %s", (card_text, user_id))
        conn.commit()
    conn.close()

def increment_referral_count(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET referral_count = referral_count + 1 WHERE user_id = %s', (user_id,))
    conn.commit()
    conn.close()

# --- Аналитика ---
def update_user_last_active(user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET last_active_date = CURRENT_DATE WHERE user_id = %s", (user_id,))
        conn.commit()
    conn.close()

def increment_free_readings_used(user_id):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET free_readings_used = free_readings_used + 1 WHERE user_id = %s", (user_id,))
        conn.commit()
    conn.close()

def update_conversion_step(user_id, step):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET conversion_step = %s WHERE user_id = %s", (step, user_id))
        conn.commit()
    conn.close()

def update_user_last_update_notified(user_id, version):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET last_update_notified = %s WHERE user_id = %s", (version, user_id))
        conn.commit()
    conn.close()

def get_active_users(days=7):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT user_id FROM users 
            WHERE created_at >= NOW() - INTERVAL '%s days'
        """, (days,))
        users = cur.fetchall()
    conn.close()
    return users