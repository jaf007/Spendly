# Spec: Backend Routes For Profile Page

## Overview
This feature replaces the hardcoded, placeholder data on the `/profile` route (introduced in Step 4's UI-only build) with real queries against the `users` and `expenses` tables. The profile page will now show the logged-in user's actual name/email/member-since date, live summary stats, their real recent transactions, and a real per-category spending breakdown — all computed from the database instead of fixed Python literals.

## Depends on
- Step 1: Database setup (`users` and `expenses` tables must exist)
- Step 2: Registration (user accounts must be creatable)
- Step 3: Login + Logout (session must be set; `/profile` must be a protected route)
- Step 4: Profile page design (template `profile.html` and its expected context shape — `user`, `summary_stats`, `transactions`, `category_breakdown` — already exist and are not changing)

## Routes
No new routes. The existing `GET /profile` route is modified in place — same path, same auth guard — only its data source changes from hardcoded literals to database queries.

## Database changes
No database changes. The existing `users` table (`name`, `email`, `created_at`) and `expenses` table (`user_id`, `amount`, `category`, `date`, `description`) are sufficient for every value the page needs.

## Templates
- **Create:** none
- **Modify:** none — `templates/profile.html` already consumes `user`, `summary_stats`, `transactions`, `category_breakdown` in the exact shape the new view function will produce; no template edits needed.

## Files to change
- `app.py` — rewrite the body of the `profile()` view function:
  - Keep the existing auth guard (`redirect` to `/login` if `user_id` not in session).
  - Query the current user's `name`, `email`, `created_at` from `users`; derive `initials` from the name (first letter of up to the first two words, uppercase) and `member_since` by formatting `created_at` as `"%B %Y"`.
  - Query all of the user's expenses to compute:
    - `summary_stats`: total spent (`SUM(amount)`), transaction count (`COUNT(*)`), and top category (category with the highest summed amount) — formatted into the same `{label, value, delta, delta_style}` shape the template expects.
    - `transactions`: the user's most recent expenses (ordered by `date` descending, limited to a reasonable number, e.g. 5), each formatted into `{date, description, category, amount}` with `date` rendered as `"DD Mon YYYY"` and `amount` rendered as a `₹`-prefixed, comma-grouped string.
    - `category_breakdown`: per-category totals (`GROUP BY category`, ordered by total descending), each formatted into `{name, amount, width_class}`, where `width_class` is the category's share of the highest category total rounded to the nearest available `w-10`…`w-100` CSS class.
  - Handle the zero-expenses case (new user with no transactions yet) without raising — empty `transactions`/`category_breakdown` lists and zeroed/placeholder `summary_stats` values.

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — use raw sqlite3 via `get_db()`
- Parameterised queries only — never string-format SQL
- Passwords hashed with werkzeug (unchanged in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html` (unchanged in this step — no template edits)
- Close every DB connection (`conn.close()` in a `finally` block), consistent with the existing routes
- Keep all formatting/derivation logic (initials, member-since, currency strings, width classes) in `app.py` — no new helper modules

## Definition of done
- [ ] Visiting `/profile` without being logged in redirects to `/login`
- [ ] Visiting `/profile` while logged in returns HTTP 200
- [ ] The user info card shows the real logged-in user's name and email (not "Nitish Kumar" / "nitish@example.com")
- [ ] The "member since" date reflects the user's real `created_at` value, formatted as a month and year
- [ ] Summary stats (total spent, transaction count, top category) match the sum/count/grouping of that user's actual rows in `expenses`
- [ ] The transaction history table lists that user's real expenses, most recent first
- [ ] The category breakdown section reflects real `SUM(amount)` per category for that user, with bar widths proportional to the highest category
- [ ] Logging in as a different seeded/created user shows that user's own data, not another user's
- [ ] A user with zero expenses sees the page render without errors (empty table, zeroed stats)
