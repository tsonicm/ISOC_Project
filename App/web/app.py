"""
Web/BFF — Backend-for-Frontend layer.
Serves Jinja2 HTML templates, manages sessions, orchestrates backend API calls.
Port: 8080
Database: web.db (users/sessions only)
Calls: Directory Service, Appointment Service, Notification Service
"""

import os
from functools import wraps
from datetime import datetime
import requests as http_client
from flask import (
    Flask, request, render_template, redirect, url_for,
    flash, session, jsonify,
)
from werkzeug.security import check_password_hash, generate_password_hash
from init_db import init_db, seed_data, get_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")

PORT = int(os.environ.get("PORT", 8080))
DIRECTORY_SERVICE_BASE_URL = os.environ.get(
    "DIRECTORY_SERVICE_BASE_URL", "http://directory-service:5002"
)
APPOINTMENT_SERVICE_BASE_URL = os.environ.get(
    "APPOINTMENT_SERVICE_BASE_URL", "http://appointment-service:5001"
)
NOTIFICATION_SERVICE_BASE_URL = os.environ.get(
    "NOTIFICATION_SERVICE_BASE_URL", "http://notification-service:5003"
)


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def require_role(*roles):
    """Decorator to enforce role-based access on routes."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if "role" not in session:
                flash("Please log in first.", "warning")
                return redirect(url_for("login_page"))
            if session["role"] not in roles:
                flash("Access denied.", "error")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def get_notification_count():
    """Get unread notification count for the current user (for nav badge)."""
    if "role" not in session:
        return 0
    try:
        resp = http_client.get(
            f"{NOTIFICATION_SERVICE_BASE_URL}/notifications",
            params={
                "recipient_type": session["role"],
                "recipient_id": session["entity_id"],
            },
            timeout=3,
        )
        if resp.status_code == 200:
            notifications = resp.json()
            return sum(1 for n in notifications if n.get("status") != "read")
    except Exception:
        pass
    return 0


@app.context_processor
def inject_globals():
    """Inject session data and notification count into all templates."""
    return {
        "current_user": {
            "email": session.get("email"),
            "role": session.get("role"),
            "entity_id": session.get("entity_id"),
            "user_id": session.get("user_id"),
        } if "role" in session else None,
        "notification_count": get_notification_count(),
    }


# ===========================================================================
#  AUTH ROUTES
# ===========================================================================

@app.route("/", methods=["GET"])
def login_page():
    """Show login page or redirect to dashboard if already authenticated."""
    if "role" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    """Authenticate user."""
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for("login_page"))

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    db.close()

    if user is None or not check_password_hash(user["password"], password):
        flash("Invalid email or password.", "error")
        return redirect(url_for("login_page"))

    session["user_id"] = user["id"]
    session["email"] = user["email"]
    session["role"] = user["role"]
    session["entity_id"] = user["entity_id"]

    flash(f"Welcome! Logged in as {user['role']}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["GET"])
def logout():
    """Clear session and redirect to login."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login_page"))


@app.route("/dashboard", methods=["GET"])
@require_role("patient", "doctor", "admin")
def dashboard():
    """Post-login landing page. Redirects to role-specific default view."""
    role = session["role"]
    if role == "patient":
        return redirect(url_for("patient_doctors"))
    elif role == "doctor":
        return redirect(url_for("doctor_appointments"))
    elif role == "admin":
        return redirect(url_for("admin_doctors"))
    return render_template("dashboard.html")


# ===========================================================================
#  PATIENT ROUTES
# ===========================================================================

@app.route("/patient/doctors", methods=["GET"])
@require_role("patient")
def patient_doctors():
    """List all active doctors."""
    doctors = []
    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors",
            params={"active": 1},
            timeout=5,
        )
        if resp.status_code == 200:
            doctors = resp.json()
    except Exception as e:
        flash(f"Could not load doctors: {e}", "error")

    return render_template("patient/doctors.html", doctors=doctors)


@app.route("/patient/doctors/<int:doctor_id>/availability", methods=["GET"])
@require_role("patient")
def patient_doctor_availability(doctor_id):
    """Show doctor details and available time slots."""
    doctor = {}
    slots = []

    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}", timeout=5
        )
        if resp.status_code == 200:
            doctor = resp.json()
        else:
            flash("Doctor not found.", "error")
            return redirect(url_for("patient_doctors"))
    except Exception as e:
        flash(f"Could not load doctor details: {e}", "error")

    # Fetch availability
    params = {"doctor_id": doctor_id}
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to

    try:
        resp = http_client.get(
            f"{APPOINTMENT_SERVICE_BASE_URL}/availability",
            params=params,
            timeout=5,
        )
        if resp.status_code == 200:
            slots = resp.json()
    except Exception as e:
        flash(f"Could not load availability: {e}", "error")

    return render_template(
        "patient/availability.html",
        doctor=doctor, slots=slots,
        date_from=date_from, date_to=date_to,
    )


