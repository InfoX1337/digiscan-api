# Plan – FormProof (COI Cyfryzacja formularzy)

Deadline 21:30. Freeze kodu ok. 18:00, prezentacja+wideo 18:00–20:00, bufor do 21:30.
Godziny: Faza 3 sekwencja 12:25–13:15, runda 1 13:15–14:45, runda 2 14:45–16:30; 3b 16:30–18:00.

## Scenariusz demo (75 s)
1. UI: upuszczamy `Wniosek o zwrot opłaty skarbowej.pdf` (skan/JPG też możliwe). Pasek postępu: parser, OCR, reguły, LLM.
2. Wynik w <60 s: lewo oryginał, środek wizualizacja eUsługi (strony, sekcje, pola), prawo JSON.
3. Klik w pole = podświetla fragment oryginału (bbox/tekst) + confidence. Lista "Do przeglądu" (niskie confidence) – urzędnik poprawia 2–3 pola.
4. Panel zgodności COI: "11/11 reguł OK, 3 auto-napraw" (np. dodano stronę końcową, flow, REQUIRED). **Kulminacja (innowacja).**
5. Słowniki (Kraje→SELECT dictionaryName), PESEL→MLPZ defaultValue readOnly, zależność SHOW JSONata ("Polska"), propozycja nowego słownika.
6. Pobierz JSON; `curl` API z JWT (REST, batch).

## Stack (zmiana 11:55: Python zamiast TS – regulamin preferuje Python 3.14+)
Python 3.14 + uv, FastAPI + uvicorn, pydantic v2 (kontrakt = modele), PyJWT, jsonschema, jsonata-python. Docker `python:3.14.0-alpine3.22`, user `app`, read-only FS. Ollama (osobny kontener, pinned tag) do wzbogacenia. Baza: brak (stateless, pliki w pamięci).
Ekstrakcja: pdfplumber (tekst+pozycje+prostokąty/checkboxy), pypdfium2 (render stron -> OCR/podgląd), pytesseract + tesseract-ocr pol (apk), Pillow, python-docx, openpyxl, ODS = zip+xml (stdlib), DOC = olefile + własny odczyt tekstu z WordDocument (bez układu).
UI: `web/` czysty HTML + ES modules JS (bez Node/build), serwowany przez FastAPI StaticFiles. Podgląd oryginału: `?previews=true` -> `report.previews[]` (PNG + width/height w jednostkach bbox) – bez pdf.js.
Licencje: tylko MIT/BSD/Apache/MPL(certifi). Zakaz GPL/AGPL (PyMuPDF, antiword, poppler, libreoffice). `uv run python scripts/license_check.py`.
Jakość: `uv run pytest`, `uv run ruff check`, `uv run mypy src`.

## Architektura (pipeline, każdy krok czysta funkcja, testowalny)
`ingest` (walidacja) → `extract` (plik→SourceDoc) → `infer` (SourceDoc→DraftForm z confidence+source) → `llm` (opcjonalne wzbogacenie, timeout, fallback) → `dict` (słowniki, dane inicjalne, propozycja) → `build` (DraftForm→FormDefinition) → `validate` (reguły COI + schema + auto-naprawa → Report) → odpowiedź `{form, report}`.
`form` = czysty JSON zgodny ze schemą COI (bez dodatkowych kluczy, `FormDefinition.dump()`). `report` osobno: `fields[techName|id] → {confidence, source:{page,bbox?,text}}`, `review[]`, `rules[]`, `repairs[]`, `proposedDictionaries[]`, `timings`, `llm:{used,model}`.
Uogólnianie: zero hardkodu pod pliki/tytuły; obrona na nowych plikach.

## Model danych
Brak bazy. Stan = request. Cache wyników LLM in-memory po SHA-256 tekstu (demo, limit rozmiaru). Słowniki = statyczne JSON w `src/dict/data/` (Kraje, Numery kierunkowe, Województwo; Powiat/Gmina/Miejscowość – próbka lub eksport TERYT z licencją otwartą, jeśli zdążymy; inaczej oznaczone w README jako ograniczone).

