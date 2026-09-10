# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Spendly is a Flask-based expense tracker built as a step-by-step learning project. The codebase is intentionally scaffolded incrementally: many routes and the database layer exist only as placeholders with comments describing what a future "step" will implement. Do not assume unimplemented functionality is a bug — check `app.py` and `database/db.py` for "Step N" / "coming in Step N" markers before building on top of a route.

## Commands

```bash
# Activate the virtualenv (already created in ./venv)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the dev server (http://localhost:5001)
python app.py

# Run tests
pytest
```

There is no lint/format tooling configured in this repo.

## Architecture

- **`app.py`** — single Flask app with all routes defined directly on it (no blueprints). Currently:
  - Implemented: `/`, `/register`, `/login`, `/terms`, `/privacy` — all just render a template.
  - Placeholder only (return plain strings, not yet built): `/logout`, `/profile`, `/expenses/add`, `/expenses/<id>/edit`, `/expenses/<id>/delete`.
  - Runs on port 5001 with `debug=True`.
- **`database/db.py`** — intended to hold `get_db()` (SQLite connection with `row_factory` and foreign keys enabled), `init_db()` (`CREATE TABLE IF NOT EXISTS` statements), and `seed_db()` (sample data). Not yet implemented.
- **`database/__init__.py`** — empty; expected to expose the db module's public functions once written.
- The SQLite file `expense_tracker.db` is gitignored and created at runtime — never commit it.
- **`templates/`** — Jinja2 templates. `base.html` defines the shared layout (nav, footer, font/CSS includes) and is extended by page templates via `{% block content %}`. Existing pages: `landing.html`, `login.html`, `register.html`, `terms.html`, `privacy.html`.
- **`static/css/style.css`** — single global stylesheet for the whole site (no per-page CSS files).
- **`static/js/main.js`** — currently minimal/near-empty; add client-side behavior here as needed.
- No authentication, session, or ORM layer exists yet — routes like login/register currently only render forms and don't process submissions.