@app.route("/patient/appointments", methods=["GET"])
@require_role("patient")
def patient_appointments():
    """List patient's own appointments."""
    appointments = []
    try:
        resp = http_client.get(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments",
            params={"patient_id": session["entity_id"]},
            timeout=5,
        )
        if resp.status_code == 200:
            appointments = resp.json()
    except Exception as e:
        flash(f"Could not load appointments: {e}", "error")

    # Enrich with doctor names
    for appt in appointments:
        try:
            resp = http_client.get(
                f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{appt['doctor_id']}", timeout=3
            )
            if resp.status_code == 200:
                appt["doctor_name"] = resp.json().get("full_name", "Unknown")
            else:
                appt["doctor_name"] = "Unknown"
        except Exception:
            appt["doctor_name"] = "Unknown"

    return render_template("patient/appointments.html", appointments=appointments)


@app.route("/patient/appointments", methods=["POST"])
@require_role("patient")
def patient_create_appointment():
    """Create a new appointment."""
    doctor_id = request.form.get("doctor_id")
    start_datetime = request.form.get("start_datetime")
    end_datetime = request.form.get("end_datetime")
    reason = request.form.get("reason", "")

    if not doctor_id or not start_datetime or not end_datetime:
        flash("All fields are required.", "error")
        return redirect(request.referrer or url_for("patient_doctors"))

    try:
        resp = http_client.post(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments",
            json={
                "patient_id": session["entity_id"],
                "doctor_id": int(doctor_id),
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "reason": reason,
            },
            timeout=5,
        )
        if resp.status_code == 201:
            flash("Appointment created successfully! Status: pending.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not create appointment: {error}", "error")
    except Exception as e:
        flash(f"Error creating appointment: {e}", "error")

    return redirect(url_for("patient_appointments"))


@app.route("/patient/appointments/<int:appointment_id>/cancel", methods=["POST"])
@require_role("patient")
def patient_cancel_appointment(appointment_id):
    """Cancel a patient's own appointment."""
    # Verify ownership
    try:
        resp = http_client.get(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments/{appointment_id}", timeout=5
        )
        if resp.status_code != 200:
            flash("Appointment not found.", "error")
            return redirect(url_for("patient_appointments"))
        appt = resp.json()
        if appt["patient_id"] != session["entity_id"]:
            flash("You can only cancel your own appointments.", "error")
            return redirect(url_for("patient_appointments"))
    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for("patient_appointments"))

    # Cancel
    try:
        resp = http_client.patch(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments/{appointment_id}",
            json={"status": "cancelled"},
            timeout=5,
        )
        if resp.status_code == 200:
            flash("Appointment cancelled.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not cancel: {error}", "error")
    except Exception as e:
        flash(f"Error cancelling appointment: {e}", "error")

    return redirect(url_for("patient_appointments"))


# ===========================================================================
#  DOCTOR ROUTES
# ===========================================================================

@app.route("/doctor/appointments", methods=["GET"])
@require_role("doctor")
def doctor_appointments():
    """List doctor's appointments."""
    appointments = []
    try:
        resp = http_client.get(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments",
            params={"doctor_id": session["entity_id"]},
            timeout=5,
        )
        if resp.status_code == 200:
            appointments = resp.json()
    except Exception as e:
        flash(f"Could not load appointments: {e}", "error")

    # Enrich with patient names
    for appt in appointments:
        try:
            resp = http_client.get(
                f"{DIRECTORY_SERVICE_BASE_URL}/patients/{appt['patient_id']}", timeout=3
            )
            if resp.status_code == 200:
                appt["patient_name"] = resp.json().get("full_name", "Unknown")
            else:
                appt["patient_name"] = "Unknown"
        except Exception:
            appt["patient_name"] = "Unknown"

    return render_template("doctor/appointments.html", appointments=appointments)


