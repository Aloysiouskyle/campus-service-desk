import csv
import io
import re
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from werkzeug.security import generate_password_hash

from app import create_app


class ServiceDeskTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.config = {
            "TESTING": True, "DATABASE": str(Path(folder.name) / "test.sqlite3"),
            "SECRET_KEY": "tests-only", "READ_ONLY": False,
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        account = self.app.test_cli_runner().invoke(
            args=["create-staff", "staff@example.test", "--password", "test-staff-password"]
        )
        self.assertEqual(account.exit_code, 0)
        self.assertEqual(self.login(self.client).status_code, 303)

    def login(self, client, email="staff@example.test", password="test-staff-password"):
        csrf = self.hidden(client.get("/sign-in"), "csrf")
        return client.post("/sign-in", data={"csrf": csrf, "email": email, "password": password})

    def test_authentication_and_sign_out(self):
        visitor = self.app.test_client()
        self.assertEqual(visitor.get("/").location, "/sign-in")
        self.assertEqual(visitor.get("/requests/export.csv").location, "/sign-in")
        self.assertEqual(self.login(visitor, password="incorrect").status_code, 401)
        self.assertEqual(self.login(visitor).location, "/")
        self.assertEqual(visitor.post("/sign-out").status_code, 400)
        csrf = self.hidden(visitor.get("/"), "csrf")
        self.assertEqual(visitor.post("/sign-out", data={"csrf": csrf}).location, "/sign-in")
        self.assertEqual(visitor.get("/requests/new").location, "/sign-in")

    def test_visitor_login_only_in_read_only_mode(self):
        preview = create_app({**self.config, "READ_ONLY": True}).test_client()
        self.assertEqual(self.login(preview, "visitor@campus.example", "MukonoDesk2026").status_code, 303)
        self.assertIn(b"Sign out", preview.get("/").data)
        self.assertEqual(preview.post("/requests/new").status_code, 403)
        self.assertEqual(self.login(self.app.test_client(), "visitor@campus.example", "MukonoDesk2026").status_code, 401)


    def hidden(self, response, name):
        return re.search(fr'name="{name}" value="([^"]+)"', response.get_data(as_text=True))[1]

    def submit(self, **overrides):
        fields = dict(title="Broken lab monitor", description="The campus lab monitor flickers.",
                      category="IT Support", priority="High")
        fields.update(overrides)
        fields["csrf"] = self.hidden(self.client.get("/requests/new"), "csrf")
        return self.client.post("/requests/new", data=fields)

    def update(self, status, page=None):
        page = page or self.client.get("/requests/1")
        return self.client.post("/requests/1/status", data={
            "csrf": self.hidden(page, "csrf"), "version": self.hidden(page, "version"),
            "status": status, "note": "Confirmed by lab support.",
        })

    def test_empty_dashboard_and_missing_request(self):
        self.assertIn(b"No requests found", self.client.get("/").data)
        self.assertEqual(self.client.get("/requests/999").status_code, 404)

