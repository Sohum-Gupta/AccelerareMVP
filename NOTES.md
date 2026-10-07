# NOTES

Things learned the hard way. Add an entry whenever something non-obvious comes up.

- 2026-10-07: `uv init` creates a packaged `src/` layout with a `[build-system]`; removed it because a Django site is an app, not a library.
- 2026-10-07: Django 6.1 configures email with `MAILERS = {"default": {...}}`, not `EMAIL_BACKEND`.
