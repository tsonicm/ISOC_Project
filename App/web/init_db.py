"""
Database initialization for Web/BFF.
Creates table: users in web.db
Seeds default accounts for testing.
"""

import sqlite3
import os
from werkzeug.security import generate_password_hash
import requests as http_client


DB_PATH = os.environ.get("DB_PATH", "/data/web.db")
DIRECTORY_SERVICE_BASE_URL = os.environ.get(
    "DIRECTORY_SERVICE_BASE_URL", "http://directory-service:5002"
)


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they do not exist."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('patient', 'doctor', 'admin')),
            entity_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    conn.commit()
    conn.close()


def seed_data():
    """
    Seed default test data if the users table is empty.
    Creates entities in Directory Service and corresponding users in web.db.
    """
    conn = get_db()
    user_count = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]

    if user_count > 0:
        conn.close()
        print("[SEED] Users already exist, skipping seed.")
        return

    print("[SEED] Seeding default data...")

    # --- Seed Admin in Directory Service ---
    try:
        resp = http_client.post(
            f"{DIRECTORY_SERVICE_BASE_URL}/admin",
            json={"full_name": "Admin Principal", "email": "admin@clinic.com"},
            timeout=5,
        )
        admin_data = resp.json()
        admin_id = admin_data["id"]
        print(f"[SEED] Created admin: id={admin_id}")
    except Exception as e:
        print(f"[SEED] WARNING: Could not create admin in Directory Service: {e}")
        admin_id = 1

    # --- Seed Doctors in Directory Service ---
    doctors = [
        {"full_name": "Dr. Maria Popescu", "specialization": "Cardiologie",
         "email": "maria.popescu@clinic.com", "phone": "0721000001"},
        {"full_name": "Dr. Ion Ionescu", "specialization": "Dermatologie",
         "email": "ion.ionescu@clinic.com", "phone": "0721000002"},
    ]
    doctor_ids = []
    for doc in doctors:
        try:
            resp = http_client.post(
                f"{DIRECTORY_SERVICE_BASE_URL}/doctors",
                json=doc,
                timeout=5,
            )
            doc_data = resp.json()
            doctor_ids.append(doc_data["id"])
            print(f"[SEED] Created doctor: id={doc_data['id']} - {doc['full_name']}")
        except Exception as e:
            print(f"[SEED] WARNING: Could not create doctor: {e}")
            doctor_ids.append(len(doctor_ids) + 1)

    # --- Seed Working Hours for Doctors (Mon-Fri, 09:00-17:00, 30min slots, lunch 12:00-13:00) ---
    for doc_id in doctor_ids:
        for weekday in range(0, 5):  # Monday=0 to Friday=4
            try:
                http_client.post(
                    f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doc_id}/working-hours",
                    json={
                        "weekday": weekday,
                        "start_time": "09:00",
                        "end_time": "17:00",
                        "slot_length_minutes": 30,
                        "break_start_time": "12:00",
                        "break_end_time": "13:00",
                    },
                    timeout=5,
                )
            except Exception as e:
                print(f"[SEED] WARNING: Could not create working hours: {e}")
    print("[SEED] Created working hours for doctors (Mon-Fri, 09:00-17:00)")

    # --- Seed Patients in Directory Service ---
    patients = [
        {"full_name": "Ana Vasile", "email": "ana.vasile@email.com", "phone": "0740000001"},
        {"full_name": "George Radu", "email": "george.radu@email.com", "phone": "0740000002"},
    ]
    patient_ids = []
    for pat in patients:
        try:
            resp = http_client.post(
                f"{DIRECTORY_SERVICE_BASE_URL}/patients",
                json=pat,
                timeout=5,
            )
            pat_data = resp.json()
            patient_ids.append(pat_data["id"])
            print(f"[SEED] Created patient: id={pat_data['id']} - {pat['full_name']}")
        except Exception as e:
            print(f"[SEED] WARNING: Could not create patient: {e}")
            patient_ids.append(len(patient_ids) + 1)

    # --- Create users in web.db ---
    # Admin user
    conn.execute(
        "INSERT INTO users (email, password, role, entity_id) VALUES (?, ?, ?, ?)",
        ("admin@clinic.com", generate_password_hash("admin123"), "admin", admin_id),
    )

    # Doctor users
    doctor_emails = ["maria.popescu@clinic.com", "ion.ionescu@clinic.com"]
    for i, email in enumerate(doctor_emails):
        conn.execute(
            "INSERT INTO users (email, password, role, entity_id) VALUES (?, ?, ?, ?)",
            (email, generate_password_hash("doctor123"), "doctor", doctor_ids[i]),
        )

    # Patient users
    patient_emails = ["ana.vasile@email.com", "george.radu@email.com"]
    for i, email in enumerate(patient_emails):
        conn.execute(
            "INSERT INTO users (email, password, role, entity_id) VALUES (?, ?, ?, ?)",
            (email, generate_password_hash("patient123"), "patient", patient_ids[i]),
        )

    conn.commit()
    conn.close()
    print("[SEED] Seeding complete!")
    print("[SEED] Test accounts:")
    print("[SEED]   Admin:   admin@clinic.com / admin123")
    print("[SEED]   Doctor:  maria.popescu@clinic.com / doctor123")
    print("[SEED]   Doctor:  ion.ionescu@clinic.com / doctor123")
    print("[SEED]   Patient: ana.vasile@email.com / patient123")
    print("[SEED]   Patient: george.radu@email.com / patient123")


if __name__ == "__main__":
    init_db()
    seed_data()
    print(f"Database initialized at {DB_PATH}")
