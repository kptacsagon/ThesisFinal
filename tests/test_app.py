import pytest
import json

from app import app, db


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def register(client, username, email, password, role="student"):
    return client.post("/api/auth/register", json={"username": username, "email": email, "password": password, "role": role})


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_student_success(self, client):
        r = register(client, "alice", "alice@example.com", "pass123")
        assert r.status_code == 201
        data = r.get_json()
        assert data["user"]["username"] == "alice"
        assert data["user"]["role"] == "student"
        assert "token" in data

    def test_register_advisor(self, client):
        r = register(client, "prof", "prof@example.com", "pass123", "advisor")
        assert r.status_code == 201
        assert r.get_json()["user"]["role"] == "advisor"

    def test_register_admin(self, client):
        r = register(client, "admin", "admin@example.com", "pass123", "admin")
        assert r.status_code == 201
        assert r.get_json()["user"]["role"] == "admin"

    def test_register_missing_fields(self, client):
        r = client.post("/api/auth/register", json={"username": "bob"})
        assert r.status_code == 400

    def test_register_duplicate_username(self, client):
        register(client, "alice", "alice@example.com", "pass123")
        r = register(client, "alice", "alice2@example.com", "pass123")
        assert r.status_code == 409

    def test_register_duplicate_email(self, client):
        register(client, "alice", "alice@example.com", "pass123")
        r = register(client, "alice2", "alice@example.com", "pass123")
        assert r.status_code == 409

    def test_register_invalid_role(self, client):
        r = register(client, "alice", "alice@example.com", "pass123", "superuser")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_success(self, client):
        register(client, "alice", "alice@example.com", "pass123")
        r = login(client, "alice", "pass123")
        assert r.status_code == 200
        assert "token" in r.get_json()

    def test_login_wrong_password(self, client):
        register(client, "alice", "alice@example.com", "pass123")
        r = login(client, "alice", "wrong")
        assert r.status_code == 401

    def test_login_unknown_user(self, client):
        r = login(client, "nobody", "pass")
        assert r.status_code == 401

    def test_login_missing_fields(self, client):
        r = client.post("/api/auth/login", json={"username": "alice"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Thesis submission tests
# ---------------------------------------------------------------------------

class TestThesisSubmission:
    def _student_token(self, client):
        register(client, "alice", "alice@example.com", "pass123", "student")
        return login(client, "alice", "pass123").get_json()["token"]

    def test_submit_thesis_success(self, client):
        token = self._student_token(client)
        r = client.post("/api/theses", json={"title": "My Thesis", "abstract": "Abstract here", "content": "Full content"},
                        headers=auth_header(token))
        assert r.status_code == 201
        data = r.get_json()
        assert data["title"] == "My Thesis"
        assert data["status"] == "pending"

    def test_submit_thesis_missing_fields(self, client):
        token = self._student_token(client)
        r = client.post("/api/theses", json={"title": "Only title"}, headers=auth_header(token))
        assert r.status_code == 400

    def test_advisor_cannot_submit_thesis(self, client):
        register(client, "prof", "prof@example.com", "pass123", "advisor")
        token = login(client, "prof", "pass123").get_json()["token"]
        r = client.post("/api/theses", json={"title": "T", "abstract": "A", "content": "C"},
                        headers=auth_header(token))
        assert r.status_code == 403

    def test_list_theses_student_sees_own(self, client):
        token = self._student_token(client)
        client.post("/api/theses", json={"title": "T1", "abstract": "A", "content": "C"}, headers=auth_header(token))
        # second student
        register(client, "bob", "bob@example.com", "pass123", "student")
        token2 = login(client, "bob", "pass123").get_json()["token"]
        client.post("/api/theses", json={"title": "T2", "abstract": "A", "content": "C"}, headers=auth_header(token2))

        r = client.get("/api/theses", headers=auth_header(token))
        theses = r.get_json()
        assert all(t["student_username"] == "alice" for t in theses)

    def test_list_theses_advisor_sees_all(self, client):
        token = self._student_token(client)
        client.post("/api/theses", json={"title": "T1", "abstract": "A", "content": "C"}, headers=auth_header(token))
        register(client, "bob", "bob@example.com", "pass123", "student")
        token2 = login(client, "bob", "pass123").get_json()["token"]
        client.post("/api/theses", json={"title": "T2", "abstract": "A", "content": "C"}, headers=auth_header(token2))

        register(client, "prof", "prof@example.com", "pass123", "advisor")
        adv_token = login(client, "prof", "pass123").get_json()["token"]
        r = client.get("/api/theses", headers=auth_header(adv_token))
        assert len(r.get_json()) == 2

    def test_no_token_returns_401(self, client):
        r = client.get("/api/theses")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Thesis update tests
# ---------------------------------------------------------------------------

class TestThesisUpdate:
    def _setup(self, client):
        register(client, "alice", "alice@example.com", "pass123", "student")
        token = login(client, "alice", "pass123").get_json()["token"]
        thesis = client.post("/api/theses", json={"title": "T", "abstract": "A", "content": "C"},
                             headers=auth_header(token)).get_json()
        return token, thesis["id"]

    def test_student_can_update_pending(self, client):
        token, thesis_id = self._setup(client)
        r = client.put(f"/api/theses/{thesis_id}", json={"title": "Updated"}, headers=auth_header(token))
        assert r.status_code == 200
        assert r.get_json()["title"] == "Updated"

    def test_other_student_cannot_update(self, client):
        _, thesis_id = self._setup(client)
        register(client, "bob", "bob@example.com", "pass123", "student")
        token2 = login(client, "bob", "pass123").get_json()["token"]
        r = client.put(f"/api/theses/{thesis_id}", json={"title": "Hack"}, headers=auth_header(token2))
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Review workflow tests
# ---------------------------------------------------------------------------

class TestReviewWorkflow:
    def _setup(self, client):
        register(client, "alice", "alice@example.com", "pass123", "student")
        s_token = login(client, "alice", "pass123").get_json()["token"]
        thesis = client.post("/api/theses", json={"title": "T", "abstract": "A", "content": "C"},
                             headers=auth_header(s_token)).get_json()

        register(client, "prof", "prof@example.com", "pass123", "advisor")
        a_token = login(client, "prof", "pass123").get_json()["token"]
        return s_token, a_token, thesis["id"]

    def test_advisor_can_approve(self, client):
        _, a_token, thesis_id = self._setup(client)
        r = client.post(f"/api/theses/{thesis_id}/review",
                        json={"decision": "approved", "comment": "Great work!"},
                        headers=auth_header(a_token))
        assert r.status_code == 201
        assert r.get_json()["decision"] == "approved"

    def test_thesis_status_updated_after_review(self, client):
        s_token, a_token, thesis_id = self._setup(client)
        client.post(f"/api/theses/{thesis_id}/review",
                    json={"decision": "needs_revision", "comment": "Please revise section 2"},
                    headers=auth_header(a_token))
        r = client.get(f"/api/theses/{thesis_id}", headers=auth_header(s_token))
        assert r.get_json()["status"] == "needs_revision"

    def test_advisor_can_reject(self, client):
        _, a_token, thesis_id = self._setup(client)
        r = client.post(f"/api/theses/{thesis_id}/review",
                        json={"decision": "rejected", "comment": "Does not meet requirements"},
                        headers=auth_header(a_token))
        assert r.status_code == 201
        assert r.get_json()["decision"] == "rejected"

    def test_student_cannot_review(self, client):
        s_token, _, thesis_id = self._setup(client)
        r = client.post(f"/api/theses/{thesis_id}/review",
                        json={"decision": "approved", "comment": "Self approve"},
                        headers=auth_header(s_token))
        assert r.status_code == 403

    def test_review_invalid_decision(self, client):
        _, a_token, thesis_id = self._setup(client)
        r = client.post(f"/api/theses/{thesis_id}/review",
                        json={"decision": "maybe", "comment": "Hmm"},
                        headers=auth_header(a_token))
        assert r.status_code == 400

    def test_student_cannot_edit_approved_thesis(self, client):
        s_token, a_token, thesis_id = self._setup(client)
        client.post(f"/api/theses/{thesis_id}/review",
                    json={"decision": "approved", "comment": "Great"},
                    headers=auth_header(a_token))
        r = client.put(f"/api/theses/{thesis_id}", json={"title": "Sneaky edit"},
                       headers=auth_header(s_token))
        assert r.status_code == 400

    def test_admin_can_review(self, client):
        _, _, thesis_id = self._setup(client)
        register(client, "admin", "admin@example.com", "pass123", "admin")
        admin_token = login(client, "admin", "pass123").get_json()["token"]
        r = client.post(f"/api/theses/{thesis_id}/review",
                        json={"decision": "approved", "comment": "Admin approves"},
                        headers=auth_header(admin_token))
        assert r.status_code == 201


# ---------------------------------------------------------------------------
# Admin user list tests
# ---------------------------------------------------------------------------

class TestAdminUsers:
    def test_admin_can_list_users(self, client):
        register(client, "admin", "admin@example.com", "pass123", "admin")
        token = login(client, "admin", "pass123").get_json()["token"]
        r = client.get("/api/users", headers=auth_header(token))
        assert r.status_code == 200
        assert isinstance(r.get_json(), list)

    def test_student_cannot_list_users(self, client):
        register(client, "alice", "alice@example.com", "pass123", "student")
        token = login(client, "alice", "pass123").get_json()["token"]
        r = client.get("/api/users", headers=auth_header(token))
        assert r.status_code == 403

    def test_advisor_cannot_list_users(self, client):
        register(client, "prof", "prof@example.com", "pass123", "advisor")
        token = login(client, "prof", "pass123").get_json()["token"]
        r = client.get("/api/users", headers=auth_header(token))
        assert r.status_code == 403
