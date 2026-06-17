"""
Notification Service — manages in-app notifications for appointment events.
REST API over HTTP with JSON payloads.
Port: 5003
Database: notifications.db
"""

import os
from datetime import datetime
from flask import Flask, request, jsonify
from init_db import init_db, get_db, DB_PATH

app = Flask(__name__)

PORT = int(os.environ.get("PORT", 5003))


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
#  NOTIFICATIONS
# ===========================================================================

@app.route("/notifications", methods=["POST"])
def create_notification():
    """
    Create a new notification.
    On creation, immediately attempt to "send" it:
      - For 'log' channel: print to stdout and mark as 'sent'.
      - For 'email' channel: stub — mark as 'sent' (no real email).
    """
    data = request.get_json(force=True)

    recipient_type = data.get("recipient_type")
    recipient_id = data.get("recipient_id")
    subject = data.get("subject")
    body = data.get("body")
    channel = data.get("channel", "log")
    appointment_id = data.get("appointment_id")

    if not recipient_type or recipient_id is None or not subject or not body:
        return jsonify({"error": "recipient_type, recipient_id, subject, and body are required"}), 400

    if recipient_type not in ("patient", "doctor"):
        return jsonify({"error": "recipient_type must be 'patient' or 'doctor'"}), 400

    if channel not in ("email", "log"):
        return jsonify({"error": "channel must be 'email' or 'log'"}), 400

    db = get_db()
    now = now_iso()
    cursor = db.execute(
        """INSERT INTO notifications
           (recipient_type, recipient_id, appointment_id, channel, subject, body,
            status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (recipient_type, int(recipient_id), appointment_id, channel,
         subject, body, now, now),
    )
    notification_id = cursor.lastrowid
    db.commit()

    # Attempt to "send" the notification immediately
    send_status = "sent"
    sent_at = now_iso()
    try:
        if channel == "log":
            print(f"[NOTIFICATION] To: {recipient_type}#{recipient_id} | "
                  f"Subject: {subject} | Body: {body}")
        elif channel == "email":
            # Email stub — just log it
            print(f"[EMAIL STUB] To: {recipient_type}#{recipient_id} | "
                  f"Subject: {subject} | Body: {body}")
    except Exception:
        send_status = "failed"
        sent_at = None

    db.execute(
        "UPDATE notifications SET status = ?, sent_at = ?, updated_at = ? WHERE id = ?",
        (send_status, sent_at, now_iso(), notification_id),
    )
    db.commit()

    notification = row_to_dict(
        db.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    )
    db.close()
    return jsonify(notification), 201


@app.route("/notifications", methods=["GET"])
def list_notifications():
    """
    List notifications filtered by recipient_type and recipient_id.
    Query params: recipient_type, recipient_id
    """
    recipient_type = request.args.get("recipient_type")
    recipient_id = request.args.get("recipient_id")

    db = get_db()

    query = "SELECT * FROM notifications"
    params = []
    conditions = []

    if recipient_type:
        conditions.append("recipient_type = ?")
        params.append(recipient_type)
    if recipient_id:
        conditions.append("recipient_id = ?")
        params.append(int(recipient_id))

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY created_at DESC"

    rows = db.execute(query, params).fetchall()
    db.close()
    return jsonify(rows_to_list(rows)), 200


@app.route("/notifications/<int:notification_id>", methods=["PATCH"])
def update_notification(notification_id):
    """
    Update a notification's status (primarily to mark as 'read').
    """
    data = request.get_json(force=True)
    db = get_db()

    existing = db.execute(
        "SELECT * FROM notifications WHERE id = ?", (notification_id,)
    ).fetchone()

    if existing is None:
        db.close()
        return jsonify({"error": "Notification not found"}), 404

    new_status = data.get("status")
    if not new_status:
        db.close()
        return jsonify({"error": "status is required"}), 400

    if new_status not in ("pending", "sent", "failed", "read"):
        db.close()
        return jsonify({"error": "status must be one of: pending, sent, failed, read"}), 400

    now = now_iso()
    db.execute(
        "UPDATE notifications SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, now, notification_id),
    )
    db.commit()

    notification = row_to_dict(
        db.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    )
    db.close()
    return jsonify(notification), 200


# ===========================================================================
#  Main
# ===========================================================================

if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    init_db()
    print(f"Notification Service starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=os.environ.get("APP_ENV") == "development")
