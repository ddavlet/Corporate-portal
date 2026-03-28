# Kolberg Project — Claude Code Context

## Stack
- Django v2 (backend_v2 at /projects/backend_v2)
- PostgreSQL with pgvector (host: db, port: 5432)
- n8n for automation workflows
- Traefik as reverse proxy
- Gunicorn as WSGI server

## Projects
- `backend_v2` → newer Django app, serves lemonfit/neuron/lemonfit2 tenants

## Important conventions
- After editing models, always mention that migrations need to be run:
  `docker exec django python manage.py migrate`
- After editing code, Django auto-reloads via gunicorn (no restart needed in debug mode)
- Database changes: coordinate with the Postgres container (host=db)
- Never hardcode secrets — use environment variables from docker-compose

## Workflow notes
- Commands are received via Telegram voice messages (transcribed to text)
- Keep responses concise — they will be read as Telegram messages
- When making file changes, briefly summarize what was changed and why

## Git autopush policy (mandatory)
- After completing code changes, always run:
  - `git add -A`
  - `git commit -m "<type>: <short summary>"`
  - `git push`
- If there are no changes, do not create an empty commit.
- Never delete files or directories unless explicitly approved by the user.
- Never run destructive commands:
  - `git reset --hard`
  - `git clean -fd`
  - `git checkout -- <file>`
  - `rm -rf`
- Never force push: `git push --force`
- Never push directly to `main` or `master`; use a feature branch.
- If tests or lint fail, stop and report errors before commit/push.
- If push fails, report exact error and stop.
