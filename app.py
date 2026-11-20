"""Flask entry point and HTTP routes for Campus Service Desk."""

import csv
import hmac
import io
import os
import secrets
from datetime import datetime
from pathlib import Path

import click
from flask import (
    Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for,
)

import desk


def create_app(config=None):
    app = Flask(__name__, static_folder="public/assets", static_url_path="/assets")
    app.config.from_mapping(
        DATABASE=os.environ.get("CSD_DATABASE", str(Path(app.instance_path) / "desk.sqlite3")),
        SECRET_KEY=os.environ.get("CSD_SECRET_KEY") or secrets.token_hex(32),
        READ_ONLY=os.environ.get("VERCEL") == "1" or os.environ.get("CSD_READ_ONLY") == "1",
        MAX_CONTENT_LENGTH=24 * 1024,
    )
    app.config.update(config or {})

    def database():
        if "db" not in g:
            if app.config["READ_ONLY"]:
                g.db = desk.connect(":memory:")
                desk.init_db(g.db, seed=True)
            else:
                g.db = desk.connect(app.config["DATABASE"])
        return g.db

    if not app.config["READ_ONLY"]:
        path = Path(app.config["DATABASE"])
        path.parent.mkdir(parents=True, exist_ok=True)
        db = desk.connect(path)
        try:
            desk.init_db(db)
        finally:
            db.close()

    @app.teardown_appcontext
    def close_database(error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.cli.command("seed")
    def seed():
        """Load fictional tickets into an empty database."""
        if app.config["READ_ONLY"]:
            raise click.ClickException("The hosted preview already includes sample tickets.")
        desk.init_db(database(), seed=True)
        click.echo("Sample data initialized. Existing tickets were preserved.")

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    @app.before_request
    def protect_writes():
        if request.method == "POST":
            if app.config["READ_ONLY"]:
                abort(403, "The hosted preview is read-only.")
            token = session.get("csrf")
            if not token or not hmac.compare_digest(token.encode(), request.form.get("csrf", "").encode()):
                abort(400, "The form expired. Reload the page and try again.")

    @app.context_processor
    def template_values():
        return dict(statuses=desk.STATUSES, categories=desk.CATEGORIES, priorities=desk.PRIORITIES,
                    read_only=app.config["READ_ONLY"], csrf_token=csrf_token)

    @app.template_filter("reference")
    def reference(ticket_id):
        return f"CSD-{ticket_id:04d}"

    @app.template_filter("date")
    def short_date(iso_date):
        value = datetime.fromisoformat(iso_date)
        return f"{value.day} {value:%b %Y}"

    @app.template_filter("slug")
    def slug(value):
        return value.lower().replace(" ", "-")

    def current_filters():
        return {
            "q": request.args.get("q", "").strip()[:120],
            "status": request.args.get("status", ""),
            "category": request.args.get("category", ""),
            "priority": request.args.get("priority", ""),
        }

    @app.get("/")
    def dashboard():
        db = database()
        filters = current_filters()
        counts = dict(db.execute("SELECT status, count(*) FROM tickets GROUP BY status").fetchall())
        return render_template("dashboard.html", tickets=desk.matching_tickets(db, filters),
                               filters=filters, counts=counts, total=sum(counts.values()))

    @app.route("/requests/new", methods=["GET", "POST"])
    def create_ticket():
        if app.config["READ_ONLY"]:
            abort(403, "Run the project locally to submit requests.")
        data, errors = {}, {}
        if request.method == "POST":
            data = {key: request.form.get(key, "").strip() for key in
                    ("title", "description", "category", "priority")}
            if not 5 <= len(data["title"]) <= 120:
                errors["title"] = "Enter a title between 5 and 120 characters."
            if not 10 <= len(data["description"]) <= 2000:
                errors["description"] = "Enter a description between 10 and 2,000 characters."
            if data["category"] not in desk.CATEGORIES:
                errors["category"] = "Choose a category."
            if data["priority"] not in desk.PRIORITIES:
                errors["priority"] = "Choose a priority."
            if not errors:
                db = database()
                with db:
                    ticket_id = desk.add_ticket(db, **data, created_at=desk.timestamp())
                flash(f"Request {reference(ticket_id)} submitted.")
                return redirect(url_for("detail", ticket_id=ticket_id), code=303)
        return render_template("new.html", data=data, errors=errors), 422 if errors else 200

    def render_detail(ticket_id, error=None, code=200):
        db = database()
        # Use one read snapshot so the status and history always match.
        with db:
            db.execute("BEGIN")
            ticket = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
            if ticket is None:
                abort(404)
            history = db.execute(
                "SELECT * FROM events WHERE ticket_id = ? ORDER BY id DESC", (ticket_id,),
            ).fetchall()
        return render_template("detail.html", ticket=ticket, history=history,
                               transitions=desk.TRANSITIONS[ticket["status"]], error=error), code

    @app.get("/requests/<int:ticket_id>")
    def detail(ticket_id):
        return render_detail(ticket_id)

    @app.post("/requests/<int:ticket_id>/status")
    def update_status(ticket_id):
        note = request.form.get("note", "").strip()
        status = request.form.get("status", "")
        if len(note) > 500:
            return render_detail(ticket_id, "Keep the note to 500 characters.", 422)
        result = desk.change_status(database(), ticket_id, request.form.get("version", ""),
                                    status, note or "Status updated.")
        if result == 404:
            abort(404)
        if result == 409:
            return render_detail(ticket_id, "This request changed. Review the latest status and try again.", 409)
        if result == 422:
            return render_detail(ticket_id, "Choose an available status.", 422)
        flash("Request status updated.")
        return redirect(url_for("detail", ticket_id=ticket_id), code=303)

    @app.get("/requests/export.csv")
    def export():
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["Reference", "Title", "Category", "Priority", "Status", "Created (UTC)"])
        for ticket in desk.matching_tickets(database(), current_filters()):
            title = ticket["title"]
            if title.lstrip().startswith(("=", "+", "-", "@")) or title.startswith(("\t", "\r", "\n")):
                title = "'" + title
            writer.writerow([reference(ticket["id"]), title, ticket["category"], ticket["priority"],
                             ticket["status"], ticket["created_at"]])
        return Response("\ufeff" + buffer.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="campus-requests.csv"'})

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def show_error(error):
        return render_template("error.html", error=error), error.code

    return app


app = create_app()
