import calendar
import sqlite3
from datetime import date, datetime

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, init_db, seed_db

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    user_name = None
    if "user_id" in session:
        conn = get_db()
        try:
            user = conn.execute(
                "SELECT name FROM users WHERE id = ?", (session["user_id"],)
            ).fetchone()
        finally:
            conn.close()
        if user is not None:
            user_name = user["name"]
    return render_template("landing.html", user_name=user_name)


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("landing"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password or not confirm_password:
            return render_template(
                "register.html", error="All fields are required.", name=name, email=email
            )

        if len(password) < 4:
            return render_template(
                "register.html",
                error="Password must be at least 4 characters.",
                name=name,
                email=email,
            )

        if password != confirm_password:
            return render_template(
                "register.html",
                error="Passwords do not match.",
                name=name,
                email=email,
            )

        conn = get_db()
        try:
            password_hash = generate_password_hash(password)
            try:
                conn.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                    (name, email, password_hash),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return render_template(
                    "register.html",
                    error="That email is already registered.",
                    name=name,
                    email=email,
                )
        finally:
            conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("profile"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        try:
            user = conn.execute(
                "SELECT id, password_hash FROM users WHERE email = ?", (email,)
            ).fetchone()
        finally:
            conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template(
                "login.html", error="Invalid email or password.", email=email
            )

        session["user_id"] = user["id"]
        return redirect(url_for("profile"))

    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    date_from = _parse_date(request.args.get("date_from"))
    date_to = _parse_date(request.args.get("date_to"))

    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.")
        date_from = date_to = None
    elif not (date_from and date_to):
        date_from = date_to = None

    today = date.today()
    presets = [
        {"key": "this_month", "label": "This Month",
         "date_from": today.replace(day=1), "date_to": today},
        {"key": "last_3_months", "label": "Last 3 Months",
         "date_from": _months_ago(today, 3), "date_to": today},
        {"key": "last_6_months", "label": "Last 6 Months",
         "date_from": _months_ago(today, 6), "date_to": today},
        {"key": "all_time", "label": "All Time",
         "date_from": None, "date_to": None},
    ]

    for preset in presets:
        preset["active"] = (
            date_from == preset["date_from"] and date_to == preset["date_to"]
        )

    if any(preset["active"] for preset in presets):
        active_filter = next(preset["key"] for preset in presets if preset["active"])
    elif date_from and date_to:
        active_filter = "custom"
    else:
        active_filter = "all_time"

    period_label = {
        "this_month": "this month",
        "last_3_months": "last 3 months",
        "last_6_months": "last 6 months",
        "all_time": "all time",
        "custom": "custom range",
    }[active_filter]

    for preset in presets:
        preset["date_from"] = preset["date_from"].isoformat() if preset["date_from"] else None
        preset["date_to"] = preset["date_to"].isoformat() if preset["date_to"] else None

    iso_from = date_from.isoformat() if date_from else None
    iso_to = date_to.isoformat() if date_to else None

    conn = get_db()
    try:
        user_row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        name_parts = user_row["name"].split()
        initials = "".join(part[0] for part in name_parts[:2]).upper()
        member_since = datetime.strptime(
            user_row["created_at"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%B %Y")

        user = {
            "name": user_row["name"],
            "email": user_row["email"],
            "initials": initials,
            "member_since": member_since,
        }

        summary_stats = _get_summary_stats(conn, user_id, iso_from, iso_to, period_label)
        transactions = _get_recent_transactions(conn, user_id, date_from=iso_from, date_to=iso_to)
        category_breakdown = _get_category_breakdown(conn, user_id, iso_from, iso_to)
    finally:
        conn.close()

    return render_template(
        "profile.html",
        user=user,
        summary_stats=summary_stats,
        transactions=transactions,
        category_breakdown=category_breakdown,
        presets=presets,
        active_filter=active_filter,
        filter_from=iso_from or "",
        filter_to=iso_to or "",
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


# ------------------------------------------------------------------ #
# Profile page data helpers                                           #
# ------------------------------------------------------------------ #

def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _date_filter_clause(date_from, date_to):
    if date_from and date_to:
        return " AND date BETWEEN ? AND ?", [date_from, date_to]
    return "", []


def _months_ago(d, months):
    month_index = d.month - 1 - months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _get_recent_transactions(conn, user_id, limit=None, date_from=None, date_to=None):
    clause, clause_params = _date_filter_clause(date_from, date_to)
    limit_clause = " LIMIT ?" if limit is not None else ""
    limit_params = [limit] if limit is not None else []
    rows = conn.execute(
        "SELECT date, description, category, amount FROM expenses "
        f"WHERE user_id = ?{clause} ORDER BY date DESC, id DESC{limit_clause}",
        [user_id, *clause_params, *limit_params],
    ).fetchall()

    return [
        {
            "date": datetime.strptime(row["date"], "%Y-%m-%d").strftime("%d %b %Y"),
            "description": row["description"],
            "category": row["category"],
            "amount": f"₹{row['amount']:,.2f}",
        }
        for row in rows
    ]


def _get_summary_stats(conn, user_id, date_from=None, date_to=None, period_label="all time"):
    clause, clause_params = _date_filter_clause(date_from, date_to)

    total_row = conn.execute(
        f"SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id = ?{clause}",
        [user_id, *clause_params],
    ).fetchone()
    total = total_row["total"]

    count_row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM expenses WHERE user_id = ?{clause}",
        [user_id, *clause_params],
    ).fetchone()
    count = count_row["cnt"]

    if total == 0 or count == 0:
        top_category_stat = {
            "label": "Top category",
            "value": "—",
            "delta": "no spend yet",
            "delta_style": "muted",
        }
    else:
        top_category_row = conn.execute(
            f"""
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE user_id = ?{clause}
            GROUP BY category
            ORDER BY total DESC
            LIMIT 1
            """,
            [user_id, *clause_params],
        ).fetchone()
        pct = round(top_category_row["total"] / total * 100)
        top_category_stat = {
            "label": "Top category",
            "value": top_category_row["category"],
            "delta": f"{pct}% of spend",
            "delta_style": "positive",
        }

    return [
        {
            "label": "Total spent",
            "value": f"₹{total:,.2f}",
            "delta": period_label,
            "delta_style": "muted",
        },
        {
            "label": "Transactions",
            "value": str(count),
            "delta": period_label,
            "delta_style": "muted",
        },
        top_category_stat,
    ]


def _get_category_breakdown(conn, user_id, date_from=None, date_to=None):
    clause, clause_params = _date_filter_clause(date_from, date_to)
    rows = conn.execute(
        "SELECT category, SUM(amount) AS total FROM expenses "
        f"WHERE user_id = ?{clause} GROUP BY category ORDER BY total DESC",
        [user_id, *clause_params],
    ).fetchall()

    if not rows:
        return []

    max_total = rows[0]["total"]

    breakdown = []
    for row in rows:
        pct = round((row["total"] / max_total) * 10) * 10
        pct = max(10, min(100, pct))
        breakdown.append(
            {
                "name": row["category"],
                "amount": f"₹{row['total']:,.2f}",
                "width_class": f"w-{pct}",
            }
        )

    return breakdown


# ------------------------------------------------------------------ #
# Database bootstrap                                                  #
# ------------------------------------------------------------------ #

with app.app_context():
    init_db()
    seed_db()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
