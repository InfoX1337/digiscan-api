# STATE
Faza: 3 (Rdzeń). S1–S3 + runda 1 (EXTRACT, UI, VALIDATE, I1 infer, I2 build) DONE i scalone (12:40, ~2 h przed planem). Następna: runda 2.
Start sesji: 2026-11-21 11:35. Deadline ok. 21:30. Plan godzinowy w plan.md (rdzeń 12:25–16:30, 3b do 18:00, prezentacja+wideo 18:00–20:00).
Następny krok: /clear -> 'hackathon-sprint-app, kontynuuj' -> runda 2: 3 worktree LLM (R1, Opus), DICT (R2, Sonnet), EVAL+e2e (R3, Sonnet); integrator: jakość infer na formatach nie-PDF (form 1 DOCX/XLSX 5–18 pól vs PDF 30; form 4 tytuł 'Wniosek'), endpoint POST /forms/validate (sprawdź routes), potem F1.
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

## Stan rundy 1 (12:40)
- Pipeline end-to-end działa na 32 plikach (4 formularze × pdf/docx/doc/xlsx/ods/jpg/png), 0.0–1.5 s/plik, bez LLM. PDF form 2: 51 pól, 29/29 reguł.
- Podgląd: skrypt `scratchpad/run_all.py` (filtr nazwy jako arg) – przenieść do scripts/eval w R3.
- UI sprawdzone z prawdziwym backendem (python-playwright przez `uvx --with playwright`, Chrome z ~/Library/Caches/ms-playwright/chromium-1243; MCP playwright nie ma Chrome).
- VALIDATE: 29 reguł COI-R01..R29 + naprawy (uuid5 deterministyczne). R25 dodaje walidatory wg etykiety (wpływa na eval vs expected1).
- Bezpieczeństwo: /demo-config zwraca token 15 min (nie sekret); APP_ENV=production wymaga AUTH_CLIENT_SECRET i DEMO_UI=false; limit zip bomb. Domyślnie APP_ENV=demo (Dockerfile, .env).
- ODS parser: stdlib xml.etree (expat ma ochronę przed entity bomb) – decyzja: zostaje, bez defusedxml.

## Linki / worktree / problemy
brak / runda 2 aktywna (12:35): ../COI-llm feat/llm (R1 Opus), ../COI-dict feat/dict (R2 Sonnet), ../COI-eval feat/eval (R3 Sonnet) / Tesseract na hoście bez `pol` (OCR fallback eng, zła diakrytyka) – doinstalować pol.traineddata lub demo w Dockerze (apk pol). Zasady AI hacknation.pl niesprawdzone. Ollama w Dockerze na Mac bez GPU wolna -> plan B rules-only + OLLAMA_URL na host.
