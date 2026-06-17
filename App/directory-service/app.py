"""
Directory Service — manages patients, doctors, admins, and doctor working hours.
REST API over HTTP with JSON payloads.
Port: 5002
Database: directory.db
"""

import os
from datetime import datetime
from flask import Flask, request, jsonify
from init_db import init_db, get_db

app = Flask(__name__)

PORT = int(os.environ.get("PORT", 5002))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    """Convert a list of sqlite3.Row objects to a list of dicts."""
    return [dict(r) for r in rows]


def now_iso():
    """Return current UTC timestamp in ISO format."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


# ===========================================================================
#  PATIENTS
# ===========================================================================

@app.route("/patients", methods=["GET"])
def list_patients():
    """List all patients."""
    db = get_db()
    rows = db.execute("SELECT * FROM patients ORDER BY id").fetchall()
    db.close()
    return jsonify(rows_to_list(rows)), 200


@app.route("/patients", methods=["POST"])
def create_patient():
    """Create a new patient."""
    data = request.get_json(force=True)

    full_name = data.get("full_name")
    email = data.get("email")
    phone = data.get("phone")

    if not full_name or not email:
        return jsonify({"error": "full_name and email are required"}), 400

    db = get_db()
    cursor = db.execute(
        "INSERT INTO patients (full_name, email, phone, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (full_name, email, phone, now_iso(), now_iso()),
    )
    patient_id = cursor.lastrowid
    db.commit()

    patient = row_to_dict(
        db.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    )
    db.close()
    return jsonify(patient), 201


@app.route("/patients/<int:patient_id>", methods=["GET"])
def get_patient(patient_id):
    """Get a single patient by ID."""
    db = get_db()
    row = db.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    db.close()

    if row is None:
        return jsonify({"error": "Patient not found"}), 404
    return jsonify(row_to_dict(row)), 200


# ===========================================================================
#  DOCTORS
# ===========================================================================

@app.route("/doctors", methods=["GET"])
def list_doctors():
    """List all doctors. Optional query param: ?active=1"""
    db = get_db()
    active_filter = request.args.get("active")

    if active_filter is not None:
        rows = db.execute(
            "SELECT * FROM doctors WHERE active = ? ORDER BY id", (int(active_filter),)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM doctors ORDER BY id").fetchall()

    db.close()
    return jsonify(rows_to_list(rows)), 200


@app.route("/doctors", methods=["POST"])
def create_doctor():
    """Create a new doctor."""
    data = request.get_json(force=True)

    full_name = data.get("full_name")
    email = data.get("email")
    specialization = data.get("specialization")
    phone = data.get("phone")
    active = data.get("active", 1)

    if not full_name or not email:
        return jsonify({"error": "full_name and email are required"}), 400

    db = get_db()
    cursor = db.execute(
        """INSERT INTO doctors (full_name, specialization, email, phone, active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (full_name, specialization, email, phone, int(active), now_iso(), now_iso()),
    )
    doctor_id = cursor.lastrowid
    db.commit()

    doctor = row_to_dict(
        db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    )
    db.close()
    return jsonify(doctor), 201


@app.route("/doctors/<int:doctor_id>", methods=["GET"])
def get_doctor(doctor_id):
    """Get a single doctor by ID."""
    db = get_db()
    row = db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    db.close()

    if row is None:
        return jsonify({"error": "Doctor not found"}), 404
    return jsonify(row_to_dict(row)), 200


@app.route("/doctors/<int:doctor_id>", methods=["PATCH"])
def update_doctor(doctor_id):
    """Update specified fields of a doctor."""
    data = request.get_json(force=True)
    db = get_db()

    existing = db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    if existing is None:
        db.close()
        return jsonify({"error": "Doctor not found"}), 404

    allowed_fields = ["full_name", "specialization", "email", "phone", "active"]
    updates = []
    values = []
    for field in allowed_fields:
        if field in data:
            updates.append(f"{field} = ?")
            val = data[field]
            if field == "active":
                val = int(val)
            values.append(val)

    if not updates:
        db.close()
        return jsonify({"error": "No valid fields to update"}), 400

    updates.append("updated_at = ?")
    values.append(now_iso())
    values.append(doctor_id)

    db.execute(
        f"UPDATE doctors SET {', '.join(updates)} WHERE id = ?", values
    )
    db.commit()

    doctor = row_to_dict(
        db.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    )
    db.close()
    return jsonify(doctor), 200


