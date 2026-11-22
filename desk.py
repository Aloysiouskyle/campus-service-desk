"""SQLite persistence and help-desk workflow rules."""

import sqlite3
from datetime import UTC, datetime, timedelta

STATUSES = ("Open", "In progress", "Resolved")
CATEGORIES = ("IT Support", "Facilities", "Library", "Academic Services", "Student Services")
PRIORITIES = ("Low", "Normal", "High")
TRANSITIONS = {
    "Open": ("In progress",),
    "In progress": ("Open", "Resolved"),
    "Resolved": ("Open",),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    email TEXT PRIMARY KEY COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('staff', 'student'))
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    owner_email TEXT REFERENCES accounts(email),
    assignee_email TEXT REFERENCES accounts(email),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open'
        CHECK (status IN ('Open', 'In progress', 'Resolved')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    author_email TEXT NOT NULL REFERENCES accounts(email),
    author_role TEXT NOT NULL CHECK (author_role IN ('student', 'staff')),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    recipient TEXT NOT NULL REFERENCES accounts(email),
    kind TEXT NOT NULL CHECK (kind IN ('reply', 'status')),
    is_read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notifications_by_recipient ON notifications(recipient, id);
CREATE INDEX IF NOT EXISTS messages_by_ticket ON messages(ticket_id, id);
CREATE INDEX IF NOT EXISTS events_by_ticket ON events(ticket_id, id);
"""

SAMPLES = (
    ("Wi-Fi drops in the main library", "IT Support", "High", "Open",
     "Students on the second floor lose their connection every few minutes."),
    ("Projector flickering in Block B", "Facilities", "Normal", "In progress",
     "The projector in room B12 flickers after ten minutes of use."),
    ("Course registration page won’t load", "Academic Services", "High", "In progress",
     "The registration page stops loading after selecting this semester."),
    ("Renewal unavailable for borrowed book", "Library", "Normal", "Open",
     "The catalogue shows the book as renewable, but the renewal button is missing."),
    ("Replace broken chair in Lab 2", "Facilities", "Low", "Resolved",
     "The chair at workstation 14 has a loose backrest."),
    ("Student portal password reset", "IT Support", "Normal", "Resolved",
     "The reset email does not arrive after a student requests it."),
    ("Campus ID collection hours", "Student Services", "Low", "Open",
     "The hours at the collection desk differ from the posted schedule."),
    ("Printer queue stuck in Lab 1", "IT Support", "Normal", "In progress",
     "Jobs join the queue but never reach the printer."),
    ("Reserve a library study room", "Library", "Low", "Resolved",
     "The booking page lists a room as available but rejects the reservation."),
    ("Missing course on timetable", "Academic Services", "Normal", "Open",
     "The timetable is missing the Wednesday database systems session."),
    ("Water leak near the science block", "Facilities", "High", "Open",
     "Water is collecting along the corridor outside the ground-floor lab."),
    ("Update student sports timetable", "Student Services", "Low", "Resolved",
     "The student portal still shows last semester’s training times."),
)


def timestamp(value=None):
    return (value or datetime.now(UTC)).isoformat(timespec="seconds")


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def add_ticket(db, title, description, category, priority, created_at, owner_email=None):
    ticket_id = db.execute(
        """INSERT INTO tickets(title, description, category, priority, created_at, owner_email)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (title, description, category, priority, created_at, owner_email),
    ).lastrowid
    add_event(db, ticket_id, "Open", "Request submitted.", created_at)
    return ticket_id


def add_event(db, ticket_id, status, note, created_at):
    db.execute(
        "INSERT INTO events(ticket_id, status, note, created_at) VALUES (?, ?, ?, ?)",
        (ticket_id, status, note, created_at),
    )


def claim_ticket(db, ticket_id, staff_email):
    with db:
        # SQLite serializes writers. Only the first claim can match the empty assignee.
        changed = db.execute(
            "UPDATE tickets SET assignee_email = ? WHERE id = ? AND assignee_email IS NULL",
            (staff_email, ticket_id),
        ).rowcount
        ticket = db.execute("SELECT assignee_email, status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if ticket is None:
            return 404
        if ticket["assignee_email"] != staff_email:
            return 409
        if changed:
            add_event(db, ticket_id, ticket["status"], f"Assigned to {staff_email}.", timestamp())
    return 200


def notify(db, ticket_id, recipient, actor, kind):
    if recipient and recipient != actor:
        db.execute("INSERT INTO notifications(ticket_id, recipient, kind) VALUES (?, ?, ?)",
                   (ticket_id, recipient, kind))


def change_status(db, ticket_id, expected_event, status, note, actor):
    # A transaction prevents simultaneous updates from reading the same old status.
    with db:
        db.execute("BEGIN IMMEDIATE")
        ticket = db.execute("SELECT status, owner_email FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if ticket is None:
            return 404
        last_event = db.execute("SELECT max(id) FROM events WHERE ticket_id = ?", (ticket_id,)).fetchone()[0]
        if str(last_event) != expected_event:
            return 409
        if status not in TRANSITIONS[ticket["status"]]:
            return 422
        db.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        add_event(db, ticket_id, status, note, timestamp())
        notify(db, ticket_id, ticket["owner_email"], actor, "status")
    return 200


def init_db(db, seed=False):
    db.executescript(SCHEMA)
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='staff'").fetchone():
            db.execute("INSERT INTO accounts SELECT email, password_hash, 'staff' FROM staff")
            db.execute("DROP TABLE staff")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(tickets)")}
        if "assignee_email" not in columns:
            db.execute("ALTER TABLE tickets ADD COLUMN assignee_email TEXT REFERENCES accounts(email)")
        if "owner_email" not in columns:
            db.execute("ALTER TABLE tickets ADD COLUMN owner_email TEXT REFERENCES accounts(email)")
        db.execute("CREATE INDEX IF NOT EXISTS tickets_by_owner ON tickets(owner_email, status)")
    if seed:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM tickets LIMIT 1").fetchone():
                return
            anchor = datetime(2026, 11, 19, 9, tzinfo=UTC)
            for index in reversed(range(len(SAMPLES))):
                title, category, priority, status, description = SAMPLES[index]
                created = anchor - timedelta(hours=index * 6)
                ticket_id = add_ticket(db, title, description, category, priority, timestamp(created))
                if status != "Open":
                    add_event(db, ticket_id, "In progress", "Assigned to the campus support team.",
                              timestamp(created + timedelta(hours=1)))
                if status == "Resolved":
                    add_event(db, ticket_id, "Resolved", "Support confirmed the issue was resolved.",
                              timestamp(created + timedelta(hours=3)))
                db.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))


def matching_tickets(db, filters, owner_email=None):
    clauses, values = [], []
    if owner_email is not None:
        clauses.append("owner_email = ?")
        values.append(owner_email)
    assignee = filters.get("assignee")
    if assignee == "unassigned":
        clauses.append("assignee_email IS NULL")
    elif assignee:
        clauses.append("assignee_email = ?")
        values.append(assignee)
    for field in ("status", "category", "priority"):
        if filters[field]:
            clauses.append(f"{field} = ?")
            values.append(filters[field])
    if filters["q"]:
        clauses.append("""(instr(lower(title), lower(?)) > 0
                           OR instr(lower(printf('CSD-%04d', id)), lower(?)) > 0)""")
        values.extend([filters["q"]] * 2)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return db.execute("SELECT * FROM tickets" + where + " ORDER BY id DESC", values).fetchall()
