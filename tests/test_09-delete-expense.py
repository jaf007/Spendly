"""
Tests for Step 9 — "Delete Expense".

Spec: .claude/specs/09-delete-expense.md

Behavior under test (via the real `delete_expense` query helper in
`database/queries.py` and the real `POST /expenses/<id>/delete` route — no
internal implementation details are assumed beyond what the spec states):
  - `delete_expense(conn, expense_id, user_id)` issues a parameterised
    `DELETE ... WHERE id = ? AND user_id = ?`. It removes the row when the
    id/user_id pair matches, silently leaves the row untouched (no error)
    when the user_id doesn't match, and silently no-ops (no error) when the
    expense_id doesn't exist at all.
  - `POST /expenses/<id>/delete` is logged-in-only; unauthenticated requests
    redirect to `/login` and never touch the database.
  - `GET /expenses/<id>/delete` is not a supported method — returns 405.
  - A `POST` for a nonexistent expense id, or an expense owned by a
    different user, returns 404 and never deletes anything.
  - A `POST` for an expense owned by the logged-in user deletes the row and
    redirects (302) to `/profile`; the deleted expense no longer appears in
    the profile's transaction list, and other users' expenses are
    untouched.

IMPORTANT implementation detail (carried over from
`tests/test_07-add-expense.py` / `tests/test_08-edit-expense.py`):
`database/db.py`'s `get_db()` opens a brand-new `sqlite3.connect(DB_PATH)`
on every call with no connection pooling and no Flask `g` — `DB_PATH` is a
plain module-level global. This means:
  * An in-memory `:memory:` database would be wiped between every single
    `get_db()` call, so a real temp *file* path must be used instead.
  * `app.py` runs `init_db()` / `seed_db()` at **import time**, against
    whatever `DB_PATH` is set at that moment. To avoid ever touching the
    real project's `expense_tracker.db`, `database.db.DB_PATH` is
    redirected to a throwaway bootstrap file *before* `app` is imported.
  * Each test then gets its own isolated temp-file database by
    monkeypatching `database.db.DB_PATH` again inside the `app` fixture.
"""

import os
import tempfile

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module

# --------------------------------------------------------------------- #
# Redirect the module-level DB_PATH *before* importing `app`, so the
# `init_db()` / `seed_db()` call that runs automatically on import never
# touches the real project database file.
# --------------------------------------------------------------------- #
_bootstrap_fd, _BOOTSTRAP_DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_bootstrap_fd)
db_module.DB_PATH = _BOOTSTRAP_DB_PATH

from app import app as flask_app  # noqa: E402  (must follow DB_PATH patch)
from database.queries import delete_expense  # noqa: E402
from flask import url_for  # noqa: E402


# ----------------------------------------------------------------------- #
# Fixtures                                                                 #
# ----------------------------------------------------------------------- #

@pytest.fixture
def app(monkeypatch, tmp_path):
    """Flask app wired to a fresh, isolated, file-backed SQLite DB."""
    db_path = str(tmp_path / "test_spendly.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-secret"})

    with flask_app.app_context():
        db_module.init_db()

    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _url(app, endpoint, **kwargs):
    """Build a URL via url_for — never hardcode routes in tests."""
    with app.test_request_context():
        return url_for(endpoint, **kwargs)


def _create_user(name, email, password):
    conn = db_module.get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _create_expense(user_id, amount=50.0, category="Food", date="2026-03-20", description="Lunch"):
    conn = db_module.get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, date, description),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _get_expense(expense_id):
    conn = db_module.get_db()
    try:
        row = conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_expenses_for_user(user_id):
    conn = db_module.get_db()
    try:
        rows = conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@pytest.fixture
def user(app):
    """A standard user with no expenses yet."""
    email = "alice@example.com"
    password = "testpass123"
    user_id = _create_user("Alice Example", email, password)
    return {"id": user_id, "email": email, "password": password}


@pytest.fixture
def other_user(app):
    """A second, independent user — for multi-user isolation tests."""
    email = "bob@example.com"
    password = "bobspass123"
    user_id = _create_user("Bob Example", email, password)
    return {"id": user_id, "email": email, "password": password}


@pytest.fixture
def auth_client(client, app, user):
    """A test client logged in as `user` via the real /login route."""
    resp = client.post(
        _url(app, "login"),
        data={"email": user["email"], "password": user["password"]},
    )
    assert resp.status_code == 302, "Login with valid fixture credentials should redirect"
    return client


