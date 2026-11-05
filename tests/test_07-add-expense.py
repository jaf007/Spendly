"""
Tests for Step 7 — "Add Expense".

Spec: .claude/specs/07-add-expense.md

Behavior under test (via the real `GET/POST /expenses/add` route, the
`insert_expense` query helper described by the spec, and the downstream
effect on `/profile` — no internal implementation details are assumed
beyond what the spec states):
  - `GET /expenses/add` and `POST /expenses/add` are both logged-in-only;
    unauthenticated requests redirect to `/login`.
  - `GET /expenses/add` renders a form with amount / category / date /
    description fields, a category `<select>` with exactly the 7 fixed
    categories, and a `date` field defaulting to today's date.
  - `POST /expenses/add` validates `amount` (required, numeric, > 0),
    `category` (required, must be one of the 7 fixed categories), and
    `date` (required, valid `YYYY-MM-DD`). `description` is optional,
    whitespace-stripped, and stored as `NULL` when blank.
  - On validation failure the form re-renders (200) with an error message
    and the previously submitted values pre-filled; it never inserts a row.
  - On success, a new row is inserted into `expenses` for the session
    user and the response redirects (302) to `/profile`.
  - A reusable `insert_expense(user_id, amount, category, date, description)`
    helper is added to `database/queries.py`.
  - The profile page gets an "Add Expense" link, and the navbar shows an
    "Add Expense" link only when `session.user_id` is set.

IMPORTANT implementation detail (carried over from
`tests/test_06-date-filter-profile.py`): `database/db.py`'s `get_db()`
opens a brand-new `sqlite3.connect(DB_PATH)` on every call with no
connection pooling and no Flask `g` — `DB_PATH` is a plain module-level
global. This means:
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


def _valid_payload(**overrides):
    payload = {
        "amount": "50.0",
        "category": "Food",
        "date": "2026-03-20",
        "description": "Lunch",
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------- #
# HTML-scraping helpers (black-box — no implementation internals assumed)  #
# ----------------------------------------------------------------------- #

def _category_select_values(page_html):
    """Return the list of non-empty <option value="..."> inside the
    category <select>, in document order."""
    select_match = re.search(
        r'<select\b[^>]*\bname="category"[^>]*>(.*?)</select>', page_html, re.DOTALL
    )
    assert select_match, "Expected a <select name=\"category\"> element on the add-expense form"
    options = re.findall(r'<option\b[^>]*\bvalue="([^"]*)"', select_match.group(1))
    return [value for value in options if value != ""]


def _has_post_form(page_html):
    return re.search(r'<form\b[^>]*\bmethod="POST"', page_html, re.IGNORECASE) is not None


def _input_value(page_html, field_name):
    """Extract the value="..." attribute of an <input name="field_name">."""
    tag_match = re.search(rf'<input\b[^>]*\bname="{field_name}"[^>]*>', page_html)
    if not tag_match:
        return None
    value_match = re.search(r'value="([^"]*)"', tag_match.group(0))
    return value_match.group(1) if value_match else None


def _has_error_message(page_html):
    """Loose, implementation-agnostic check that *some* error indicator is
    present (e.g. an "...-error" CSS class or flashed message block), since
    the spec only requires "an error message" without mandating exact
    wording."""
    return "error" in page_html.lower()


def _selected_category(page_html):
    """Return the category marked as selected in the <select>, if any."""
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
# Unit tests — insert_expense() query helper                               #
# ----------------------------------------------------------------------- #

class TestInsertExpenseUnit:
    def test_insert_expense_creates_row_queryable_from_db(self, app, user):
        queries = pytest.importorskip(
            "database.queries",
            reason="database/queries.py with insert_expense() not yet implemented",
        )
        with app.app_context():
            queries.insert_expense(
                user_id=user["id"],
                amount=50.0,
                category="Food",
                date="2026-03-20",
                description="Lunch",
            )

        rows = _get_expenses_for_user(user["id"])
        assert len(rows) == 1, "insert_expense should create exactly one row"
        row = rows[0]
        assert row["user_id"] == user["id"]
        assert row["amount"] == 50.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_insert_expense_with_none_description_stores_null(self, app, user):
        queries = pytest.importorskip(
            "database.queries",
            reason="database/queries.py with insert_expense() not yet implemented",
        )
        with app.app_context():
            queries.insert_expense(
                user_id=user["id"],
                amount=20.0,
                category="Transport",
                date="2026-01-01",
                description=None,
            )

        rows = _get_expenses_for_user(user["id"])
        assert len(rows) == 1
        assert rows[0]["description"] is None, "A None description must be stored as NULL"


# ----------------------------------------------------------------------- #
# Auth guard                                                               #
# ----------------------------------------------------------------------- #

class TestAddExpenseAuthGuard:
    def test_get_add_expense_without_session_redirects_to_login(self, client, app):
        resp = client.get(_url(app, "add_expense"))
        assert resp.status_code == 302, "Unauthenticated GET must redirect, not render the form"
        assert resp.headers["Location"].endswith(_url(app, "login"))

    def test_post_add_expense_without_session_redirects_to_login(self, client, app):
        resp = client.post(_url(app, "add_expense"), data=_valid_payload())
        assert resp.status_code == 302, "Unauthenticated POST must redirect, not insert data"
        assert resp.headers["Location"].endswith(_url(app, "login"))

    def test_post_add_expense_without_session_does_not_insert_row(self, client, app, user):
        client.post(_url(app, "add_expense"), data=_valid_payload())
        assert _get_expenses_for_user(user["id"]) == [], (
            "An unauthenticated POST must never write to the database"
        )


# ----------------------------------------------------------------------- #
# GET /expenses/add — form rendering                                       #
# ----------------------------------------------------------------------- #

class TestAddExpenseGetForm:
    def test_get_add_expense_authenticated_returns_200(self, auth_client, app):
        resp = auth_client.get(_url(app, "add_expense"))
        assert resp.status_code == 200

    def test_get_add_expense_form_present_with_post_method(self, auth_client, app):
        html = auth_client.get(_url(app, "add_expense")).get_data(as_text=True)
        assert _has_post_form(html), "Add-expense page must contain a <form method=\"POST\">"

    def test_get_add_expense_category_select_has_exactly_the_7_fixed_categories(
        self, auth_client, app
    ):
        html = auth_client.get(_url(app, "add_expense")).get_data(as_text=True)
        assert _category_select_values(html) == CATEGORIES, (
            "Category dropdown must contain exactly the 7 fixed categories, in order"
        )

    def test_get_add_expense_date_field_defaults_to_today(self, auth_client, app):
        html = auth_client.get(_url(app, "add_expense")).get_data(as_text=True)
        assert _input_value(html, "date") == date.today().isoformat(), (
            "Date field must default to today's date"
        )

    def test_get_add_expense_has_amount_and_description_inputs(self, auth_client, app):
        html = auth_client.get(_url(app, "add_expense")).get_data(as_text=True)
        assert 'name="amount"' in html
        assert 'name="description"' in html

    def test_get_add_expense_never_renders_pound_or_dollar_sign(self, auth_client, app):
        html = auth_client.get(_url(app, "add_expense")).get_data(as_text=True)
        assert "£" not in html, "Currency must never display as £"
        assert "$" not in html, "Currency must never display as $"


# ----------------------------------------------------------------------- #
# POST /expenses/add — happy path                                         #
# ----------------------------------------------------------------------- #

class TestAddExpenseHappyPath:
    def test_post_valid_expense_redirects_to_profile(self, auth_client, app):
        resp = auth_client.post(_url(app, "add_expense"), data=_valid_payload())
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(_url(app, "profile")), (
            "A successful save must redirect to the profile page, not re-render the form"
        )

    def test_post_valid_expense_inserts_row_for_current_user(self, auth_client, app, user):
        auth_client.post(_url(app, "add_expense"), data=_valid_payload())

        rows = _get_expenses_for_user(user["id"])
        assert len(rows) == 1, "Exactly one new expense row should be inserted"
        row = rows[0]
        assert row["amount"] == 50.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_post_valid_expense_without_description_stores_null(self, auth_client, app, user):
        payload = _valid_payload(description="")
        resp = auth_client.post(_url(app, "add_expense"), data=payload)

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(_url(app, "profile"))

        rows = _get_expenses_for_user(user["id"])
        assert len(rows) == 1
        assert rows[0]["description"] is None, "Blank description must be stored as NULL"

    def test_post_valid_expense_with_whitespace_only_description_stores_null(
        self, auth_client, app, user
    ):
        payload = _valid_payload(description="   ")
        resp = auth_client.post(_url(app, "add_expense"), data=payload)

        assert resp.status_code == 302
        rows = _get_expenses_for_user(user["id"])
        assert len(rows) == 1
        assert rows[0]["description"] is None, (
            "Whitespace-only description must be stripped and stored as NULL"
        )

    def test_post_new_expense_appears_on_profile_page(self, auth_client, app):
        auth_client.post(_url(app, "add_expense"), data=_valid_payload(description="Lunch combo"))

        profile_html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert "Lunch combo" in profile_html, "Newly added expense must show up in the profile's transaction list"

    def test_post_valid_expense_only_visible_to_owning_user(
        self, auth_client, app, user, other_user
    ):
        auth_client.post(_url(app, "add_expense"), data=_valid_payload())

        assert _get_expenses_for_user(user["id"]) != []
        assert _get_expenses_for_user(other_user["id"]) == [], (
            "A new expense must be attributed only to the logged-in user"
        )


# ----------------------------------------------------------------------- #
# POST /expenses/add — validation errors                                  #
# ----------------------------------------------------------------------- #

class TestAddExpenseValidation:
    def test_post_missing_amount_rerenders_form_with_error(self, auth_client, app, user):
        payload = _valid_payload(amount="")
        resp = auth_client.post(_url(app, "add_expense"), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, "Validation failure must re-render the form, not redirect"
        assert _has_error_message(html), "Missing amount must display an error message"
        assert _get_expenses_for_user(user["id"]) == [], "Invalid data must never be inserted"

    @pytest.mark.parametrize("bad_amount", ["0", "-5", "abc", "", "   "])
    def test_post_invalid_amount_rerenders_form_without_inserting(
        self, auth_client, app, user, bad_amount
    ):
        payload = _valid_payload(amount=bad_amount)
        resp = auth_client.post(_url(app, "add_expense"), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, (
            f"amount={bad_amount!r} must be rejected and re-render the form"
        )
        assert _has_error_message(html), f"amount={bad_amount!r} must display an error message"
        assert _get_expenses_for_user(user["id"]) == [], (
            f"amount={bad_amount!r} must never be inserted into the database"
        )

    def test_post_invalid_category_rerenders_form_with_error(self, auth_client, app, user):
        payload = _valid_payload(category="Vacation")
        resp = auth_client.post(_url(app, "add_expense"), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert _has_error_message(html), "Invalid category must display an error message"
        assert _get_expenses_for_user(user["id"]) == [], (
            "A category outside the fixed list must never be inserted"
        )

    def test_post_blank_category_rerenders_form_with_error(self, auth_client, app, user):
        payload = _valid_payload(category="")
        resp = auth_client.post(_url(app, "add_expense"), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert _has_error_message(html), "Blank category must display an error message"
        assert _get_expenses_for_user(user["id"]) == []

    @pytest.mark.parametrize(
        "bad_date", ["not-a-date", "2024-13-01", "2024/01/31", "", "32-01-2024"]
    )
    def test_post_invalid_date_rerenders_form_without_inserting(
        self, auth_client, app, user, bad_date
    ):
        payload = _valid_payload(date=bad_date)
        resp = auth_client.post(_url(app, "add_expense"), data=payload)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, f"date={bad_date!r} must be rejected"
        assert _has_error_message(html), f"date={bad_date!r} must display an error message"
        assert _get_expenses_for_user(user["id"]) == [], (
            f"date={bad_date!r} must never be inserted into the database"
        )

    def test_post_validation_error_retains_amount_and_description_on_bad_date(
        self, auth_client, app
    ):
        payload = _valid_payload(date="not-a-date", amount="77.25", description="Keep me")
        html = auth_client.post(_url(app, "add_expense"), data=payload).get_data(as_text=True)

        assert _input_value(html, "amount") == "77.25", (
            "Previously submitted amount must be pre-filled after a validation error"
        )
        assert _input_value(html, "description") == "Keep me", (
            "Previously submitted description must be pre-filled after a validation error"
        )
        assert _selected_category(html) == "Food", (
            "Previously submitted (valid) category must remain selected after an unrelated error"
        )

    def test_post_validation_error_retains_date_and_category_on_bad_amount(
        self, auth_client, app
    ):
        payload = _valid_payload(amount="not-a-number", date="2026-05-05", category="Bills")
        html = auth_client.post(_url(app, "add_expense"), data=payload).get_data(as_text=True)

        assert _input_value(html, "date") == "2026-05-05", (
            "Previously submitted date must be pre-filled after a validation error"
        )
        assert _selected_category(html) == "Bills", (
            "Previously submitted (valid) category must remain selected after an unrelated error"
        )

    def test_post_sql_injection_style_description_is_handled_safely(self, auth_client, app, user):
        malicious = "Lunch'); DROP TABLE expenses; --"
        payload = _valid_payload(description=malicious)
        resp = auth_client.post(_url(app, "add_expense"), data=payload)

        assert resp.status_code == 302, "A SQL-injection-style description must be treated as plain text"

        rows = _get_expenses_for_user(user["id"])
        assert len(rows) == 1
        assert rows[0]["description"] == malicious, (
            "The malicious string must be stored verbatim via a parameterised query, not executed"
        )

        # The expenses table must genuinely still exist and be queryable.
        resp2 = auth_client.get(_url(app, "profile"))
        assert resp2.status_code == 200


# ----------------------------------------------------------------------- #
# Template integration — profile button + navbar link                     #
# ----------------------------------------------------------------------- #

class TestAddExpenseTemplateIntegration:
    def test_profile_page_links_to_add_expense(self, auth_client, app):
        html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert _url(app, "add_expense") in html, (
            "Profile page must contain an 'Add Expense' link/button to /expenses/add"
        )

    def test_navbar_shows_add_expense_link_when_logged_in(self, auth_client, app):
        html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        assert "Add Expense" in html

    def test_navbar_hides_add_expense_link_when_logged_out(self, client, app):
        html = client.get(_url(app, "landing")).get_data(as_text=True)
        assert _url(app, "add_expense") not in html, (
            "Navbar must not show the Add Expense link to logged-out visitors"
        )
