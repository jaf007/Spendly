import sqlite3
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for
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

        summary_stats = _get_summary_stats(conn, user_id)
        transactions = _get_recent_transactions(conn, user_id)
        category_breakdown = _get_category_breakdown(conn, user_id)
    finally:
        conn.close()

    return render_template(
        "profile.html",
        user=user,
        summary_stats=summary_stats,
        transactions=transactions,
        category_breakdown=category_breakdown,
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

def _get_recent_transactions(conn, user_id, limit=5):
    rows = conn.execute(
        "SELECT date, description, category, amount FROM expenses "
        "WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT ?",
        (user_id, limit),
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


def _get_summary_stats(conn, user_id):
    total_row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    total = total_row["total"]

    count_row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM expenses WHERE user_id = ?",
        (user_id,),
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
            """
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE user_id = ?
            GROUP BY category
            ORDER BY total DESC
            LIMIT 1
            """,
            (user_id,),
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
            "delta": "this year",
            "delta_style": "muted",
        },
        {
            "label": "Transactions",
            "value": str(count),
            "delta": "all time",
            "delta_style": "muted",
        },
        top_category_stat,
    ]


def _get_category_breakdown(conn, user_id):
    rows = conn.execute(
        "SELECT category, SUM(amount) AS total FROM expenses "
        "WHERE user_id = ? GROUP BY category ORDER BY total DESC",
        (user_id,),
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
