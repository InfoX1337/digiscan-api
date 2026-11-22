# STATE
Faza: 3b DONE 17:50 – ZAMROŻONE (tag demo-freeze, commit 396c093). Od teraz tylko poprawki błędów. Następna: hackathon-sprint-presentation.
Start sesji: 2026-11-21 11:35. Deadline 21:30. Plan godzinowy w plan.md (3b do 18:00, prezentacja+wideo 18:00–20:00).
Następny krok: /clear -> 'hackathon-sprint-presentation, kontynuuj' (slajdy, wideo z UI e2e, tekst zgłoszenia). Repo GitHub: użytkownik tworzy sam (git push + git push --tags).
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
Repo remote: github.com/InfoX1337/digiscan-api – PRYWATNE, upublicznić przed zgłoszeniem. Materiały COI (PDF regulaminu, zipy) usunięte z indeksu 2026-11-22, ale są w historii od ad4a168 – decyzja użytkownika o przepisaniu historii.
3b (13:11): krok 1 przegląd UI DONE (commit 4db5f58: reguły OK zwinięte, intro 3 kroki, placeholder rejestru, odmiana; UI e2e 9/9).
Stretch 1+2+3 SCALONE (15:33): walidatory live, pętla urzędnika (edit-apply/edit-confirm → /forms/validate, sekcje też), strona web/eval.html (link w nagłówku, testid eval-link). pytest 135, UI e2e 11/11.
feat/infer SCALONY (eval form 1 PDF/ODS P 0.93 R 0.96). Worktree: brak.
Form 9 (3 wnioski w 1, materiał w .work/mat/9.*): infer/variants.py – spis 'Rodzaje wniosków' (rzymskie I.. albo powtórzone tytuły w DOCX) -> RADIO 'Wybierz rodzaj wniosku' (techName wybierz_rodzaj_wniosku) + SHOW na sekcjach wariantu, wspólne sekcje raz. 8/8 formatów, 29/29 reguł, 0 fałszywych trafień w form 1–4. OCR obrazów >32767 px w pasach. UI e2e: tests/e2e/ui_test_variants.py.
Znane braki form 9: blok 'Wnioskodawca' (Prezydent/Klub) słabo rozpoznany; 4× 'Dane osobowe podopiecznego' zamiast REPEATING_SECTION; ukryte sekcje zostawiają lukę w siatce podglądu.
Freeze 17:50: pytest 149/149, ruff+mypy zielone, UI e2e (real+variants) 7/7 w Dockerze, README z listą funkcji i docs/screenshot.png. Demo: Docker :8000, konto demo/demo-secret (auto-login APP_ENV=demo). testid: upload-input, convert-btn, form-viz, rules-panel, download-json, eval-link. Reset: brak bazy (bezstanowe).
Problemy: Tesseract na hoście bez `pol` (brew install tesseract-lang albo demo w Dockerze). Zasady AI hacknation.pl niesprawdzone. Ollama w Dockerze na Mac bez GPU wolna -> OLLAMA_URL na host.

## Audyt zewnętrzny – poprawki 2026-11-22
Nazwa: zakazane ; : > < / \ | ' * % $, ≤250. Usunięto .tif/.tiff (poza listą zadania). Content-Type musi pasować do rozszerzenia (octet-stream dopuszczony); DOC = OLE ze strumieniem WordDocument. limits.py: limit ciała (Content-Length + strumień), MAX_BATCH_BYTES=50 MB. README: ostrzeżenie o trybie demo, kody błędów, walidacja. docs/ARCHITECTURE.md. compose: .env opcjonalny. Dockerfile: uv z PyPI (bez obrazu ghcr). wyniki/: 40 form + raporty (Docker, llm off), 40/40 schema, 29/29 reguł. Hardkod 17 zł/pełnomocnictwo = standard eUsług COI (standardy.txt), wyzwalany treścią – zostaje.
Testy: pytest 175 + e2e API 45, UI e2e 7/7 na nowym obrazie, ruff/mypy/licencje OK. Kontener formproof-demo (:8000) na starym obrazie – przebudować.
Zostaje (użytkownik): repo publiczne, prezentacja PDF ≤10 slajdów, film ≤3 min w otwartym repo, opis zgłoszenia, sprawdzić regulamin AI hacknation.pl.