@app.route("/doctor/appointments/<int:appointment_id>/confirm", methods=["POST"])
@require_role("doctor")
def doctor_confirm_appointment(appointment_id):
    """Doctor confirms a pending appointment."""
    try:
        resp = http_client.patch(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments/{appointment_id}",
            json={"status": "confirmed"},
            timeout=5,
        )
        if resp.status_code == 200:
            flash("Appointment confirmed.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not confirm: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("doctor_appointments"))


@app.route("/doctor/appointments/<int:appointment_id>/cancel", methods=["POST"])
@require_role("doctor")
def doctor_cancel_appointment(appointment_id):
    """Doctor cancels an appointment."""
    try:
        resp = http_client.patch(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments/{appointment_id}",
            json={"status": "cancelled"},
            timeout=5,
        )
        if resp.status_code == 200:
            flash("Appointment cancelled.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not cancel: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("doctor_appointments"))


# ===========================================================================
#  ADMIN ROUTES
# ===========================================================================

@app.route("/admin/doctors", methods=["GET"])
@require_role("admin")
def admin_doctors():
    """List all doctors for admin management."""
    doctors = []
    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors", timeout=5
        )
        if resp.status_code == 200:
            doctors = resp.json()
    except Exception as e:
        flash(f"Could not load doctors: {e}", "error")

    return render_template("admin/doctors.html", doctors=doctors)


@app.route("/admin/doctors/new", methods=["GET"])
@require_role("admin")
def admin_doctor_form_new():
    """Show form to create a new doctor."""
    return render_template("admin/doctor_form.html", doctor=None)


@app.route("/admin/doctors/<int:doctor_id>/edit", methods=["GET"])
@require_role("admin")
def admin_doctor_form_edit(doctor_id):
    """Show form to edit a doctor."""
    doctor = {}
    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}", timeout=5
        )
        if resp.status_code == 200:
            doctor = resp.json()
        else:
            flash("Doctor not found.", "error")
            return redirect(url_for("admin_doctors"))
    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for("admin_doctors"))

    return render_template("admin/doctor_form.html", doctor=doctor)


@app.route("/admin/doctors", methods=["POST"])
@require_role("admin")
def admin_create_doctor():
    """Create a new doctor and optionally a user account."""
    full_name = request.form.get("full_name", "").strip()
    specialization = request.form.get("specialization", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip()

    if not full_name or not email:
        flash("Name and email are required.", "error")
        return redirect(url_for("admin_doctor_form_new"))

    try:
        resp = http_client.post(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors",
            json={
                "full_name": full_name,
                "specialization": specialization,
                "email": email,
                "phone": phone,
            },
            timeout=5,
        )
        if resp.status_code == 201:
            doctor_data = resp.json()
            # Create user account if password provided
            if password:
                db = get_db()
                db.execute(
                    "INSERT INTO users (email, password, role, entity_id) VALUES (?, ?, ?, ?)",
                    (email, generate_password_hash(password), "doctor", doctor_data["id"]),
                )
                db.commit()
                db.close()
            flash(f"Doctor '{full_name}' created successfully.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not create doctor: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("admin_doctors"))


@app.route("/admin/doctors/<int:doctor_id>", methods=["POST"])
@require_role("admin")
def admin_update_doctor(doctor_id):
    """Update a doctor's profile."""
    data = {}
    for field in ["full_name", "specialization", "email", "phone"]:
        val = request.form.get(field, "").strip()
        if val:
            data[field] = val

    active = request.form.get("active")
    if active is not None:
        data["active"] = int(active)

    try:
        resp = http_client.patch(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}",
            json=data,
            timeout=5,
        )
        if resp.status_code == 200:
            flash("Doctor updated.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not update doctor: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("admin_doctors"))


@app.route("/admin/doctors/<int:doctor_id>/hours", methods=["GET"])
@require_role("admin")
def admin_doctor_hours(doctor_id):
    """View and manage a doctor's working hours."""
    doctor = {}
    working_hours = []

    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}", timeout=5
        )
        if resp.status_code == 200:
            doctor = resp.json()
    except Exception as e:
        flash(f"Error loading doctor: {e}", "error")

    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}/working-hours", timeout=5
        )
        if resp.status_code == 200:
            working_hours = resp.json()
    except Exception as e:
        flash(f"Error loading working hours: {e}", "error")

    # Weekday names for display
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    return render_template(
        "admin/doctor_hours.html",
        doctor=doctor, working_hours=working_hours,
        weekday_names=weekday_names,
    )


