"""
Tests for Step 6 — "Date Filter for Profile Page".

Spec: .claude/specs/06-date-filter-profile.md

Behavior under test (via the real `GET /profile` route only — no internal
helpers are imported or called directly):
  - `/profile` reads optional `date_from` / `date_to` query params (ISO
    `YYYY-MM-DD`), inclusive bounds.
  - Missing or malformed params silently fall back to an unfiltered ("All
    Time") view.
  - `date_from > date_to` falls back to unfiltered AND flashes
    "Start date must be before end date."
  - The quick-select preset buttons ("This Month", "Last 3 Months",
    "Last 6 Months", "All Time") and the custom-range form must visually
    mark whichever filter is currently active.
  - Summary stats, recent transactions, and category breakdown must all
    respect the active filter, stay ₹-formatted, and remain isolated
    per-user.

IMPORTANT implementation detail discovered while writing fixtures:
`database/db.py`'s `get_db()` opens a brand-new `sqlite3.connect(DB_PATH)`
on every call (no connection pooling, no Flask `g`, no `app.config`
lookup) where `DB_PATH` is a plain module-level global. This means:
  * An in-memory `:memory:` database would be wiped between every single
    `get_db()` call, so a real temp *file* path must be used instead.
  * `app.py` also runs `init_db()` / `seed_db()` at **import time**
    (`with app.app_context(): init_db(); seed_db()`), against whatever
    `DB_PATH` is set at that moment. To avoid ever touching the real
    project's `expense_tracker.db`, `database.db.DB_PATH` is redirected to
    a throwaway bootstrap file *before* `app` is imported below.
  * Each test then gets its own isolated temp-file database by
    monkeypatching `database.db.DB_PATH` again inside the `app` fixture.
    Because `get_db` is the very same function object wherever it's
    imported from, patching the attribute on the `database.db` module is
    sufficient — no need to patch `app`'s local name.
"""

import html
import os
import re
import tempfile
from datetime import date, timedelta

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


def _add_expense(user_id, amount, category, iso_date, description=""):
    conn = db_module.get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, iso_date, description),
        )
        conn.commit()
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


# ----------------------------------------------------------------------- #
# HTML-scraping helpers (black-box — no implementation internals assumed)  #
# ----------------------------------------------------------------------- #

_PRESET_ANCHOR_RE = re.compile(
    r'<a href="([^"]+)"\s+class="(filter-preset-btn[^"]*)">\s*([^<]+?)\s*</a>',
    re.DOTALL,
)

_STAT_VALUE_RE_TEMPLATE = r'{label}</span>\s*<span class="stat-value">([^<]*)</span>'


def _preset_links(page_html):
    """Return {label: (href, is_active)} for the four quick-select buttons.

    Jinja autoescaping turns the literal "&" between query params into
    "&amp;" inside the href attribute, so hrefs must be HTML-unescaped
    before being used as a real request path.
    """
    links = {}
    for href, class_attr, label in _PRESET_ANCHOR_RE.findall(page_html):
        links[label.strip()] = (html.unescape(href), "filter-preset-btn-active" in class_attr)
    return links


def _custom_apply_is_active(html):
    return "filter-apply-btn-active" in html


def _stat_value(html, label):
    match = re.search(_STAT_VALUE_RE_TEMPLATE.format(label=re.escape(label)), html)
    return match.group(1).strip() if match else None


def _fmt_amount(amount):
    return f"₹{amount:,.2f}"


# ----------------------------------------------------------------------- #
# Auth guard                                                               #
# ----------------------------------------------------------------------- #

class TestProfileAuthGuard:
    def test_profile_without_session_redirects_to_login(self, client, app):
        resp = client.get(_url(app, "profile"))
        assert resp.status_code == 302, "Unauthenticated /profile should redirect, not render"
        assert resp.headers["Location"].endswith(
            _url(app, "login")
        ), "Unauthenticated /profile should redirect to the login page"

    def test_profile_with_date_params_still_requires_login(self, client, app):
        resp = client.get(_url(app, "profile", date_from="2024-01-01", date_to="2024-01-31"))
        assert resp.status_code == 302, (
            "Auth guard must apply even when date filter query params are present"
        )


