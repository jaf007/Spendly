import sqlite3

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

        if len(password) < 8:
            return render_template(
                "register.html",
                error="Password must be at least 8 characters.",
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

    user = {
        "name": "Nitish Kumar",
        "email": "nitish@example.com",
        "initials": "NK",
        "member_since": "March 2024",
    }

    summary_stats = [
        {"label": "Total spent", "value": "₹28,540", "delta": "this year", "delta_style": "muted"},
        {"label": "Transactions", "value": "47", "delta": "all time", "delta_style": "muted"},
        {"label": "Top category", "value": "Food", "delta": "32% of spend", "delta_style": "positive"},
    ]

    transactions = [
        {"date": "12 Oct 2026", "description": "Groceries at Whole Foods", "category": "Food", "amount": "₹1,240.00"},
        {"date": "10 Oct 2026", "description": "Uber ride to work", "category": "Transport", "amount": "₹380.00"},
        {"date": "05 Oct 2026", "description": "Electricity bill", "category": "Bills", "amount": "₹2,150.00"},
        {"date": "01 Oct 2026", "description": "Movie tickets", "category": "Entertainment", "amount": "₹640.00"},
        {"date": "28 Sep 2026", "description": "Pharmacy — prescription refill", "category": "Health", "amount": "₹520.00"},
    ]

    category_breakdown = [
        {"name": "Food", "amount": "₹9,120", "width_class": "w-80"},
        {"name": "Bills", "amount": "₹6,440", "width_class": "w-60"},
        {"name": "Transport", "amount": "₹4,980", "width_class": "w-50"},
        {"name": "Entertainment", "amount": "₹3,210", "width_class": "w-40"},
    ]

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
# Database bootstrap                                                  #
# ------------------------------------------------------------------ #

with app.app_context():
    init_db()
    seed_db()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