@pytest.fixture
def expense(app, user):
    """An expense owned by `user`, available to delete."""
    expense_id = _create_expense(
        user["id"], amount=50.0, category="Food", date="2026-03-20", description="Lunch"
    )
    return {
        "id": expense_id,
        "amount": 50.0,
        "category": "Food",
        "date": "2026-03-20",
        "description": "Lunch",
    }


@pytest.fixture
def other_users_expense(app, other_user):
    """An expense owned by `other_user` — used for ownership-isolation tests."""
    expense_id = _create_expense(
        other_user["id"], amount=99.0, category="Bills", date="2026-01-01", description="Rent"
    )
    return {"id": expense_id, "amount": 99.0, "category": "Bills", "date": "2026-01-01", "description": "Rent"}


# ----------------------------------------------------------------------- #
# Unit tests — database/queries.py::delete_expense                        #
# ----------------------------------------------------------------------- #

class TestDeleteExpenseUnit:
    def test_delete_expense_valid_id_correct_user_removes_row(self, app, user, expense):
        conn = db_module.get_db()
        try:
            delete_expense(conn, expense["id"], user["id"])
        finally:
            conn.close()

        assert _get_expense(expense["id"]) is None, (
            "delete_expense with the correct owner must remove the row from the DB"
        )

    def test_delete_expense_wrong_user_id_leaves_row_intact(self, app, expense, other_user):
        conn = db_module.get_db()
        try:
            # Attempt to delete `expense` (owned by `user`) using `other_user`'s id.
            delete_expense(conn, expense["id"], other_user["id"])
        finally:
            conn.close()

        row = _get_expense(expense["id"])
        assert row is not None, (
            "delete_expense with a mismatched user_id must not delete the row "
            "(0 rows affected, no error raised)"
        )
        assert row["amount"] == expense["amount"]
        assert row["category"] == expense["category"]

    def test_delete_expense_wrong_user_id_raises_no_error(self, app, expense, other_user):
        conn = db_module.get_db()
        try:
            # Must complete without raising, even though no row matches.
            delete_expense(conn, expense["id"], other_user["id"])
        finally:
            conn.close()

    def test_delete_expense_nonexistent_id_raises_no_error(self, app, user):
        conn = db_module.get_db()
        try:
            delete_expense(conn, 999999, user["id"])
        finally:
            conn.close()
        # No assertion needed beyond "did not raise" — but confirm DB state
        # for the real user is unaffected.
        assert _get_expenses_for_user(user["id"]) == []

    def test_delete_expense_nonexistent_id_does_not_change_db(self, app, user, expense):
        before = _get_expenses_for_user(user["id"])

        conn = db_module.get_db()
        try:
            delete_expense(conn, 999999, user["id"])
        finally:
            conn.close()

        after = _get_expenses_for_user(user["id"])
        assert after == before, (
            "Deleting a nonexistent expense_id must leave existing rows untouched"
        )


# ----------------------------------------------------------------------- #
# Auth guard                                                               #
# ----------------------------------------------------------------------- #

class TestDeleteExpenseAuthGuard:
    def test_post_delete_expense_without_session_redirects_to_login(self, client, app, expense):
        resp = client.post(_url(app, "delete_expense", id=expense["id"]))
        assert resp.status_code == 302, "Unauthenticated POST must redirect, not delete the row"
        assert resp.headers["Location"].endswith(_url(app, "login"))

    def test_post_delete_expense_without_session_does_not_delete_row(self, client, app, expense):
        client.post(_url(app, "delete_expense", id=expense["id"]))
        row = _get_expense(expense["id"])
        assert row is not None, "An unauthenticated POST must never delete from the database"


# ----------------------------------------------------------------------- #
# Method guard — GET must be 405                                          #
# ----------------------------------------------------------------------- #

class TestDeleteExpenseMethodGuard:
    def test_get_delete_expense_returns_405_unauthenticated(self, client, app, expense):
        resp = client.get(_url(app, "delete_expense", id=expense["id"]))
        assert resp.status_code == 405, "GET on the delete route must not be allowed"

    def test_get_delete_expense_returns_405_authenticated(self, auth_client, app, expense):
        resp = auth_client.get(_url(app, "delete_expense", id=expense["id"]))
        assert resp.status_code == 405, "GET on the delete route must not be allowed, even when logged in"

    def test_get_delete_expense_does_not_delete_row(self, auth_client, app, expense):
        auth_client.get(_url(app, "delete_expense", id=expense["id"]))
        assert _get_expense(expense["id"]) is not None, (
            "A GET request must never delete the expense"
        )


# ----------------------------------------------------------------------- #
# 404s — nonexistent or other users' expenses                             #
# ----------------------------------------------------------------------- #

