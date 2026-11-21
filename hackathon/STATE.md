# STATE
Faza: 3 (Rdzeń). S1–S3 DONE (12:10). Następna: runda 1 równoległa (EXTRACT, UI, VALIDATE) + integrator I1/I2.
Start sesji: 2026-11-21 11:35. Deadline ok. 21:30. Plan godzinowy w plan.md (rdzeń 12:25–16:30, 3b do 18:00, prezentacja+wideo 18:00–20:00).
Następny krok: /clear -> 'hackathon-sprint-app, kontynuuj' -> utwórz 3 worktree (COI-extract, COI-ui, COI-validate), briefy subagentów wg plan.md, integrator robi infer+build na main.
Materiały: COI/.work/mat (pliki 4 formularzy × formaty), COI/.work/txt (schema.json, example1.json, reguły, słowniki, dane.txt, standardy.txt).

## Decyzje
- Stack (zmiana 11:55 na prośbę użytkownika): Python 3.14 + uv + FastAPI + pydantic, Docker python:3.14.0-alpine3.22 + tesseract pol (apk), Ollama (qwen3.5:4b). UI: czysty HTML+JS w web/ (bez Node). exceljs/TS porzucone.
- Podgląd oryginału w UI: `?previews=true` -> report.previews (PNG z pypdfium2), zamiast pdf.js.
- Przykład COI ma `validation: {}` – model toleruje, emituje `[]`.
- Wyróżnik: Dowód i zaufanie (confidence+source w `report`, walidator COI + auto-naprawa, lista do przeglądu).
- Odpowiedź API: `{form, report}`; form czysty wg schemy (klucz `repeatingSectionGrid`, nie literówka ze schemy).
- Brak bazy (stateless). Słowniki statyczne JSON; TERYT może być próbką (uczciwie w README).
- 12 zadań rdzenia + stretch w plan.md.
- Streamy runda 1: EXTRACT (Sonnet), UI (Sonnet), VALIDATE (Opus); integrator robi infer+build.
- Uwaga: tylko formularz 1 ma oczekiwany JSON (example1.json) -> golden/eval tylko na nim.

## Środowisko
OK: python3.14 + uv 0.11, tesseract (host, brew), git, gh, ffmpeg, docker (obraz formproof:dev 343 MB działa), ollama (qwen3.5:4b), playwright chromium. Mac M4 24 GB. Brak remote git (utworzyć repo publiczne na GitHub przed zgłoszeniem – wideo musi być w otwartym repo).

## Linki / worktree / problemy
brak / brak / Zasady AI hacknation.pl niesprawdzone. Ollama w Dockerze na Mac bez GPU wolna -> plan B rules-only + OLLAMA_URL na host.