# ----------------------------------------------------------------------- #
# Unfiltered baseline (Step 5 parity)                                      #
# ----------------------------------------------------------------------- #

class TestProfileUnfilteredBaseline:
    def test_profile_no_query_params_shows_all_expenses_and_all_time_active(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 100.0, "Food", "2023-01-15", "Old groceries")
        _add_expense(user["id"], 50.0, "Transport", date.today().isoformat(), "Today's cab")

        resp = auth_client.get(_url(app, "profile"))
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Old groceries" in html, "Unfiltered view must include old expenses"
        assert "Today&#39;s cab" in html, "Unfiltered view must include recent expenses"
        assert _stat_value(html, "Total spent") == _fmt_amount(150.0)
        assert _stat_value(html, "Transactions") == "2"

        links = _preset_links(html)
        assert links["All Time"][1] is True, "All Time preset must be active with no filter"
        for label in ("This Month", "Last 3 Months", "Last 6 Months"):
            assert links[label][1] is False, f"{label} must not be active with no filter"
        assert _custom_apply_is_active(html) is False

    def test_profile_with_zero_expenses_shows_zero_totals_and_empty_state(
        self, auth_client, app
    ):
        resp = auth_client.get(_url(app, "profile"))
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert _stat_value(html, "Total spent") == _fmt_amount(0.0)
        assert _stat_value(html, "Transactions") == "0"
        assert "No transactions found for this date range." in html
        assert "category-row" not in html, "No category rows should render for zero expenses"


# ----------------------------------------------------------------------- #
# Preset quick-select buttons — click the actual server-rendered link      #
# ----------------------------------------------------------------------- #

class TestProfilePresetFilters:
    def test_this_month_preset_link_filters_to_current_month(self, auth_client, app, user):
        today = date.today()
        first_of_month = today.replace(day=1)
        prev_month_day = first_of_month - timedelta(days=1)

        _add_expense(user["id"], 20.0, "Food", today.isoformat(), "In this month")
        _add_expense(user["id"], 999.0, "Bills", prev_month_day.isoformat(), "In prior month")

        baseline_html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        this_month_href, _ = _preset_links(baseline_html)["This Month"]

        resp = auth_client.get(this_month_href)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "In this month" in html
        assert "In prior month" not in html
        assert _stat_value(html, "Total spent") == _fmt_amount(20.0)
        assert _stat_value(html, "Transactions") == "1"
        assert _preset_links(html)["This Month"][1] is True

    def test_last_3_months_preset_link_filters_to_recent_window(self, auth_client, app, user):
        today = date.today()
        _add_expense(
            user["id"], 30.0, "Food", (today - timedelta(days=30)).isoformat(), "Within 3 months"
        )
        _add_expense(
            user["id"],
            999.0,
            "Bills",
            (today - timedelta(days=200)).isoformat(),
            "Older than 3 months",
        )

        baseline_html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        href, _ = _preset_links(baseline_html)["Last 3 Months"]

        resp = auth_client.get(href)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Within 3 months" in html
        assert "Older than 3 months" not in html
        assert _preset_links(html)["Last 3 Months"][1] is True

    def test_last_6_months_preset_link_filters_to_recent_window(self, auth_client, app, user):
        today = date.today()
        _add_expense(
            user["id"], 40.0, "Food", (today - timedelta(days=120)).isoformat(), "Within 6 months"
        )
        _add_expense(
            user["id"],
            999.0,
            "Bills",
            (today - timedelta(days=250)).isoformat(),
            "Older than 6 months",
        )

        baseline_html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        href, _ = _preset_links(baseline_html)["Last 6 Months"]

        resp = auth_client.get(href)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Within 6 months" in html
        assert "Older than 6 months" not in html
        assert _preset_links(html)["Last 6 Months"][1] is True

    def test_all_time_preset_link_clears_filter_and_shows_everything(
        self, auth_client, app, user
    ):
        today = date.today()
        _add_expense(
            user["id"], 15.0, "Food", (today - timedelta(days=400)).isoformat(), "Very old expense"
        )
        _add_expense(user["id"], 25.0, "Transport", today.isoformat(), "Recent expense")

        # Start from a filtered ("This Month") view, then click "All Time".
        filtered_html = auth_client.get(
            _url(app, "profile", date_from=today.replace(day=1).isoformat(), date_to=today.isoformat())
        ).get_data(as_text=True)
        all_time_href, _ = _preset_links(filtered_html)["All Time"]

        assert all_time_href == _url(app, "profile"), (
            "All Time preset must link to a clean /profile URL with no query params"
        )

        resp = auth_client.get(all_time_href)
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Very old expense" in html
        assert "Recent expense" in html
        assert _stat_value(html, "Transactions") == "2"
        assert _preset_links(html)["All Time"][1] is True


