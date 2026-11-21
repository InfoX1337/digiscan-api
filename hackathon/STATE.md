# STATE
Faza: 3 (Rdzeń) DONE 13:15 (~3 h przed planem). Następna: 3b (dopracowanie, stretch, zamrożenie).
Start sesji: 2026-11-21 11:35. Deadline 21:30. Plan godzinowy w plan.md (3b do 18:00, prezentacja+wideo 18:00–20:00).
Następny krok: /clear -> 'hackathon-sprint-app, kontynuuj' -> 3b: (1) przegląd jakości UI w Dockerze + zrzuty (max 10 poprawek, Sonnet równolegle), (2) stretch wg plan.md (1: walidatory live, 2: edycja->re-validate, 3: strona eval), (3) jakość infer: form 1 ODS/XLSX (13 pól vs PDF 22), form 3 (5–15 pól), TERYT multi-level (expected1: TERYT_DOWODOWY), (4) repo publiczne GitHub, freeze, tag demo-freeze.
Materiały: COI/.work/mat (symlink tests/fixtures/materials), COI/.work/txt (schema, example1, reguły, słowniki, dane.txt).

## Decyzje
- Stack: Python 3.14 + uv + FastAPI + pydantic, Docker python:3.14.0-alpine3.22 + tesseract pol, Ollama qwen3.5:4b. UI czysty HTML+JS w web/.
- Wyróżnik: Dowód i zaufanie (confidence+source w `report`, 29 reguł COI + auto-naprawa, lista do przeglądu).
- LLM (R1): tylko pola <0.8; zgoda podnosi pewność, ale NIE wyciąga pola spod progu przeglądu 0.6; zmiana od LLM = 0.55 (człowiek zatwierdza); typ BRAK = nie pole (0.35); odrzuca tytuły-echo promptu. keep_alive 30m, num_predict 1024. ~9–16 s/plik na hoście (Metal), zimny start ~70 s.
- DICT (R2): Kraje 198, Numery kierunkowe 198, Województwo 16; Powiat/Gmina/Miejscowość próbka (sample:true). MLPZ defaulty tylko w sekcjach wnioskodawcy. Brak TERYT multi-level.
- Odpowiedź API: `{form, report}`; brak bazy (stateless).
- Bezpieczeństwo (automatyczny review): APP_ENV=demo domyślnie w Dockerfile – świadomie dla jury; APP_ENV=production wymusza sekrety i DEMO_UI=false. ODS: stdlib expat (bez zewn. encji) – zostaje.

## Wyniki (llm off)
- Eval form 1 vs expected1: PDF/DOC/DOCX P 0.86 R 0.36 typ 0.92 (było 0.63/0.28); ODS/XLSX P 0.44 R 0.12; obrazy na hoście słabe (brak pol), w Dockerze lepsze.
- Pola: form 2 ~33–40 we wszystkich formatach; form 4 PDF/DOC/DOCX/obrazy 21–24, ODS/XLSX 11; 29/29 reguł wszędzie.
- Testy: 134 pytest (unit + e2e API na 32 plikach); UI e2e real `tests/e2e/ui_test_real.py` 4/4 na kontenerze.

## Komendy
- Eval: `uv run python scripts/eval/run.py`; wyniki do zgłoszenia: `uv run python scripts/export_results.py tests/fixtures/materials wyniki`
- UI e2e: `BASE_URL=http://localhost:8010 CHROME_PATH=~/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google\ Chrome\ for\ Testing.app/Contents/MacOS/Google\ Chrome\ for\ Testing uvx --with playwright --with pytest pytest -o addopts="" tests/e2e/ui_test_real.py`
- Kontener testowy: `docker compose build api && docker run -d --name fp-test --env-file .env -e OLLAMA_URL=http://host.docker.internal:11434 -p 8010:8000 --read-only --tmpfs /tmp coi-api`
- `.env` (lokalny, poza gitem): OLLAMA_URL=http://localhost:11434 dla uruchomienia na hoście; compose nadpisuje na ollama:11434.

## Linki / worktree / problemy
Repo remote: brak (utworzyć publiczne na GitHub przed zgłoszeniem).
3b (13:11): krok 1 przegląd UI DONE (commit 4db5f58: reguły OK zwinięte, intro 3 kroki, placeholder rejestru, odmiana; UI e2e 9/9).
Worktree AKTYWNE (subagenci mogli zostać przerwani limitem – sprawdź `git -C ../COI-<s> log main..` i stan plików):
- ../COI-ui feat/ui: stretch 1 walidatory live (web/js/validators.js) + 2 edycja/zatwierdź → /forms/validate (testid edit-apply, edit-confirm, field-error)
- ../COI-eval feat/eval: strona web/eval.html + js/eval.js + css/eval.css + `run.py --web-out web/demo/eval.json`; po merge dodać link w index.html; regenerować eval.json po merge infer
- ../COI-infer feat/infer: jakość ODS/XLSX, recall form 1, form 3, TERYT
Następnie: scal (rebase, przegląd diffu, pytest+mypy+ruff, UI e2e w Dockerze), docs/architektura.md (opcjonalne – README ma sekcję), repo GitHub, freeze, tag demo-freeze.
Problemy: Tesseract na hoście bez `pol` (brew install tesseract-lang albo demo w Dockerze). Zasady AI hacknation.pl niesprawdzone. Ollama w Dockerze na Mac bez GPU wolna -> OLLAMA_URL na host.