class TestDeleteExpense404s:
    def test_post_delete_expense_nonexistent_id_returns_404(self, auth_client, app):
        resp = auth_client.post(_url(app, "delete_expense", id=999999))
        assert resp.status_code == 404

    def test_post_delete_expense_other_users_expense_returns_404(
        self, auth_client, app, other_users_expense
    ):
        resp = auth_client.post(_url(app, "delete_expense", id=other_users_expense["id"]))
        assert resp.status_code == 404, (
            "A user must never be able to delete another user's expense"
        )

    def test_post_delete_expense_other_users_expense_does_not_delete_row(
        self, auth_client, app, other_users_expense
    ):
        auth_client.post(_url(app, "delete_expense", id=other_users_expense["id"]))
        row = _get_expense(other_users_expense["id"])
        assert row is not None, "Another user's expense must never be removed"
        assert row["amount"] == other_users_expense["amount"]
        assert row["category"] == other_users_expense["category"]


# ----------------------------------------------------------------------- #
# POST /expenses/<id>/delete — happy path                                 #
# ----------------------------------------------------------------------- #

class TestDeleteExpenseHappyPath:
    def test_post_delete_own_expense_redirects_to_profile(self, auth_client, app, expense):
        resp = auth_client.post(_url(app, "delete_expense", id=expense["id"]))
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(_url(app, "profile")), (
            "A successful delete must redirect to the profile page"
        )

    def test_post_delete_own_expense_removes_row_from_db(self, auth_client, app, expense):
        auth_client.post(_url(app, "delete_expense", id=expense["id"]))
        assert _get_expense(expense["id"]) is None, (
            "The expense row must no longer exist in the database after deletion"
        )

    def test_post_delete_own_expense_no_longer_appears_on_profile(self, auth_client, app, expense):
        auth_client.post(_url(app, "delete_expense", id=expense["id"]))
        profile_html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert expense["description"] not in profile_html, (
            "A deleted expense's description must no longer appear in the transaction list"
        )

    def test_post_delete_own_expense_sets_success_flash_message(self, auth_client, app, expense):
        resp = auth_client.post(_url(app, "delete_expense", id=expense["id"]), follow_redirects=True)
        html = resp.get_data(as_text=True)
        assert "Expense deleted" in html, (
            "Deleting an expense must flash an 'Expense deleted' success message"
        )

    def test_post_delete_does_not_affect_other_users_expenses(
        self, auth_client, app, expense, other_users_expense
    ):
        auth_client.post(_url(app, "delete_expense", id=expense["id"]))

        row = _get_expense(other_users_expense["id"])
        assert row is not None
        assert row["amount"] == other_users_expense["amount"]
        assert row["category"] == other_users_expense["category"]

    def test_post_delete_only_removes_targeted_expense(self, auth_client, app, user):
        keep_id = _create_expense(user["id"], amount=10.0, category="Food", date="2026-01-01", description="Keep")
        delete_id = _create_expense(user["id"], amount=20.0, category="Bills", date="2026-01-02", description="Remove")

        resp = auth_client.post(_url(app, "delete_expense", id=delete_id))
        assert resp.status_code == 302

        assert _get_expense(delete_id) is None
        assert _get_expense(keep_id) is not None, "Only the targeted expense should be deleted"

    def test_post_delete_twice_second_time_returns_404(self, auth_client, app, expense):
        first = auth_client.post(_url(app, "delete_expense", id=expense["id"]))
        assert first.status_code == 302

        second = auth_client.post(_url(app, "delete_expense", id=expense["id"]))
        assert second.status_code == 404, (
            "Deleting an already-deleted expense must 404, not silently succeed"
        )


# ----------------------------------------------------------------------- #
# Template integration — profile page delete form/button                  #
# ----------------------------------------------------------------------- #

class TestDeleteExpenseTemplateIntegration:
    def test_profile_page_shows_delete_action_per_transaction(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert "Delete" in html

    def test_profile_delete_form_posts_to_correct_expense_url(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert _url(app, "delete_expense", id=expense["id"]) in html, (
            "Each transaction row's delete form must submit to its own expense id"
        )

    def test_profile_delete_form_uses_post_method(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        target_url = _url(app, "delete_expense", id=expense["id"])
        # The <form> whose action targets this expense's delete endpoint must use POST.
        form_start = html.find(target_url)
        assert form_start != -1
        form_snippet = html[max(0, form_start - 200):form_start + 50]
        assert "POST" in form_snippet.upper(), (
            "The delete form must submit via POST, not GET"
        )

    def test_profile_page_shows_both_edit_and_delete_per_row(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert _url(app, "edit_expense", id=expense["id"]) in html
        assert _url(app, "delete_expense", id=expense["id"]) in html