# ----------------------------------------------------------------------- #
# Custom date range                                                        #
# ----------------------------------------------------------------------- #

class TestProfileCustomDateRange:
    def test_custom_range_shows_only_expenses_within_inclusive_bounds(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 10.0, "Food", "2024-01-01", "Before range")
        _add_expense(user["id"], 20.0, "Food", "2024-02-01", "Start boundary")
        _add_expense(user["id"], 30.0, "Food", "2024-02-15", "Inside range")
        _add_expense(user["id"], 40.0, "Food", "2024-02-28", "End boundary")
        _add_expense(user["id"], 50.0, "Food", "2024-03-01", "After range")

        resp = auth_client.get(
            _url(app, "profile", date_from="2024-02-01", date_to="2024-02-28")
        )
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Before range" not in html
        assert "Start boundary" in html, "date_from bound must be inclusive"
        assert "Inside range" in html
        assert "End boundary" in html, "date_to bound must be inclusive"
        assert "After range" not in html
        assert _stat_value(html, "Total spent") == _fmt_amount(90.0)
        assert _stat_value(html, "Transactions") == "3"

    def test_custom_range_marks_apply_button_active_and_no_preset_active(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 10.0, "Food", "2024-02-15", "Inside range")

        resp = auth_client.get(
            _url(app, "profile", date_from="2024-02-01", date_to="2024-02-28")
        )
        html = resp.get_data(as_text=True)

        assert _custom_apply_is_active(html) is True
        links = _preset_links(html)
        for label, (_, active) in links.items():
            assert active is False, f"{label} preset must not show active for an unrelated custom range"


# ----------------------------------------------------------------------- #
# Validation errors                                                        #
# ----------------------------------------------------------------------- #

class TestProfileValidation:
    def test_date_from_after_date_to_falls_back_unfiltered_with_flash(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 10.0, "Food", "2023-01-01", "Old expense")
        _add_expense(user["id"], 20.0, "Food", "2024-06-01", "Newer expense")

        resp = auth_client.get(
            _url(app, "profile", date_from="2024-06-01", date_to="2023-01-01")
        )
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Start date must be before end date." in html
        assert "Old expense" in html, "Invalid range should fall back to unfiltered data"
        assert "Newer expense" in html
        assert _preset_links(html)["All Time"][1] is True

    @pytest.mark.parametrize(
        "bad_date_from",
        ["not-a-date", "2024/01/31", "2024-13-01", "", "2024-01-01T00:00:00"],
    )
    def test_malformed_date_from_falls_back_silently(
        self, auth_client, app, user, bad_date_from
    ):
        _add_expense(user["id"], 10.0, "Food", "2023-01-01", "Old expense")

        resp = auth_client.get(
            _url(app, "profile", date_from=bad_date_from, date_to="2024-01-01")
        )
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, "Malformed date_from must not crash the app"
        assert "Start date must be before end date." not in html, (
            "Malformed input is a silent fallback, not a validation-error flash"
        )
        assert "Old expense" in html, "Malformed date_from should fall back to unfiltered view"
        assert _preset_links(html)["All Time"][1] is True

    def test_malformed_date_to_falls_back_silently(self, auth_client, app, user):
        _add_expense(user["id"], 10.0, "Food", "2023-01-01", "Old expense")

        resp = auth_client.get(
            _url(app, "profile", date_from="2024-01-01", date_to="banana")
        )
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Start date must be before end date." not in html
        assert "Old expense" in html

    def test_only_date_from_without_date_to_falls_back_unfiltered(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 10.0, "Food", "2023-01-01", "Old expense")

        resp = auth_client.get(_url(app, "profile", date_from="2024-01-01"))
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Old expense" in html, "A single-sided date param must fall back to unfiltered"
        assert _preset_links(html)["All Time"][1] is True

    def test_only_date_to_without_date_from_falls_back_unfiltered(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 10.0, "Food", "2023-01-01", "Old expense")

        resp = auth_client.get(_url(app, "profile", date_to="2024-01-01"))
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Old expense" in html
        assert _preset_links(html)["All Time"][1] is True

    def test_sql_injection_style_date_param_falls_back_safely(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 10.0, "Food", "2023-01-01", "Old expense")
        malicious = "2024-01-01'; DROP TABLE expenses; --"

        resp = auth_client.get(
            _url(app, "profile", date_from=malicious, date_to="2024-01-01")
        )
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, "A SQL-injection-style date_from must not crash the app"
        assert "Old expense" in html, (
            "Non-ISO date_from is treated as malformed input, not executed as SQL"
        )

        # The expenses table must genuinely still exist and be queryable.
        resp2 = auth_client.get(_url(app, "profile"))
        assert resp2.status_code == 200
        assert "Old expense" in resp2.get_data(as_text=True)


