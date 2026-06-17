"""
Appointment Service — manages appointments and availability calculation.
REST API over HTTP with JSON payloads.
Port: 5001
Database: appointments.db
Calls: Directory Service (working hours), Notification Service (notifications)
"""

import os
from datetime import datetime, timedelta
import requests as http_client
from flask import Flask, request, jsonify
from init_db import init_db, get_db, DB_PATH

app = Flask(__name__)

PORT = int(os.environ.get("PORT", 5001))
DIRECTORY_SERVICE_BASE_URL = os.environ.get(
    "DIRECTORY_SERVICE_BASE_URL", "http://directory-service:5002"
)
NOTIFICATION_SERVICE_BASE_URL = os.environ.get(
    "NOTIFICATION_SERVICE_BASE_URL", "http://notification-service:5003"
)

# Valid appointment state transitions
VALID_TRANSITIONS = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["cancelled"],
    "cancelled": [],  # terminal state
}


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


def format_dt_str(dt_str):
    try:
        dt = datetime.strptime(dt_str[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%Y-%m-%d at %H:%M")
    except Exception:
        return dt_str


def send_notification(recipient_type, recipient_id, subject, body, appointment_id=None):
    """
    Fire-and-forget notification to Notification Service.
    Best-effort: failures are logged but do not block the main operation.
    """
    try:
        payload = {
            "recipient_type": recipient_type,
            "recipient_id": recipient_id,
            "subject": subject,
            "body": body,
            "channel": "log",
        }
        if appointment_id is not None:
            payload["appointment_id"] = appointment_id

        http_client.post(
            f"{NOTIFICATION_SERVICE_BASE_URL}/notifications",
            json=payload,
            timeout=5,
        )
    except Exception as e:
        print(f"[WARNING] Failed to send notification: {e}")


def check_overlap(db, doctor_id, start_dt, end_dt, exclude_id=None):
    """
    Check if a proposed time range overlaps with any existing non-cancelled
    appointment for the given doctor. Returns True if there IS an overlap.
    """
    query = """
        SELECT COUNT(*) as cnt FROM appointments
        WHERE doctor_id = ?
          AND status != 'cancelled'
          AND start_datetime < ?
          AND end_datetime > ?
    """
    params = [doctor_id, end_dt, start_dt]

    if exclude_id is not None:
        query += " AND appointment_id != ?"
        params.append(exclude_id)

    result = db.execute(query, params).fetchone()
    return result["cnt"] > 0


# ===========================================================================
#  APPOINTMENTS
# ===========================================================================

@app.route("/appointments", methods=["GET"])
def list_appointments():
    """
    List appointments with optional filters.
    Query params: patient_id, doctor_id, date_from, date_to
    """
    db = get_db()

    query = "SELECT * FROM appointments"
    params = []
    conditions = []

    patient_id = request.args.get("patient_id")
    doctor_id = request.args.get("doctor_id")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    if patient_id:
        conditions.append("patient_id = ?")
        params.append(int(patient_id))
    if doctor_id:
        conditions.append("doctor_id = ?")
        params.append(int(doctor_id))
    if date_from:
        conditions.append("start_datetime >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("start_datetime <= ?")
        params.append(date_to)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY start_datetime ASC"

    rows = db.execute(query, params).fetchall()
    db.close()
    return jsonify(rows_to_list(rows)), 200


@app.route("/appointments", methods=["POST"])
def create_appointment():
    """
    Create a new appointment.
    Validates:
      - Required fields present
      - No double-booking for the doctor
    Triggers notification to patient and doctor on success.
    """
    data = request.get_json(force=True)

    patient_id = data.get("patient_id")
    doctor_id = data.get("doctor_id")
    start_datetime = data.get("start_datetime")
    end_datetime = data.get("end_datetime")
    reason = data.get("reason", "")

    if not all([patient_id, doctor_id, start_datetime, end_datetime]):
        return jsonify({"error": "patient_id, doctor_id, start_datetime, and end_datetime are required"}), 400

    patient_id = int(patient_id)
    doctor_id = int(doctor_id)

    # Validate datetime format
    try:
        start_dt = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M:%S")
        end_dt = datetime.strptime(end_datetime, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return jsonify({"error": "Datetime must be in format YYYY-MM-DDTHH:MM:SS"}), 400

    if end_dt <= start_dt:
        return jsonify({"error": "end_datetime must be after start_datetime"}), 400

    # Verify patient exists via Directory Service
    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/patients/{patient_id}", timeout=5
        )
        if resp.status_code != 200:
            return jsonify({"error": "Patient not found"}), 404
    except Exception as e:
        return jsonify({"error": f"Cannot reach Directory Service: {e}"}), 503

    # Verify doctor exists and is active via Directory Service
    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}", timeout=5
        )
        if resp.status_code != 200:
            return jsonify({"error": "Doctor not found"}), 404
        doctor_data = resp.json()
        if not doctor_data.get("active", True):
            return jsonify({"error": "Doctor is not active"}), 400
    except http_client.exceptions.RequestException as e:
        return jsonify({"error": f"Cannot reach Directory Service: {e}"}), 503

    # Check for double-booking
    db = get_db()
    if check_overlap(db, doctor_id, start_datetime, end_datetime):
        db.close()
        return jsonify({"error": "Time slot is already booked (double-booking prevented)"}), 409

    # Create appointment in PENDING state
    now = now_iso()
    cursor = db.execute(
        """INSERT INTO appointments
           (patient_id, doctor_id, start_datetime, end_datetime, status, reason,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (patient_id, doctor_id, start_datetime, end_datetime, reason, now, now),
    )
    appointment_id = cursor.lastrowid
    db.commit()

    appointment = row_to_dict(
        db.execute(
            "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
        ).fetchone()
    )
    db.close()

    # Send notifications (best-effort)
    fmt_start = format_dt_str(start_datetime)
    send_notification(
        "patient", patient_id,
        "Appointment Created",
        f"Your appointment on {fmt_start} has been created and is pending confirmation.",
        appointment_id,
    )
    send_notification(
        "doctor", doctor_id,
        "New Appointment Pending",
        f"A new appointment on {fmt_start} is pending your confirmation.",
        appointment_id,
    )

    return jsonify(appointment), 201


@app.route("/appointments/<int:appointment_id>", methods=["GET"])
def get_appointment(appointment_id):
    """Get a single appointment by ID."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
    ).fetchone()
    db.close()

    if row is None:
        return jsonify({"error": "Appointment not found"}), 404
    return jsonify(row_to_dict(row)), 200


@app.route("/appointments/<int:appointment_id>", methods=["PATCH"])
def update_appointment(appointment_id):
    """
    Update an appointment's status.
    Enforces valid state transitions:
      pending   → confirmed, cancelled
      confirmed → cancelled
      cancelled → (nothing — terminal)
    """
    data = request.get_json(force=True)
    new_status = data.get("status")

    if not new_status:
        return jsonify({"error": "status is required"}), 400

    new_status = new_status.lower()
    if new_status not in ("confirmed", "cancelled"):
        return jsonify({"error": "status must be 'confirmed' or 'cancelled'"}), 400

    db = get_db()
    row = db.execute(
        "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
    ).fetchone()

    if row is None:
        db.close()
        return jsonify({"error": "Appointment not found"}), 404

    current_status = row["status"]
    allowed = VALID_TRANSITIONS.get(current_status, [])

    if new_status not in allowed:
        db.close()
        return jsonify({
            "error": f"Cannot transition from '{current_status}' to '{new_status}'. "
                     f"Allowed transitions: {allowed}"
        }), 422

    now = now_iso()
    db.execute(
        "UPDATE appointments SET status = ?, updated_at = ? WHERE appointment_id = ?",
        (new_status, now, appointment_id),
    )
    db.commit()

    appointment = row_to_dict(
        db.execute(
            "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
        ).fetchone()
    )
    db.close()

    # Send notifications based on the new status
    patient_id = appointment["patient_id"]
    doctor_id = appointment["doctor_id"]
    start = appointment["start_datetime"]
    fmt_start = format_dt_str(start)

    if new_status == "confirmed":
        send_notification(
            "patient", patient_id,
            "Appointment Confirmed",
            f"Your appointment on {fmt_start} has been confirmed.",
            appointment_id,
        )
    elif new_status == "cancelled":
        send_notification(
            "patient", patient_id,
            "Appointment Cancelled",
            f"Your appointment on {fmt_start} has been cancelled.",
            appointment_id,
        )
        send_notification(
            "doctor", doctor_id,
            "Appointment Cancelled",
            f"The appointment on {fmt_start} has been cancelled.",
            appointment_id,
        )

    return jsonify(appointment), 200


# ===========================================================================
#  AVAILABILITY
# ===========================================================================

@app.route("/availability", methods=["GET"])
def get_availability():
    """
    Compute available time slots for a doctor in a date range.
    Required query params: doctor_id
    Optional query params: date_from, date_to (default: today + 7 days)
    
    Algorithm:
      1. Fetch doctor's working hours from Directory Service.
      2. For each day in the range, find the matching weekday schedule.
      3. Generate time slots based on slot_length_minutes.
      4. Exclude slots that overlap with existing non-cancelled appointments.
      5. Exclude break periods.
      6. Return list of available slots.
    """
    doctor_id = request.args.get("doctor_id")
    if not doctor_id:
        return jsonify({"error": "doctor_id query param is required"}), 400

    doctor_id = int(doctor_id)

    # Default date range: today → today + 7 days
    date_from_str = request.args.get("date_from")
    date_to_str = request.args.get("date_to")

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "date_from must be YYYY-MM-DD"}), 400
    else:
        date_from = today

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "date_to must be YYYY-MM-DD"}), 400
    else:
        date_to = date_from + timedelta(days=7)

    # Fetch working hours from Directory Service
    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}/working-hours",
            timeout=5,
        )
        if resp.status_code != 200:
            return jsonify({"error": "Could not fetch working hours"}), 502
        working_hours = resp.json()
    except Exception as e:
        return jsonify({"error": f"Cannot reach Directory Service: {e}"}), 503

    # Index working hours by weekday
    wh_by_weekday = {}
    for wh in working_hours:
        wh_by_weekday[wh["weekday"]] = wh

    # Fetch existing non-cancelled appointments in the date range
    db = get_db()
    existing_appointments = rows_to_list(
        db.execute(
            """SELECT start_datetime, end_datetime FROM appointments
               WHERE doctor_id = ?
                 AND status != 'cancelled'
                 AND start_datetime >= ?
                 AND start_datetime <= ?
               ORDER BY start_datetime""",
            (doctor_id, date_from.strftime("%Y-%m-%dT%H:%M:%S"),
             (date_to + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")),
        ).fetchall()
    )
    db.close()

    # Build set of booked slots for quick lookup
    booked_slots = set()
    for appt in existing_appointments:
        booked_slots.add((appt["start_datetime"], appt["end_datetime"]))

    # Generate available slots
    available_slots = []
    current_date = date_from

    while current_date <= date_to:
        weekday = current_date.weekday()  # 0=Monday, 6=Sunday
        wh = wh_by_weekday.get(weekday)

        if wh:
            # Parse working hours times
            try:
                day_start = datetime.strptime(
                    f"{current_date.strftime('%Y-%m-%d')}T{wh['start_time']}:00",
                    "%Y-%m-%dT%H:%M:%S",
                )
                day_end = datetime.strptime(
                    f"{current_date.strftime('%Y-%m-%d')}T{wh['end_time']}:00",
                    "%Y-%m-%dT%H:%M:%S",
                )
            except ValueError:
                # Try with seconds already included
                day_start = datetime.strptime(
                    f"{current_date.strftime('%Y-%m-%d')}T{wh['start_time']}",
                    "%Y-%m-%dT%H:%M:%S",
                )
                day_end = datetime.strptime(
                    f"{current_date.strftime('%Y-%m-%d')}T{wh['end_time']}",
                    "%Y-%m-%dT%H:%M:%S",
                )

            slot_duration = timedelta(minutes=wh["slot_length_minutes"])

            # Parse break times if present
            break_start = None
            break_end = None
            if wh.get("break_start_time") and wh.get("break_end_time"):
                try:
                    break_start = datetime.strptime(
                        f"{current_date.strftime('%Y-%m-%d')}T{wh['break_start_time']}:00",
                        "%Y-%m-%dT%H:%M:%S",
                    )
                    break_end = datetime.strptime(
                        f"{current_date.strftime('%Y-%m-%d')}T{wh['break_end_time']}:00",
                        "%Y-%m-%dT%H:%M:%S",
                    )
                except ValueError:
                    break_start = datetime.strptime(
                        f"{current_date.strftime('%Y-%m-%d')}T{wh['break_start_time']}",
                        "%Y-%m-%dT%H:%M:%S",
                    )
                    break_end = datetime.strptime(
                        f"{current_date.strftime('%Y-%m-%d')}T{wh['break_end_time']}",
                        "%Y-%m-%dT%H:%M:%S",
                    )

            # Generate slots
            slot_start = day_start
            while slot_start + slot_duration <= day_end:
                slot_end = slot_start + slot_duration

                # Check if slot falls in break period
                in_break = False
                if break_start and break_end:
                    if slot_start < break_end and slot_end > break_start:
                        in_break = True

                if not in_break:
                    start_str = slot_start.strftime("%Y-%m-%dT%H:%M:%S")
                    end_str = slot_end.strftime("%Y-%m-%dT%H:%M:%S")

                    # Check if slot is booked
                    if (start_str, end_str) not in booked_slots:
                        # Also do a precise overlap check against all existing appointments
                        is_booked = False
                        for appt in existing_appointments:
                            if appt["start_datetime"] < end_str and appt["end_datetime"] > start_str:
                                is_booked = True
                                break

                        if not is_booked:
                            available_slots.append({
                                "date": current_date.strftime("%Y-%m-%d"),
                                "start_time": slot_start.strftime("%H:%M"),
                                "end_time": slot_end.strftime("%H:%M"),
                                "start_datetime": start_str,
                                "end_datetime": end_str,
                            })

                slot_start = slot_end

        current_date += timedelta(days=1)

    return jsonify(available_slots), 200


# ===========================================================================
#  Main
# ===========================================================================

if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    init_db()
    print(f"Appointment Service starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=os.environ.get("APP_ENV") == "development")
