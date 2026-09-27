# 0001: Technology stack

- Status: accepted
- Date: 2026-09-26
- Deciders: maintainers

## Context

The brief fixes most of the stack. M0 review settled the open points: React and Tailwind versions (plan question 9), the docs generator (question 10) and the packages the brief does not name. This ADR records the stack as built so later changes have a baseline.

## Decision

| Layer | Choice | Version in M0 |
| --- | --- | --- |
| Python | CPython 3.12, `mypy --strict`, ruff | 3.12 |
| Packaging | uv with `uv.lock`; pnpm with `pnpm-lock.yaml` | uv 0.12, pnpm 12 |
| API | FastAPI, Pydantic v2, pydantic-settings, uvicorn | FastAPI 0.141 |
| Database | PostgreSQL 16, SQLAlchemy 2, Alembic, psycopg 3 | SQLAlchemy 2.0 |
| Password hashing | argon2-cffi (Argon2id) | 25.1 |
| CLI | Typer | 0.27 |
| Front end | React 19, TypeScript 5 strict, Vite, Tailwind CSS v4, shadcn/ui patterns on Radix, TanStack Query, lucide-react | React 19.3, Vite 8, Tailwind 4.3 |
| Fonts | Inter, self-hosted through `@fontsource-variable/inter` | 5.3 |
| Tests | pytest, pytest-cov, Testcontainers, httpx; Vitest, Testing Library, jsdom, Playwright, axe-core | |
| Lint and format | ruff; ESLint with typescript-eslint (strict type-checked), react-hooks, jsx-a11y (strict); Prettier for the web package | |
| Docs | MkDocs Material | 9.7 |
| Node | Node.js 24 LTS | 24 |

Choices that differ from the brief's table:

- React 19 instead of 18. Current shadcn/ui guidance and Tailwind v4 target React 19, and React 18 receives no new features. Approved in M0 review.
- TypeScript stays on 5.9 as the brief says, although TypeScript 7 has shipped. Moving to 7 is a separate decision.
- SQLAlchemy resolves to 2.0.x under the one-week cooldown (see ADR-0005); 2.1 will arrive through Dependabot.

Scheduling (APScheduler), charts (ECharts), tables (TanStack Table), reports (Jinja2, WeasyPrint, openpyxl), crypto (`cryptography`) and OIDC (Authlib) are named in the brief but not installed until the milestone that uses them.

## Consequences

- Every package outside the brief's list needs approval before it is added. This ADR is the record of what was approved in M0.
- Material for MkDocs is in maintenance mode and its authors are building Zensical, which reads `mkdocs.yml`. MkDocs 2.0 removes the plugin and theme system Material needs, so `pyproject.toml` caps MkDocs below 2.0. We keep the configuration plain so a switch to Zensical before v1.0 is cheap.
- Starlette now recommends `httpx2` for its test client. We stay on `httpx` (approved) and filter that one deprecation warning in pytest. Switching is an open question for M1.