## Kontrakt API (Fastify, prefix `/api/v1`, JWT Bearer)
- `POST /auth/token` {clientId, clientSecret} (z env) → {accessToken, expiresIn}. Parametry JWT: `JWT_SECRET`, `JWT_EXPIRES_IN`, `JWT_ISSUER`, `JWT_AUDIENCE`.
- `POST /forms/convert` multipart `file` (+ query `llm=true|false`, `previews=true|false`) → 200 `{form, report}`; 400 walidacja pliku (kod błędu: `FILE_TOO_LARGE`, `BAD_EXTENSION`, `MIME_MISMATCH`, `BAD_FILENAME`, `EMPTY`), 401, 415, 422 (nic nie wyekstrahowano), 504 (timeout).
- `POST /forms/convert/batch` multipart wiele `file` → `{results:[{filename, ok, form?, report?, error?}]}` (limit liczby plików z configu).
- `POST /forms/validate` body `FormDefinition` → `Report.rules/repairs` (walidator jako osobna usługa; dla UI po ręcznych poprawkach).
- `GET /dictionaries`, `GET /dictionaries/:name` (JWT) → pozycje.
- `GET /health` (bez JWT), `GET /docs` (OpenAPI).
Config env (`src/formproof/config.py`, `.env.example`): `MAX_FILE_BYTES`, `MAX_BATCH_FILES`, `MAX_OCR_PAGES`, `REQUEST_TIMEOUT_S`, `JWT_SECRET/EXPIRES_S/ISSUER/AUDIENCE`, `AUTH_CLIENT_ID/SECRET`, `OLLAMA_URL`, `LLM_MODEL`, `LLM_ENABLED`, `LLM_TIMEOUT_S`, `TESSERACT_CMD`, `DEMO_UI`, `PORT`.
Typy (pydantic): `src/formproof/types/form.py` (FormDefinition; emitujemy `repeatingSectionGrid`, wejście toleruje `{}` zamiast `[]`), `source.py` (SourceDoc), `draft.py` (DraftForm), `report.py` (Report, camelCase), `stages.py` (sygnatury kroków: ExtractFn, InferFn, EnrichFn, DictFn, BuildFn, ValidateFn). Query `/forms/convert`: `llm`, `previews`.

## Auth
JWT (HS256) na wszystkich `/api/v1/*` poza `/auth/token`, `/health`. Brak kont użytkowników; klient z env. UI loguje się automatycznie danymi z env (tryb demo) lub formularzem tokenu. Konto demo w README.

## Prawdziwe vs uproszczone
Prawdziwe: ekstrakcja z 6 formatów (z OCR), generator, walidator+auto-naprawa+confidence, słowniki, dane inicjalne, zależności JSONata (walidowane parserem jsonata), UI z wizualizacją, batch.
Uproszczone: Powiat/Gmina/Miejscowość próbka (jeśli brak otwartego TERYT), brak persystencji, DOC (binarny) tylko tekst bez układu.
Plan B: LLM pada/wolny → tryb rules-only (pełny, poprawny JSON, niższe confidence). Ollama w Dockerze na Mac bez GPU wolna: timeout 45 s, cache, demo na hoście z Metal (`OLLAMA_URL`).

## Mapa własności plików (rozłączna)
- Integrator (main): `pyproject.toml`, `uv.lock`, `src/formproof/types/**`, `src/formproof/config.py`, `src/formproof/app.py`, `src/formproof/routes/**`, `src/formproof/auth/**`, `src/formproof/ingest/**`, `src/formproof/infer/**`, `src/formproof/build/**`, `src/formproof/pipeline.py`, Docker*, `README.md`, `docs/**`, `tests/test_api.py`, `tests/test_contract.py`, `tests/conftest.py`.
- Strumień EXTRACT: `src/formproof/extract/**`, `tests/extract/**` (materiały: `tests/fixtures/materials` = symlink do `.work/mat`, poza gitem).
- Strumień UI: `web/**`, `tests/e2e/ui_*`.
- Strumień VALIDATE: `src/formproof/validate/**`, `tests/validate/**`.
- Runda 2: LLM (`src/formproof/llm/**`), DICT (`src/formproof/dictionaries/**`), EVAL (`scripts/eval/**`, `tests/e2e/api_*`).
Kontrakty: `SourceDoc` (EXTRACT out), `FormDefinition`+`Report` (VALIDATE in/out, UI in). Nowa zależność = prośba do integratora (`uv add` na main).
Fixtures na main: `tests/fixtures/sample-source.json` (form 2 PDF), `sample-source1.json` (form 1 PDF), `expected1.json` (= example1.json), `sample-response.json` (dla UI; syntetyczny report).