# ----------------------------------------------------------------------- #
# Multi-user isolation                                                     #
# ----------------------------------------------------------------------- #

class TestProfileMultiUserIsolation:
    def test_filtered_profile_excludes_other_users_expenses_in_same_range(
        self, auth_client, app, user, other_user
    ):
        _add_expense(user["id"], 10.0, "Food", "2024-02-10", "Alice in range")
        _add_expense(other_user["id"], 999.0, "Bills", "2024-02-11", "Bob in range")

        resp = auth_client.get(
            _url(app, "profile", date_from="2024-02-01", date_to="2024-02-28")
        )
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200
        assert "Alice in range" in html
        assert "Bob in range" not in html, "A filtered view must never leak another user's expenses"
        assert _stat_value(html, "Total spent") == _fmt_amount(10.0)
        assert _stat_value(html, "Transactions") == "1"

    def test_unfiltered_profile_excludes_other_users_expenses(
        self, auth_client, app, user, other_user
    ):
        _add_expense(user["id"], 10.0, "Food", "2024-02-10", "Alice expense")
        _add_expense(other_user["id"], 999.0, "Bills", "2024-02-10", "Bob expense")

        resp = auth_client.get(_url(app, "profile"))
        html = resp.get_data(as_text=True)

        assert "Alice expense" in html
        assert "Bob expense" not in html, "Even unfiltered, profile must only show the session user's data"
        assert _stat_value(html, "Total spent") == _fmt_amount(10.0)


# ----------------------------------------------------------------------- #
# Formatting / rendering invariants                                        #
# ----------------------------------------------------------------------- #

class TestProfileResponseFormatting:
    def test_rupee_symbol_present_in_filtered_and_unfiltered_views(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 42.0, "Food", "2024-02-10", "Lunch")

        unfiltered_html = auth_client.get(_url(app, "profile")).get_data(as_text=True)
        filtered_html = auth_client.get(
            _url(app, "profile", date_from="2024-02-01", date_to="2024-02-28")
        ).get_data(as_text=True)

        assert "₹" in unfiltered_html
        assert "₹" in filtered_html

    def test_filtered_empty_range_shows_zero_state_without_error(
        self, auth_client, app, user
    ):
        _add_expense(user["id"], 42.0, "Food", "2023-01-01", "Far outside the query range")

        resp = auth_client.get(
            _url(app, "profile", date_from="2024-05-01", date_to="2024-05-31")
        )
        html = resp.get_data(as_text=True)

        assert resp.status_code == 200, "An empty filtered result set must not error out"
        assert _stat_value(html, "Total spent") == _fmt_amount(0.0)
        assert _stat_value(html, "Transactions") == "0"
        assert "No transactions found for this date range." in html
        assert "category-row" not in html
        assert "—" in html, "Top category stat should show the empty-state placeholder"