@app.route("/admin/doctors/<int:doctor_id>/hours", methods=["POST"])
@require_role("admin")
def admin_create_hours(doctor_id):
    """Create a working hours entry for a doctor."""
    data = {
        "weekday": int(request.form.get("weekday", 0)),
        "start_time": request.form.get("start_time", ""),
        "end_time": request.form.get("end_time", ""),
        "slot_length_minutes": int(request.form.get("slot_length_minutes", 30)),
    }

    break_start = request.form.get("break_start_time", "").strip()
    break_end = request.form.get("break_end_time", "").strip()
    if break_start:
        data["break_start_time"] = break_start
    if break_end:
        data["break_end_time"] = break_end

    try:
        resp = http_client.post(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}/working-hours",
            json=data,
            timeout=5,
        )
        if resp.status_code == 201:
            flash("Working hours added.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not add working hours: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("admin_doctor_hours", doctor_id=doctor_id))


@app.route("/admin/doctors/<int:doctor_id>/hours/delete", methods=["POST"])
@require_role("admin")
def admin_delete_hours(doctor_id):
    """Delete a working hours entry by weekday."""
    weekday = request.form.get("weekday")

    try:
        resp = http_client.delete(
            f"{DIRECTORY_SERVICE_BASE_URL}/doctors/{doctor_id}/working-hours",
            params={"weekday": weekday},
            timeout=5,
        )
        if resp.status_code == 204:
            flash("Working hours deleted.", "success")
        else:
            error = resp.json().get("error", "Unknown error") if resp.text else "Unknown error"
            flash(f"Could not delete: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("admin_doctor_hours", doctor_id=doctor_id))


@app.route("/admin/patients", methods=["GET"])
@require_role("admin")
def admin_patients():
    """List all patients for admin management."""
    patients = []
    try:
        resp = http_client.get(
            f"{DIRECTORY_SERVICE_BASE_URL}/patients", timeout=5
        )
        if resp.status_code == 200:
            patients = resp.json()
    except Exception as e:
        flash(f"Could not load patients: {e}", "error")

    return render_template("admin/patients.html", patients=patients)


@app.route("/admin/patients/new", methods=["GET"])
@require_role("admin")
def admin_patient_form_new():
    """Show form to create a new patient."""
    return render_template("admin/patient_form.html", patient=None)


@app.route("/admin/patients", methods=["POST"])
@require_role("admin")
def admin_create_patient():
    """Create a new patient and optionally a user account."""
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip()

    if not full_name or not email:
        flash("Name and email are required.", "error")
        return redirect(url_for("admin_patient_form_new"))

    try:
        resp = http_client.post(
            f"{DIRECTORY_SERVICE_BASE_URL}/patients",
            json={"full_name": full_name, "email": email, "phone": phone},
            timeout=5,
        )
        if resp.status_code == 201:
            patient_data = resp.json()
            if password:
                db = get_db()
                db.execute(
                    "INSERT INTO users (email, password, role, entity_id) VALUES (?, ?, ?, ?)",
                    (email, generate_password_hash(password), "patient", patient_data["id"]),
                )
                db.commit()
                db.close()
            flash(f"Patient '{full_name}' created successfully.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not create patient: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(url_for("admin_patients"))


@app.route("/admin/appointments/<int:appointment_id>/confirm", methods=["POST"])
@require_role("admin")
def admin_confirm_appointment(appointment_id):
    """Admin confirms a pending appointment."""
    try:
        resp = http_client.patch(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments/{appointment_id}",
            json={"status": "confirmed"},
            timeout=5,
        )
        if resp.status_code == 200:
            flash("Appointment confirmed.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not confirm: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(request.referrer or url_for("admin_doctors"))


@app.route("/admin/appointments/<int:appointment_id>/cancel", methods=["POST"])
@require_role("admin")
def admin_cancel_appointment(appointment_id):
    """Admin cancels an appointment."""
    try:
        resp = http_client.patch(
            f"{APPOINTMENT_SERVICE_BASE_URL}/appointments/{appointment_id}",
            json={"status": "cancelled"},
            timeout=5,
        )
        if resp.status_code == 200:
            flash("Appointment cancelled.", "success")
        else:
            error = resp.json().get("error", "Unknown error")
            flash(f"Could not cancel: {error}", "error")
    except Exception as e:
        flash(f"Error: {e}", "error")

    return redirect(request.referrer or url_for("admin_doctors"))


# ===========================================================================
#  NOTIFICATIONS (shared by patient/doctor)
# ===========================================================================

@app.route("/notifications", methods=["GET"])
@require_role("patient", "doctor")
def notifications_page():
    """List notifications for the current user."""
    notifications = []
    try:
        resp = http_client.get(
            f"{NOTIFICATION_SERVICE_BASE_URL}/notifications",
            params={
                "recipient_type": session["role"],
                "recipient_id": session["entity_id"],
            },
            timeout=5,
        )
        if resp.status_code == 200:
            notifications = resp.json()
    except Exception as e:
        flash(f"Could not load notifications: {e}", "error")

    return render_template("notifications.html", notifications=notifications)


@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
@require_role("patient", "doctor")
def mark_notification_read(notification_id):
    """Mark a notification as read."""
    try:
        http_client.patch(
            f"{NOTIFICATION_SERVICE_BASE_URL}/notifications/{notification_id}",
            json={"status": "read"},
            timeout=5,
        )
    except Exception:
        pass

    return redirect(url_for("notifications_page"))


# ===========================================================================
#  Main
# ===========================================================================

if __name__ == "__main__":
    db_dir = os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else "."
    os.makedirs(db_dir, exist_ok=True)
    init_db()
    seed_data()
    print(f"Web/BFF starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=os.environ.get("APP_ENV") == "development")
