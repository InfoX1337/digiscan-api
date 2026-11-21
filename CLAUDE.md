# FormProof (COI Cyfryzacja formularzy)

Stan projektu: `hackathon/STATE.md`. Plan: `hackathon/plan.md`. Brief/idea obok.

## Stack
Node 24 + TypeScript strict + pnpm, Fastify, Vite (web/), Docker alpine, Ollama (lokalny LLM). Zero SaaS/LLM-API w runtime (regulamin). Licencje: bez GPL/AGPL.

## Komendy (po S1)
- `pnpm dev` – API z watch; `pnpm web:dev` – UI
- `pnpm test` – vitest; `pnpm typecheck`; `pnpm lint`
- `pnpm license:check` – blokuje copyleft
- `docker compose up --build` – api + ollama
- `pnpm eval` – porównanie z `test/fixtures/expected1.json`

## Zasady
- Pliki formularzy tylko w pamięci/temp na czas żądania.
- Zero hardkodu pod konkretne pliki/tytuły (obrona na nowych plikach).
- `form` w odpowiedzi = czysty JSON wg schemy COI; confidence/source tylko w `report`.
- Kontrakty (`src/types/**`) zmienia tylko integrator na main.
- Worktree: `git worktree add ../COI-<strumień> -b feat/<strumień>`; własność plików w plan.md.
- Materiały: `.work/` (poza gitem).
