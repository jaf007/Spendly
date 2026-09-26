# Spec: Login and Logout

## Overview
This step implements session-based authentication for Spendly. The `/login` route currently only renders a static form (`templates/login.html`) — submitting it does nothing — and `/logout` is a placeholder that returns the plain string "Logout — coming in Step 3". This step wires up the `POST` side of login: verifying the submitted email/password against the `users` table created in Step 1, and starting a Flask session on success. It also implements `/logout` to end that session. The nav bar in `base.html` is updated to reflect whether a visitor is signed in. This step does not build the `/profile` page itself (that's Step 4) — it only makes `/profile` reachable as a logged-in destination.

## Depends on
- Step 1 (Database Setup) — `get_db()`, `init_db()`, and the `users` table (`id`, `email`, `password_hash`) must exist. Confirmed implemented in `database/db.py`.
- Step 2 (Registration) — accounts must be creatable via `/register` so there are credentials to log in with. Confirmed implemented in `app.py`.

## Routes
- `GET /login` — render the login form (already implemented, unchanged)
- `POST /login` — validate email/password against `users`, start a session on success, redirect to `/profile` — public
- `GET /logout` — clear the session, redirect to `/` (landing page) — logged-in (harmless if called while logged out)

## Database changes
No database changes. The existing `users` table (`id`, `name`, `email` UNIQUE, `password_hash`, `created_at`) already has every column login needs.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html` — repopulate the `email` field value on a failed login attempt (mirrors what registration does for its fields), so the user doesn't have to retype it.
  - `templates/base.html` — nav links become conditional: when `session.get('user_id')` is set, show a link to `/profile` and a "Sign out" link (`/logout`); otherwise show the existing "Sign in" / "Get started" links.

## Files to change
- `app.py` —
  - Set `app.secret_key` (required for Flask sessions to work; hardcoded dev value is fine, this project has no env-based config elsewhere).
  - Update `/login` to accept `GET` and `POST`; on `POST`, look up the user by email, verify the password with `check_password_hash`, and either set `session["user_id"]` and redirect to `/profile`, or re-render the form with a generic error.
  - Implement `/logout` to call `session.clear()` (or pop `user_id`) and redirect to `landing`.
- `templates/base.html` — wrap the nav links in a conditional on `session.get('user_id')`.
- `templates/login.html` — repopulate `email` value from the form on error.

## Files to create
None.

## New dependencies
No new dependencies. Flask's built-in `session` object and `werkzeug.security.check_password_hash` (pairs with `generate_password_hash`, already used in `database/db.py`) cover everything needed.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug — verify with `check_password_hash`, never compare plaintext
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use Flask's built-in `session` (signed cookies via `app.secret_key`) — do not build custom token/cookie logic
- Store only `session["user_id"]` (the integer id) — never the password hash or full user row — in the session
- Return one generic error ("Invalid email or password") for both "email not found" and "wrong password" cases, to avoid revealing which emails are registered
- On successful login, redirect (HTTP redirect, not just a render) to `/profile` so a page refresh doesn't resubmit the form

## Definition of done
- [ ] Visiting `/login` still shows the form (GET unchanged)
- [ ] Submitting valid credentials (e.g. `demo@spendly.com` / `demo123`, seeded by `seed_db()`) redirects to `/profile` and sets a session cookie
- [ ] Submitting an unknown email, or a known email with the wrong password, re-renders `/login` with a generic "Invalid email or password" error and does not set a session
- [ ] After logging in, the nav bar shows "Sign out" and a profile link instead of "Sign in" / "Get started"
- [ ] Visiting `/logout` clears the session and redirects to the landing page
- [ ] After logging out, the nav bar reverts to showing "Sign in" / "Get started", and the browser can no longer reach `/profile` as if logged in (session is actually cleared, not just hidden in the nav)
- [ ] No unhandled exceptions/stack traces appear for any of the above cases
- [ ] `app.py` still starts cleanly with `python app.py` and existing routes are unaffected