    def test_submission_persists_after_restart_and_is_searchable(self):
        response = self.submit()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, "/requests/1")
        restarted = create_app(self.config).test_client()
        self.login(restarted)
        self.assertIn(b"Request submitted.", restarted.get(response.location).data)
        self.assertIn(b"Broken lab monitor", restarted.get("/?q=csd-0001").data)

    def test_validation_preserves_input_and_rejects_unknown_category(self):
        response = self.submit(title="A nice title", category="Invalid", description="short")
        self.assertEqual(response.status_code, 422)
        self.assertIn(b'A nice title', response.data)
        self.assertIn(b'Choose a category.', response.data)
        self.assertIn(b'No requests found', self.client.get("/").data)

    def test_post_without_csrf_is_rejected(self):
        self.assertEqual(self.client.post("/requests/new").status_code, 400)
        self.assertEqual(self.client.post("/requests/1/status").status_code, 400)

    def test_status_lifecycle_and_history(self):
        self.submit()
        self.assertEqual(self.update("Resolved").status_code, 422)
        self.assertEqual(self.update("In progress").status_code, 303)
        self.assertEqual(self.update("Resolved").status_code, 303)
        self.assertEqual(self.update("Open").status_code, 303)
        page = self.client.get("/requests/1").data
        self.assertEqual(page.count(b"Confirmed by lab support."), 3)

    def test_stale_update_is_rejected_even_after_status_cycles(self):
        self.submit()
        old_page = self.client.get("/requests/1")
        self.assertEqual(self.update("In progress").status_code, 303)
        self.assertEqual(self.update("Open").status_code, 303)
        self.assertEqual(self.update("In progress", old_page).status_code, 409)

    def test_dashboard_and_csv_share_combined_filters_and_escape_formula_cells(self):
        self.submit(title="=Formula-looking title, with comma")
        self.submit(title="Library Wi-Fi", priority="Low")
        self.submit(title="Library chairs", category="Facilities")
        query = "?status=Open&priority=High&category=IT+Support&q=title"
        page = self.client.get("/" + query)
        self.assertIn(b"Showing 1 of 3 requests", page.data)
        response = self.client.get("/requests/export.csv" + query)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Title"], "'=Formula-looking title, with comma")
        self.assertEqual(rows[0]["Reference"], "CSD-0001")

    def test_students_track_only_their_tickets_and_staff_can_respond(self):
        students = []
        for name in ("alicia", "daniel"):
            email = f"{name}@example.test"
            account = self.app.test_cli_runner().invoke(
                args=["create-student", email, "--password", "test-student-password"])
            self.assertEqual(account.exit_code, 0, account.output)
            client = self.app.test_client()
            self.assertEqual(self.login(client, email, "test-student-password").status_code, 303)
            response = client.post("/requests/new", data={
                "csrf": self.hidden(client.get("/requests/new"), "csrf"), "title": f"{name} lab request",
                "description": "The lab printer needs paper.", "priority": "Normal", "category": "IT Support",
                "owner_email": "staff@example.test",
            })
            self.assertEqual(response.status_code, 303)
            students.append(client)
        alicia, daniel = students
        for path in ("/", "/?q=lab", "/requests/export.csv?q=lab"):
            page = alicia.get(path).data
            self.assertIn(b"alicia lab request", page)
            self.assertNotIn(b"daniel lab request", page)
        self.assertIn(b"Showing 1 of 1 request", alicia.get("/").data)
        self.assertEqual(alicia.get("/requests/2").status_code, 404)
        self.assertEqual(daniel.get("/requests/1").status_code, 404)
        conversation = "/requests/1/messages"
        for client, reply in [(self.client, "Which printer?"), (alicia, "<b>Beside workstation 12</b>")]:
            token = self.hidden(client.get("/requests/1"), "csrf")
            self.assertEqual(client.post(conversation, data={"body": reply, "csrf": token}).location,
                             "/requests/1#conversation")
        token = self.hidden(daniel.get("/"), "csrf")
        self.assertEqual(daniel.post(conversation, data={"body": "Wrong ticket", "csrf": token}).status_code, 404)
        page = alicia.get("/requests/1").get_data(as_text=True)
        self.assertLess(page.index("Which printer?"), page.index("&lt;b&gt;Beside workstation 12&lt;/b&gt;"))
        self.assertIn("alicia@example.test</strong> · Student", page)
        self.assertNotIn("Wrong ticket", page)
        own_ticket = alicia.get("/requests/1")
        self.assertNotIn(b"Update status", own_ticket.data)
        self.assertEqual(alicia.post("/requests/1/status", data={
            "csrf": self.hidden(own_ticket, "csrf"), "version": "1", "role": "staff",
            "status": "In progress",
        }).status_code, 403)
        self.assertIn(b"Showing 2 of 2 requests", self.client.get("/").data)
        self.assertEqual(alicia.post("/requests/1/claim", data={"csrf": self.hidden(own_ticket, "csrf")}).status_code, 403)
        self.assertEqual(self.client.post("/requests/1/claim").status_code, 400)
        staff_token = self.hidden(self.client.get("/requests/1"), "csrf")
        self.assertEqual(self.client.post("/requests/1/claim", data={"csrf": staff_token}).status_code, 303)
        student_page = alicia.get("/requests/1").data
        self.assertIn(b"Assigned to staff@example.test.", student_page)
        self.assertNotIn(b"Assign to me", student_page)
        self.assertEqual(self.update("In progress").status_code, 303)
        self.assertIn(b"Confirmed by lab support.", alicia.get("/requests/1").data)
        inbox = alicia.get("/notifications")
        self.assertIn(b"Notifications (2)", inbox.data)
        self.assertIn(b"New reply on CSD-0001", inbox.data)
        self.assertIn(b"Status changed on CSD-0001", inbox.data)
        self.assertIn(b"Notifications (0)", daniel.get("/notifications").data)
        path = "/notifications/1/open"
        self.assertEqual(daniel.post(path, data={"csrf": token}).status_code, 404)
        self.assertEqual(alicia.post(path, data={"csrf": self.hidden(inbox, "csrf")}).location,
                         "/requests/1#conversation")
        self.assertIn(b"Notifications (1)", alicia.get("/notifications").data)
        self.assertIn(b"New reply on CSD-0001", alicia.get("/notifications").data)


    def test_concurrent_staff_claims_record_one_winner_and_one_history_entry(self):
        self.submit()
        self.submit(title="Another broken monitor")
        second_email = "second@example.test"
        result = self.app.test_cli_runner().invoke(
            args=["create-staff", second_email, "--password", "test-staff-password"])
        self.assertEqual(result.exit_code, 0)
        other = self.app.test_client()
        self.assertEqual(self.login(other, second_email).status_code, 303)
        clients = [self.client, other]
        emails = ["staff@example.test", second_email]
        forms = [{"csrf": self.hidden(client.get("/requests/1"), "csrf")} for client in clients]
        start = Barrier(2)

        def claim(index):
            start.wait(timeout=5)
            return clients[index].post("/requests/1/claim", data=forms[index])

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(claim, range(2)))
        codes = [response.status_code for response in responses]
        self.assertCountEqual(codes, [303, 409])
        winner, loser = codes.index(303), codes.index(409)
        self.assertIn(emails[winner].encode(), responses[loser].data)
        self.assertIn(b"Another staff member claimed", responses[loser].data)
        retry = clients[winner].post("/requests/1/claim", data=forms[winner])
        self.assertEqual(retry.status_code, 303)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            self.assertEqual(db.execute("SELECT assignee_email, status FROM tickets WHERE id=1").fetchone(),
                             (emails[winner], "Open"))
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE ticket_id=1").fetchone()[0], 2)
        for assignment, expected in [(emails[winner], ["CSD-0001"]), (emails[loser], []),
                                     ("unassigned", ["CSD-0002"])]:
            query = {"assignee": assignment, "q": "monitor", "status": "Open"}
            page = other.get("/", query_string=query).data
            self.assertIn(f"Showing {len(expected)} of 2".encode(), page)
            export = other.get("/requests/export.csv", query_string=query)
            rows = list(csv.DictReader(io.StringIO(export.data.decode("utf-8-sig"))))
            self.assertEqual([row["Reference"] for row in rows], expected)
            if rows:
                self.assertEqual(rows[0]["Assigned to"], "Unassigned" if assignment == "unassigned" else assignment)

    def test_existing_staff_login_and_ticket_survive_schema_upgrade(self):
        legacy_path = str(Path(self.config["DATABASE"]).with_name("old.sqlite3"))
        with sqlite3.connect(legacy_path) as db:
            db.executescript("""
                CREATE TABLE staff (email TEXT PRIMARY KEY COLLATE NOCASE, password_hash TEXT NOT NULL);
                CREATE TABLE tickets (id INTEGER PRIMARY KEY, title TEXT, description TEXT,
                    category TEXT, priority TEXT, status TEXT DEFAULT 'Open', created_at TEXT);
                INSERT INTO tickets VALUES (1, 'Old projector', 'Broken lamp', 'Facilities',
                    'High', 'Open', '2026-10-01');
            """)
            db.execute("INSERT INTO staff VALUES (?, ?)",
                       ("staff@example.test", generate_password_hash("test-staff-password")))
        legacy = create_app({**self.config, "DATABASE": legacy_path})
        client = legacy.test_client()
        self.assertEqual(self.login(client).status_code, 303)
        self.assertIn(b"Old projector", client.get("/").data)
        result = legacy.test_cli_runner().invoke(
            args=["create-student", "ada@example.test", "--password", "test-student-password"])
        self.assertEqual(result.exit_code, 0)
        student = legacy.test_client()
        self.assertEqual(self.login(student, "ada@example.test", "test-student-password").status_code, 303)
        self.assertEqual(student.get("/requests/1").status_code, 404)
        self.assertNotIn(b"Old projector", student.get("/requests/export.csv").data)

    def test_ticket_text_is_escaped_in_html(self):
        self.submit(title="<b>Lab monitor</b>")
        page = self.client.get("/").data
        self.assertIn(b"&lt;b&gt;Lab monitor&lt;/b&gt;", page)
        self.assertNotIn(b"<b>Lab monitor</b>", page)

    def test_seed_is_repeatable_and_preserves_existing_tickets(self):
        runner = self.app.test_cli_runner()
        self.assertEqual(runner.invoke(args=["seed"]).exit_code, 0)
        self.assertEqual(runner.invoke(args=["seed"]).exit_code, 0)
        self.assertIn(b"Showing 12 of 12 requests", self.client.get("/").data)
        self.submit()
        self.assertEqual(runner.invoke(args=["seed"]).exit_code, 0)
        self.assertIn(b"Showing 13 of 13 requests", self.client.get("/").data)

    def test_hosted_preview_browses_samples_and_blocks_writes(self):
        preview = create_app({**self.config, "READ_ONLY": True}).test_client()
        self.assertIn(b"Showing 12 of 12 requests", preview.get("/").data)
        self.assertIn(b"Activity history", preview.get("/requests/1").data)
        self.assertEqual(preview.get("/requests/export.csv").status_code, 200)
        self.assertEqual(preview.post("/requests/new").status_code, 403)
        self.assertEqual(preview.post("/requests/1/status").status_code, 403)
        self.assertEqual(preview.post("/requests/1/claim").status_code, 403)
        self.assertEqual(preview.post("/requests/1/messages").status_code, 403)
        with preview.get("/assets/desk.css") as stylesheet:
            self.assertEqual(stylesheet.status_code, 200)


if __name__ == "__main__":
    unittest.main()
