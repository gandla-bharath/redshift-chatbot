"""
scripts/load_sample_data.py
---------------------------
Load sample data into local PostgreSQL to simulate a Redshift warehouse.
Run once after starting Docker: python scripts/load_sample_data.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import random
from datetime import datetime, timedelta
from src.db import get_local_connection

CITIES      = ["Austin", "New York", "Los Angeles", "Chicago", "Seattle", "Miami", "Denver"]
CATEGORIES  = ["Apartment", "House", "Villa", "Condo", "Studio", "Cabin"]
STATUSES    = ["confirmed", "cancelled", "completed"]
COUNTRIES   = ["USA", "Canada", "UK", "Australia", "Germany"]


def create_tables(cur):
    cur.execute("""
        DROP TABLE IF EXISTS reviews, bookings, properties, users CASCADE;

        CREATE TABLE users (
            user_id     SERIAL PRIMARY KEY,
            name        VARCHAR(100),
            email       VARCHAR(150),
            country     VARCHAR(50),
            signup_date DATE
        );

        CREATE TABLE properties (
            property_id  SERIAL PRIMARY KEY,
            name         VARCHAR(120),
            city         VARCHAR(50),
            country      VARCHAR(50),
            category     VARCHAR(30),
            price_per_night DECIMAL(8,2),
            host_id      INT
        );

        CREATE TABLE bookings (
            booking_id   SERIAL PRIMARY KEY,
            property_id  INT REFERENCES properties(property_id),
            user_id      INT REFERENCES users(user_id),
            checkin_date DATE,
            checkout_date DATE,
            amount       DECIMAL(10,2),
            status       VARCHAR(20),
            created_at   TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE reviews (
            review_id    SERIAL PRIMARY KEY,
            booking_id   INT REFERENCES bookings(booking_id),
            rating       INT CHECK (rating BETWEEN 1 AND 5),
            comment      TEXT,
            created_at   TIMESTAMP DEFAULT NOW()
        );
    """)
    print("✅ Tables created")


def load_users(cur, n=100):
    for i in range(1, n + 1):
        signup = datetime(2022, 1, 1) + timedelta(days=random.randint(0, 800))
        cur.execute(
            "INSERT INTO users(name, email, country, signup_date) VALUES(%s,%s,%s,%s)",
            (f"User {i}", f"user{i}@example.com", random.choice(COUNTRIES), signup.date())
        )
    print(f"✅ {n} users loaded")


def load_properties(cur, n=50):
    for i in range(1, n + 1):
        cur.execute(
            "INSERT INTO properties(name, city, country, category, price_per_night, host_id) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                f"{random.choice(CATEGORIES)} #{i}",
                random.choice(CITIES), "USA",
                random.choice(CATEGORIES),
                round(random.uniform(50, 600), 2),
                random.randint(1, 20)
            )
        )
    print(f"✅ {n} properties loaded")


def load_bookings(cur, n=500):
    for i in range(n):
        checkin = datetime(2023, 1, 1) + timedelta(days=random.randint(0, 500))
        nights  = random.randint(1, 14)
        checkout = checkin + timedelta(days=nights)
        amount  = round(random.uniform(100, 5000), 2)
        cur.execute("""
            INSERT INTO bookings(property_id, user_id, checkin_date, checkout_date, amount, status, created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
        """, (
            random.randint(1, 50), random.randint(1, 100),
            checkin.date(), checkout.date(),
            amount, random.choice(STATUSES),
            checkin - timedelta(days=random.randint(1, 60))
        ))
    print(f"✅ {n} bookings loaded")


def load_reviews(cur, n=300):
    for i in range(1, n + 1):
        cur.execute(
            "INSERT INTO reviews(booking_id, rating, comment, created_at) VALUES(%s,%s,%s,%s)",
            (
                random.randint(1, 500),
                random.randint(1, 5),
                random.choice(["Great stay!", "Would recommend", "Average experience", "Excellent!", "Not great"]),
                datetime(2023, random.randint(1, 12), random.randint(1, 28))
            )
        )
    print(f"✅ {n} reviews loaded")


def main():
    print("\n🔌 Connecting to local PostgreSQL...")
    conn = get_local_connection()
    cur  = conn.cursor()

    create_tables(cur)
    load_users(cur)
    load_properties(cur)
    load_bookings(cur)
    load_reviews(cur)

    conn.commit()
    cur.close()
    conn.close()
    print("\n🎉 Sample data loaded successfully!")
    print("Run: jupyter notebook notebooks/01_test_connection.ipynb")


if __name__ == "__main__":
    main()