# ===========================================================================
#  DOCTOR WORKING HOURS
# ===========================================================================

@app.route("/doctors/<int:doctor_id>/working-hours", methods=["GET"])
def get_working_hours(doctor_id):
    """Get all working hours entries for a doctor."""
    db = get_db()

    # Verify doctor exists
    doctor = db.execute("SELECT id FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    if doctor is None:
        db.close()
        return jsonify({"error": "Doctor not found"}), 404

    rows = db.execute(
        "SELECT * FROM doctor_working_hours WHERE doctor_id = ? ORDER BY weekday",
        (doctor_id,),
    ).fetchall()
    db.close()
    return jsonify(rows_to_list(rows)), 200


@app.route("/doctors/<int:doctor_id>/working-hours", methods=["POST"])
def create_working_hours(doctor_id):
    """Create a working hours entry for a doctor on a specific weekday."""
    data = request.get_json(force=True)
    db = get_db()

    # Verify doctor exists
    doctor = db.execute("SELECT id FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    if doctor is None:
        db.close()
        return jsonify({"error": "Doctor not found"}), 404

    weekday = data.get("weekday")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    slot_length_minutes = data.get("slot_length_minutes")

    if weekday is None or not start_time or not end_time or not slot_length_minutes:
        db.close()
        return jsonify({"error": "weekday, start_time, end_time, and slot_length_minutes are required"}), 400

    weekday = int(weekday)
    if weekday < 0 or weekday > 6:
        db.close()
        return jsonify({"error": "weekday must be 0-6"}), 400

    # Check for duplicate weekday
    existing = db.execute(
        "SELECT id FROM doctor_working_hours WHERE doctor_id = ? AND weekday = ?",
        (doctor_id, weekday),
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"error": f"Working hours already exist for weekday {weekday}"}), 409

    break_start = data.get("break_start_time")
    break_end = data.get("break_end_time")

    cursor = db.execute(
        """INSERT INTO doctor_working_hours
           (doctor_id, weekday, start_time, end_time, slot_length_minutes,
            break_start_time, break_end_time, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (doctor_id, weekday, start_time, end_time, int(slot_length_minutes),
         break_start, break_end, now_iso(), now_iso()),
    )
    wh_id = cursor.lastrowid
    db.commit()

    wh = row_to_dict(
        db.execute("SELECT * FROM doctor_working_hours WHERE id = ?", (wh_id,)).fetchone()
    )
    db.close()
    return jsonify(wh), 201


@app.route("/doctors/<int:doctor_id>/working-hours", methods=["PATCH"])
def update_working_hours(doctor_id):
    """Update working hours entry. Identify by weekday query param or id in body."""
    data = request.get_json(force=True)
    db = get_db()

    # Identify the record: prefer weekday query param, fallback to id in body
    weekday = request.args.get("weekday")
    wh_id = data.get("id")

    if weekday is not None:
        row = db.execute(
            "SELECT * FROM doctor_working_hours WHERE doctor_id = ? AND weekday = ?",
            (doctor_id, int(weekday)),
        ).fetchone()
    elif wh_id is not None:
        row = db.execute(
            "SELECT * FROM doctor_working_hours WHERE id = ? AND doctor_id = ?",
            (int(wh_id), doctor_id),
        ).fetchone()
    else:
        db.close()
        return jsonify({"error": "Provide weekday query param or id in body"}), 400

    if row is None:
        db.close()
        return jsonify({"error": "Working hours entry not found"}), 404

    record_id = row["id"]

    allowed_fields = [
        "weekday", "start_time", "end_time", "slot_length_minutes",
        "break_start_time", "break_end_time",
    ]
    updates = []
    values = []
    for field in allowed_fields:
        if field in data:
            updates.append(f"{field} = ?")
            val = data[field]
            if field in ("weekday", "slot_length_minutes") and val is not None:
                val = int(val)
            values.append(val)

    if not updates:
        db.close()
        return jsonify({"error": "No valid fields to update"}), 400

    updates.append("updated_at = ?")
    values.append(now_iso())
    values.append(record_id)

    db.execute(
        f"UPDATE doctor_working_hours SET {', '.join(updates)} WHERE id = ?", values
    )
    db.commit()

    updated = row_to_dict(
        db.execute("SELECT * FROM doctor_working_hours WHERE id = ?", (record_id,)).fetchone()
    )
    db.close()
    return jsonify(updated), 200


@app.route("/doctors/<int:doctor_id>/working-hours", methods=["DELETE"])
def delete_working_hours(doctor_id):
    """Delete working hours entry by weekday query param."""
    db = get_db()

    weekday = request.args.get("weekday")
    if weekday is None:
        db.close()
        return jsonify({"error": "weekday query parameter is required"}), 400

    row = db.execute(
        "SELECT id FROM doctor_working_hours WHERE doctor_id = ? AND weekday = ?",
        (doctor_id, int(weekday)),
    ).fetchone()

    if row is None:
        db.close()
        return jsonify({"error": "Working hours entry not found"}), 404

    db.execute(
        "DELETE FROM doctor_working_hours WHERE doctor_id = ? AND weekday = ?",
        (doctor_id, int(weekday)),
    )
    db.commit()
    db.close()
    return "", 204


# ===========================================================================
#  ADMINS
# ===========================================================================

@app.route("/admin", methods=["POST"])
def create_admin():
    """Create a new admin."""
    data = request.get_json(force=True)

    # Support both full_name and first_name+last_name (AMB-08)
    full_name = data.get("full_name")
    if not full_name:
        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()

    email = data.get("email")

    if not full_name or not email:
        return jsonify({"error": "full_name (or first_name+last_name) and email are required"}), 400

    db = get_db()
    cursor = db.execute(
        "INSERT INTO admins (full_name, email, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (full_name, email, now_iso(), now_iso()),
    )
    admin_id = cursor.lastrowid
    db.commit()

    admin = row_to_dict(
        db.execute("SELECT * FROM admins WHERE id = ?", (admin_id,)).fetchone()
    )
    db.close()
    return jsonify(admin), 201


@app.route("/admin/<int:admin_id>", methods=["PATCH"])
def update_admin(admin_id):
    """Update admin fields."""
    data = request.get_json(force=True)
    db = get_db()

    existing = db.execute("SELECT * FROM admins WHERE id = ?", (admin_id,)).fetchone()
    if existing is None:
        db.close()
        return jsonify({"error": "Admin not found"}), 404

    allowed_fields = ["full_name", "email"]
    updates = []
    values = []
    for field in allowed_fields:
        if field in data:
            updates.append(f"{field} = ?")
            values.append(data[field])

    if not updates:
        db.close()
        return jsonify({"error": "No valid fields to update"}), 400

    updates.append("updated_at = ?")
    values.append(now_iso())
    values.append(admin_id)

    db.execute(f"UPDATE admins SET {', '.join(updates)} WHERE id = ?", values)
    db.commit()

    admin = row_to_dict(
        db.execute("SELECT * FROM admins WHERE id = ?", (admin_id,)).fetchone()
    )
    db.close()
    return jsonify(admin), 200


@app.route("/admin/<int:admin_id>", methods=["DELETE"])
def delete_admin(admin_id):
    """Delete an admin."""
    db = get_db()

    existing = db.execute("SELECT id FROM admins WHERE id = ?", (admin_id,)).fetchone()
    if existing is None:
        db.close()
        return jsonify({"error": "Admin not found"}), 404

    db.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
    db.commit()
    db.close()
    return "", 204


# ===========================================================================
#  Main
# ===========================================================================

if __name__ == "__main__":
    # Ensure data directory exists (for local dev without Docker volumes)
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    init_db()
    print(f"Directory Service starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=os.environ.get("APP_ENV") == "development")
