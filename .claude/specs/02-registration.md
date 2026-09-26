# Spec: Registration

## Overview
This step implements account creation for Spendly. The `/register` route currently only renders a static form (`templates/register.html`) — submitting it does nothing. This step wires up the `POST` side: validating input, checking for duplicate emails, hashing the password, and inserting a new row into the existing `users` table. It does **not** introduce sessions or log the new user in automatically — session-based login/logout is a separate, later step (see the `/logout` placeholder in `app.py`, marked "coming in Step 3"). After successful registration, the user is redirected to `/login` to sign in with their new credentials.

## Depends on
- Step 1 (Database Setup) — `get_db()`, `init_db()`, and the `users` table must exist. Confirmed implemented in `database/db.py`.

## Routes
- `GET /register` — render the registration form (already implemented, unchanged)
- `POST /register` — process the registration form: validate fields, hash password, insert user, redirect to `/login` on success or re-render the form with an error on failure — public

## Database changes
No database changes. The existing `users` table (`id`, `name`, `email` UNIQUE, `password_hash`, `created_at`) already has every column registration needs.

## Templates
- **Create:** none
- **Modify:** `templates/register.html` — no structural changes needed; it already posts to `/register` and already renders `{{ error }}` when present. Optionally repopulate `name`/`email` field values on validation failure so the user doesn't have to retype them.

## Files to change
- `app.py` — update the `/register` route to accept `GET` and `POST`, handle form validation, duplicate-email detection, password hashing, DB insert, and redirect.

## Files to create
None.

## New dependencies
No new dependencies. `werkzeug.security.generate_password_hash` (already used in `database/db.py`) and `flask.request`/`redirect`/`url_for` (already part of installed Flask) cover everything needed.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (`generate_password_hash`)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Validate required fields (`name`, `email`, `password`) are non-empty server-side, not just via HTML `required`
- Enforce a minimum password length (8 characters, matching the form's placeholder text) server-side
- Catch the `sqlite3.IntegrityError` from the `email UNIQUE` constraint and show a friendly "email already registered" error instead of a stack trace
- Do not create a session or log the user in — registration only creates the account
- On success, redirect (HTTP redirect, not just a render) to `/login` so a page refresh doesn't resubmit the form

## Definition of done
- [ ] Visiting `/register` still shows the form (GET unchanged)
- [ ] Submitting the form with valid, unique data creates a new row in `users` with a hashed (not plaintext) password
- [ ] After a successful submission, the browser is redirected to `/login`
- [ ] Submitting with an email that already exists (e.g. `demo@spendly.com`) re-renders `/register` with a visible error and does not create a duplicate row
- [ ] Submitting with a missing field or a password under 8 characters re-renders `/register` with a visible error and does not hit the database
- [ ] No unhandled exceptions/stack traces appear for any of the above cases
- [ ] `app.py` still starts cleanly with `python app.py` and existing routes are unaffected
