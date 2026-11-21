# FormProof (COI Cyfryzacja formularzy)

Stan projektu: `hackathon/STATE.md`. Plan: `hackathon/plan.md`. Brief/idea obok.

## Stack
Python 3.14 + uv, FastAPI, pydantic v2, Docker `python:3.14.0-alpine3.22` (user `app`), Ollama (lokalny LLM). UI: `web/` czysty HTML+JS (bez Node). Zero SaaS/LLM-API w runtime (regulamin). Licencje: bez GPL/AGPL.

## Komendy
- `uv run python -m formproof` – API na :8000 (UI pod `/`, OpenAPI `/docs`)
- `uv run pytest`; `uv run mypy src`; `uv run ruff check src tests scripts`; `uv run ruff format src tests scripts`
- `uv run python scripts/license_check.py` – blokuje copyleft
- `docker compose up --build` – api + ollama
- `uv run python scripts/eval/run.py` – porównanie z `tests/fixtures/expected1.json` (runda 2)

## Zasady
- Pliki formularzy tylko w pamięci na czas żądania.
- Zero hardkodu pod konkretne pliki/tytuły (obrona na nowych plikach).
- `form` w odpowiedzi = czysty JSON wg schemy COI (`FormDefinition.dump()`); confidence/source tylko w `report`.
- Kontrakty (`src/formproof/types/**`) i zależności (`uv add`) zmienia tylko integrator na main.
- Worktree: `git worktree add ../COI-<strumień> -b feat/<strumień>`, potem `uv sync` i `ln -s ../../../COI/.work/mat tests/fixtures/materials`; własność plików w plan.md.
- Materiały: `.work/` (poza gitem).
