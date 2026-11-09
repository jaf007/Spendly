"""
Tests for Step 8 — "Edit Expense".

Spec: .claude/specs/08-edit-expense.md

Behavior under test (via the real `GET/POST /expenses/<id>/edit` route, the
`get_expense_by_id` / `update_expense` query helpers in `database/queries.py`,
and the downstream effect on `/profile` — no internal implementation details
are assumed beyond what the spec states):
  - `GET /expenses/<id>/edit` and `POST /expenses/<id>/edit` are both
    logged-in-only; unauthenticated requests redirect to `/login`.
  - `GET /expenses/<id>/edit` for an expense owned by the logged-in user
    renders a form pre-filled with its current amount / category / date /
    description.
  - `GET` or `POST` for a nonexistent expense id, or an expense owned by a
    different user, returns 404 and never modifies the database.
  - `POST /expenses/<id>/edit` validates `amount` (required, numeric, > 0),
    `category` (required, must be one of the 7 fixed categories), and `date`
    (required, valid `YYYY-MM-DD`). `description` is optional,
    whitespace-stripped, and stored as `NULL` when blank.
  - On validation failure the form re-renders (200) with an error message
    and the previously submitted (not DB) values pre-filled; it never
    updates the row.
  - On success, the row is updated in place and the response redirects
    (302) to `/profile`.
  - The profile page's transaction table shows an "Edit" link per row,
    pointing at `/expenses/<id>/edit`.

IMPORTANT implementation detail (carried over from
`tests/test_07-add-expense.py`): `database/db.py`'s `get_db()` opens a
brand-new `sqlite3.connect(DB_PATH)` on every call with no connection
pooling and no Flask `g` — `DB_PATH` is a plain module-level global. This
means:
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
import re
import tempfile
from datetime import date

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
from flask import url_for  # noqa: E402

CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


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
    """An expense owned by `user`, available to edit."""
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


def _valid_payload(**overrides):
    payload = {
        "amount": "75.50",
        "category": "Transport",
        "date": "2026-04-15",
        "description": "Taxi",
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------- #
# HTML-scraping helpers (black-box — no implementation internals assumed)  #
# ----------------------------------------------------------------------- #

def _category_select_values(page_html):
    select_match = re.search(
        r'<select\b[^>]*\bname="category"[^>]*>(.*?)</select>', page_html, re.DOTALL
    )
    assert select_match, "Expected a <select name=\"category\"> element on the edit-expense form"
    options = re.findall(r'<option\b[^>]*\bvalue="([^"]*)"', select_match.group(1))
    return [value for value in options if value != ""]


def _has_post_form(page_html):
    return re.search(r'<form\b[^>]*\bmethod="POST"', page_html, re.IGNORECASE) is not None


def _input_value(page_html, field_name):
    tag_match = re.search(rf'<input\b[^>]*\bname="{field_name}"[^>]*>', page_html)
    if not tag_match:
        return None
    value_match = re.search(r'value="([^"]*)"', tag_match.group(0))
    return value_match.group(1) if value_match else None


def _has_error_message(page_html):
    return "error" in page_html.lower()


def _selected_category(page_html):
    select_match = re.search(
        r'<select\b[^>]*\bname="category"[^>]*>(.*?)</select>', page_html, re.DOTALL
    )
    if not select_match:
        return None
    match = re.search(
        r'<option\b[^>]*\bvalue="([^"]+)"[^>]*\bselected', select_match.group(1)
    )
    return match.group(1) if match else None


# ----------------------------------------------------------------------- #
# Auth guard                                                               #
# ----------------------------------------------------------------------- #

class TestEditExpenseAuthGuard:
    def test_get_edit_expense_without_session_redirects_to_login(self, client, app, expense):
        resp = client.get(_url(app, "edit_expense", id=expense["id"]))
        assert resp.status_code == 302, "Unauthenticated GET must redirect, not render the form"
        assert resp.headers["Location"].endswith(_url(app, "login"))

    def test_post_edit_expense_without_session_redirects_to_login(self, client, app, expense):
        resp = client.post(_url(app, "edit_expense", id=expense["id"]), data=_valid_payload())
        assert resp.status_code == 302, "Unauthenticated POST must redirect, not update data"
        assert resp.headers["Location"].endswith(_url(app, "login"))

    def test_post_edit_expense_without_session_does_not_update_row(self, client, app, expense):
        client.post(_url(app, "edit_expense", id=expense["id"]), data=_valid_payload())
        row = _get_expense(expense["id"])
        assert row["amount"] == expense["amount"], (
            "An unauthenticated POST must never write to the database"
        )


# ----------------------------------------------------------------------- #
# GET /expenses/<id>/edit — form rendering                                #
# ----------------------------------------------------------------------- #

class TestEditExpenseGetForm:
    def test_get_edit_expense_for_own_expense_returns_200(self, auth_client, app, expense):
        resp = auth_client.get(_url(app, "edit_expense", id=expense["id"]))
        assert resp.status_code == 200

    def test_get_edit_expense_form_present_with_post_method(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "edit_expense", id=expense["id"])).get_data(as_text=True)
        assert _has_post_form(html), "Edit-expense page must contain a <form method=\"POST\">"

    def test_get_edit_expense_prefills_amount_date_description(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "edit_expense", id=expense["id"])).get_data(as_text=True)
        assert _input_value(html, "amount") == "50.0"
        assert _input_value(html, "date") == "2026-03-20"
        assert _input_value(html, "description") == "Lunch"

    def test_get_edit_expense_category_select_preselects_current_category(
        self, auth_client, app, expense
    ):
        html = auth_client.get(_url(app, "edit_expense", id=expense["id"])).get_data(as_text=True)
        assert _selected_category(html) == "Food"

    def test_get_edit_expense_category_select_has_exactly_the_7_fixed_categories(
        self, auth_client, app, expense
    ):
        html = auth_client.get(_url(app, "edit_expense", id=expense["id"])).get_data(as_text=True)
        assert _category_select_values(html) == CATEGORIES

    def test_get_edit_expense_form_posts_to_correct_url(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "edit_expense", id=expense["id"])).get_data(as_text=True)
        assert _url(app, "edit_expense", id=expense["id"]) in html

    def test_get_edit_expense_never_renders_pound_or_dollar_sign(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "edit_expense", id=expense["id"])).get_data(as_text=True)
        assert "£" not in html, "Currency must never display as £"
        assert "$" not in html, "Currency must never display as $"


# ----------------------------------------------------------------------- #
# 404s — nonexistent or other users' expenses                             #
# ----------------------------------------------------------------------- #

class TestEditExpense404s:
    def test_get_edit_expense_nonexistent_id_returns_404(self, auth_client, app):
        resp = auth_client.get(_url(app, "edit_expense", id=999999))
        assert resp.status_code == 404

    def test_post_edit_expense_nonexistent_id_returns_404(self, auth_client, app):
        resp = auth_client.post(_url(app, "edit_expense", id=999999), data=_valid_payload())
        assert resp.status_code == 404

    def test_get_edit_expense_other_users_expense_returns_404(
        self, auth_client, app, other_users_expense
    ):
        resp = auth_client.get(_url(app, "edit_expense", id=other_users_expense["id"]))
        assert resp.status_code == 404, (
            "A user must never be able to view another user's expense edit form"
        )

    def test_post_edit_expense_other_users_expense_returns_404(
        self, auth_client, app, other_users_expense
    ):
        resp = auth_client.post(
            _url(app, "edit_expense", id=other_users_expense["id"]), data=_valid_payload()
        )
        assert resp.status_code == 404

    def test_post_edit_expense_other_users_expense_does_not_update_row(
        self, auth_client, app, other_users_expense
    ):
        auth_client.post(
            _url(app, "edit_expense", id=other_users_expense["id"]), data=_valid_payload()
        )
        row = _get_expense(other_users_expense["id"])
        assert row["amount"] == other_users_expense["amount"], (
            "Another user's expense must never be modified"
        )
        assert row["category"] == other_users_expense["category"]


# ----------------------------------------------------------------------- #
# POST /expenses/<id>/edit — happy path                                   #
# ----------------------------------------------------------------------- #

class TestEditExpenseHappyPath:
    def test_post_valid_edit_redirects_to_profile(self, auth_client, app, expense):
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=_valid_payload())
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(_url(app, "profile")), (
            "A successful save must redirect to the profile page, not re-render the form"
        )

    def test_post_valid_edit_updates_row_in_db(self, auth_client, app, expense):
        auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=_valid_payload())

        row = _get_expense(expense["id"])
        assert row["amount"] == 75.5
        assert row["category"] == "Transport"
        assert row["date"] == "2026-04-15"
        assert row["description"] == "Taxi"

    def test_post_valid_edit_changes_visible_on_profile_page(self, auth_client, app, expense):
        auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=_valid_payload(description="Updated taxi ride"))

        profile_html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert "Updated taxi ride" in profile_html, (
            "An edited expense's new values must show up in the profile's transaction list"
        )
        assert "Lunch" not in profile_html, "The old description must no longer appear"

    def test_post_valid_edit_without_description_stores_null(self, auth_client, app, expense):
        payload = _valid_payload(description="")
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)

        assert resp.status_code == 302
        row = _get_expense(expense["id"])
        assert row["description"] is None, "Blank description must be stored as NULL"

    def test_post_valid_edit_with_whitespace_only_description_stores_null(
        self, auth_client, app, expense
    ):
        payload = _valid_payload(description="   ")
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)

        assert resp.status_code == 302
        row = _get_expense(expense["id"])
        assert row["description"] is None, (
            "Whitespace-only description must be stripped and stored as NULL"
        )

    def test_post_valid_edit_does_not_affect_other_users_expenses(
        self, auth_client, app, expense, other_users_expense
    ):
        auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=_valid_payload())

        row = _get_expense(other_users_expense["id"])
        assert row["amount"] == other_users_expense["amount"]
        assert row["category"] == other_users_expense["category"]


# ----------------------------------------------------------------------- #
# POST /expenses/<id>/edit — validation errors                            #
# ----------------------------------------------------------------------- #

class TestEditExpenseValidation:
    def test_post_missing_amount_rerenders_form_with_error(self, auth_client, app, expense):
        payload = _valid_payload(amount="")
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, "Validation failure must re-render the form, not redirect"
        assert _has_error_message(html), "Missing amount must display an error message"
        row = _get_expense(expense["id"])
        assert row["amount"] == expense["amount"], "Invalid data must never update the row"

    @pytest.mark.parametrize("bad_amount", ["0", "-5", "abc", "", "   "])
    def test_post_invalid_amount_rerenders_form_without_updating(
        self, auth_client, app, expense, bad_amount
    ):
        payload = _valid_payload(amount=bad_amount)
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, (
            f"amount={bad_amount!r} must be rejected and re-render the form"
        )
        assert _has_error_message(html), f"amount={bad_amount!r} must display an error message"
        row = _get_expense(expense["id"])
        assert row["amount"] == expense["amount"], (
            f"amount={bad_amount!r} must never update the row"
        )

    def test_post_invalid_category_rerenders_form_with_error(self, auth_client, app, expense):
        payload = _valid_payload(category="Vacation")
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert _has_error_message(html), "Invalid category must display an error message"
        row = _get_expense(expense["id"])
        assert row["category"] == expense["category"], (
            "A category outside the fixed list must never update the row"
        )

    def test_post_blank_category_rerenders_form_with_error(self, auth_client, app, expense):
        payload = _valid_payload(category="")
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert _has_error_message(html), "Blank category must display an error message"
        row = _get_expense(expense["id"])
        assert row["category"] == expense["category"]

    @pytest.mark.parametrize(
        "bad_date", ["not-a-date", "2024-13-01", "2024/01/31", "", "32-01-2024"]
    )
    def test_post_invalid_date_rerenders_form_without_updating(
        self, auth_client, app, expense, bad_date
    ):
        payload = _valid_payload(date=bad_date)
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, f"date={bad_date!r} must be rejected"
        assert _has_error_message(html), f"date={bad_date!r} must display an error message"
        row = _get_expense(expense["id"])
        assert row["date"] == expense["date"], (
            f"date={bad_date!r} must never update the row"
        )

    def test_post_description_over_200_chars_rerenders_form_with_error(
        self, auth_client, app, expense
    ):
        payload = _valid_payload(description="x" * 201)
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert _has_error_message(html), "A description over 200 chars must display an error message"
        row = _get_expense(expense["id"])
        assert row["description"] == expense["description"]

    def test_post_validation_error_retains_submitted_values_not_db_values(
        self, auth_client, app, expense
    ):
        payload = _valid_payload(date="not-a-date", amount="77.25", description="Keep me")
        html = auth_client.post(
            _url(app, "edit_expense", id=expense["id"]), data=payload
        ).get_data(as_text=True)

        assert _input_value(html, "amount") == "77.25", (
            "Previously submitted amount must be pre-filled after a validation error"
        )
        assert _input_value(html, "description") == "Keep me", (
            "Previously submitted description must be pre-filled after a validation error"
        )
        assert _selected_category(html) == "Transport", (
            "Previously submitted (valid) category must remain selected after an unrelated error"
        )

    def test_post_sql_injection_style_description_is_handled_safely(
        self, auth_client, app, expense
    ):
        malicious = "Taxi'); DROP TABLE expenses; --"
        payload = _valid_payload(description=malicious)
        resp = auth_client.post(_url(app, "edit_expense", id=expense["id"]), data=payload)

        assert resp.status_code == 302, "A SQL-injection-style description must be treated as plain text"

        row = _get_expense(expense["id"])
        assert row["description"] == malicious, (
            "The malicious string must be stored verbatim via a parameterised query, not executed"
        )

        # The expenses table must genuinely still exist and be queryable.
        resp2 = auth_client.get(_url(app, "profile"))
        assert resp2.status_code == 200


# ----------------------------------------------------------------------- #
# Template integration — profile page edit links                          #
# ----------------------------------------------------------------------- #

class TestEditExpenseTemplateIntegration:
    def test_profile_page_shows_edit_link_per_transaction(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert "Edit" in html

    def test_profile_edit_link_points_to_correct_expense_id(self, auth_client, app, expense):
        html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert _url(app, "edit_expense", id=expense["id"]) in html, (
            "Each transaction row's Edit link must point to its own expense id"
        )