## Zadania rdzenia (≤30 min każde) – 12
Etap 1 sekwencyjny (integrator, Opus):
- [x] S1 Szkielet (Python: uv+pydantic+pytest+ruff+mypy), struktura katalogów, config.py, typy kontraktu (form/source/draft/report), fixtures, `.gitignore`, CLAUDE.md
- [x] S2 Auth JWT + `/auth/token` + `/health` + ingest (ext + magic-bytes MIME, nazwa, rozmiar, empty) + `/forms/convert` z pipeline-stubem + testy
- [x] S3 license_check.py + Dockerfile (alpine pinned, user app) + compose (api+ollama) – smoke build
Etap 2 równoległy – runda 1 (max 3 worktree):
- [x] E1 (Sonnet) EXTRACT PDF (pdfplumber, pozycje, rect-checkboxy) + obraz/skan OCR (pytesseract pol, bbox) + wykrywanie PDF bez warstwy tekstu → OCR
- [x] E2 (Sonnet) EXTRACT DOCX/ODS/XLSX/DOC → SourceDoc (tabele, checkboxy ☐/☑, komórki)
- [x] U1 (Sonnet) UI: upload (drag&drop), JWT demo, widok JSON, lista "do przeglądu", panel reguł COI
- [x] U2 (Sonnet) UI: wizualizacja eUsługi z JSON (grid x/y/rows/cols, typy komponentów, states SHOW) + podświetlanie źródła na `report.previews` (PNG)
- [x] V1 (Opus) VALIDATE: reguły COI (≥12 reguł z dokumentu) + jsonschema + auto-naprawa + Report.rules/repairs; `POST /forms/validate` handler
- Integrator w tym czasie: [x] I1 infer (SourceDoc→DraftForm: sekcje, pola, typ z etykiety/kształtu, opcje z checkboxów, REQUIRED, confidence) [x] I2 build (UUID, techName slug ASCII unikalny, grid layout, tabs MAIN/FINISH, flow links, states JSONata z zależności, defaultValue EXTERNAL_SYSTEM z mapy atrybutów)
  (UI = 1 worktree łącznie U1+U2; EXTRACT = 1 worktree E1+E2 sekwencyjnie jeśli trzeba; VALIDATE = 1 worktree)
Etap 3 – runda 2 + końcowy:
- [ ] R1 (Opus) LLM: Ollama client, JSON-constrained prompty (typ pola, walidator, słownik, zależności, nazwy sekcji), timeout, cache, fallback, confidence fusion
- [ ] R2 (Sonnet) DICT: dane słowników + dopasowanie pola→słownik (opcja I), dane inicjalne PESEL/PESEL_ADDRESS/MLPZ (readOnly+EXTERNAL_SYSTEM), propozycja nowego słownika (II) do `report.proposedDictionaries`
- [ ] R3 (Sonnet) EVAL+e2e: skrypt porównania z `expected1.json` (P/R pól i typów), e2e API na 4 formularzach × formatach (pytest + Playwright UI), batch endpoint
- [ ] F1 Końcowy: spięcie UI↔API na deployu (docker compose), stany ładowania/błędów, README + docs/architektura.md, `data-testid`

## Stretch (wg wag oceny)
1. Walidatory w podglądzie (PESEL/NIP/REGON checksum live w wizualizacji) – VI
2. Edycja pola w UI → re-validate → `report` odświeżony (zamknięta pętla urzędnika)
3. Raport eval jako strona (precision/recall na 4 formularzach) – wiarygodność
4. Tryb ciemny + a11y + przykładowe pliki "wypróbuj"
5. Eksport zip (JSON + report) dla batch

## Limity ryzyka
- LLM timeout 45 s (`LLM_TIMEOUT_MS`), max wejście tokenów obcinane, cache SHA-256, kolejka 1 równoległe wywołanie LLM.
- OCR wolny: limit stron (domyślnie 5), skala 2x.
- Brak danych TERYT lokalnie: oznacz uczciwie.

## data-testid
`upload-input`, `upload-dropzone`, `convert-btn`, `progress`, `json-view`, `form-viz`, `field-<techName>`, `review-list`, `review-item`, `rules-panel`, `rule-<id>`, `repairs-list`, `source-highlight`, `download-json`, `login-token`.
