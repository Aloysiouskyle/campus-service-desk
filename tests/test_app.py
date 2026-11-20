import csv
import io
import re
import tempfile
import unittest
from pathlib import Path

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
        with preview.get("/assets/desk.css") as stylesheet:
            self.assertEqual(stylesheet.status_code, 200)


if __name__ == "__main__":
    unittest.main()
