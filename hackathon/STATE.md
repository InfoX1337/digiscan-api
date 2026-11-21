# STATE
Faza: 2 DONE (plan.md, CLAUDE.md). Następna: Faza 3 (Rdzeń), start od S1.
Start sesji: 2026-11-21 11:35. Deadline ok. 21:30. Plan godzinowy w plan.md (rdzeń 12:25–16:30, 3b do 18:00, prezentacja+wideo 18:00–20:00).
Następny krok: /clear -> 'hackathon-sprint-app, kontynuuj' -> Faza 3, etap sekwencyjny S1–S3 (Opus integrator).
Materiały: COI/.work/mat (pliki 4 formularzy × formaty), COI/.work/txt (schema.json, example1.json, reguły, słowniki, dane.txt, standardy.txt).

## Decyzje
- Stack: Node 24 + TS + pnpm + Fastify, Docker alpine, Ollama (qwen3.5:4b lokalnie) – regulamin zakazuje SaaS/LLM-API. Domyślny stack skilla odrzucony.
- Wyróżnik: Dowód i zaufanie (confidence+source w `report`, walidator COI + auto-naprawa, lista do przeglądu).
- Odpowiedź API: `{form, report}`; form czysty wg schemy (klucz `repeatingSectionGrid`, nie literówka ze schemy).
- Brak bazy (stateless). Słowniki statyczne JSON; TERYT może być próbką (uczciwie w README).
- UI: Vite + vanilla TS. 12 zadań rdzenia + stretch w plan.md.
- Streamy runda 1: EXTRACT (Sonnet), UI (Sonnet), VALIDATE (Opus); integrator robi infer+build.
- Uwaga: tylko formularz 1 ma oczekiwany JSON (example1.json) -> golden/eval tylko na nim.

## Środowisko
OK: node 24, git, gh, ffmpeg, docker, ollama (qwen3.5:4b), python3.14, java 21, playwright chromium. Mac M4 24 GB. Brak remote git (utworzyć repo publiczne na GitHub przed zgłoszeniem – wideo musi być w otwartym repo).

## Linki / worktree / problemy
brak / brak / Zasady AI hacknation.pl niesprawdzone. Ollama w Dockerze na Mac bez GPU wolna -> plan B rules-only + OLLAMA_URL na host.
