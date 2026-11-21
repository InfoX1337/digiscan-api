# FormProof – formularz urzędowy → JSON e-usługi COI, z dowodem dla każdego pola

FormProof zamienia plik formularza (PDF, skan JPG/PNG/TIFF, DOCX, DOC, XLSX, ODS) w konfigurację formularza
e-usługi zgodną ze schemą COI (`importowanyPlikJsonSchemat`). Działa w całości lokalnie: parsery, OCR (Tesseract)
i opcjonalnie lokalny model open-weights (Ollama). Żadnych usług SaaS ani zewnętrznych API LLM.

**Element innowacyjny – Dowód i zaufanie.** Jako jedyni dajemy JSON z dowodem: każde pole ma `confidence`
i odniesienie do fragmentu oryginału (strona, bbox, tekst). Wbudowany walidator 29 reguł technicznych COI
z auto-naprawą kieruje urzędnika tylko do pól niepewnych, więc cyfryzacja trwa minuty, nie godziny.

- `form` – czysty JSON wg schemy COI (bez dodatkowych kluczy), gotowy do importu.
- `report` – osobno: pewność i źródło każdego pola, lista „Do przeglądu”, wynik reguł COI, wykonane naprawy,
  propozycje nowych słowników, czasy etapów, informacja o użyciu LLM.

## Szybki start

```bash
cp .env.example .env              # w produkcji: własne JWT_SECRET, AUTH_CLIENT_SECRET, APP_ENV=production
docker compose up --build         # api :8000 + ollama
docker compose exec ollama ollama pull qwen3.5:4b   # jednorazowo (opcjonalne; bez modelu działa tryb reguł)
```

UI: http://localhost:8000/ (tryb demo loguje się sam). OpenAPI: http://localhost:8000/docs.

Na Macu Ollama w Dockerze nie ma GPU – szybciej z Ollamą na hoście: `OLLAMA_URL=http://host.docker.internal:11434`.

Lokalnie bez Dockera (Python 3.14 + [uv](https://docs.astral.sh/uv/), Tesseract z językiem `pol`):

```bash
uv sync
uv run python -m formproof        # :8000
```

## Konto demo

| | |
|---|---|
| clientId | `demo` |
| clientSecret | `demo-secret` |

Dane z `.env` (`AUTH_CLIENT_ID`, `AUTH_CLIENT_SECRET`). `APP_ENV=production` wymaga własnych sekretów i wyłącza auto-logowanie UI.

## REST API (prefiks `/api/v1`, JWT Bearer HS256)

| Metoda | Ścieżka | Opis |
|---|---|---|
| POST | `/auth/token` | `{clientId, clientSecret}` → `{accessToken, expiresIn}` |
| POST | `/forms/convert?llm=true&previews=false` | multipart `file` → `{form, report}` |
| POST | `/forms/convert/batch` | multipart wiele `file` → `{results: [{filename, ok, form?, report?, error?}]}` |
| POST | `/forms/validate?repair=true` | body: JSON formularza → `{form, rules, repairs}` (form po naprawie) |
| GET | `/dictionaries`, `/dictionaries/{name}` | słowniki (Kraje, Numery kierunkowe, Województwo, …) |
| GET | `/health` | bez JWT |

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/token -H 'content-type: application/json' \
  -d '{"clientId":"demo","clientSecret":"demo-secret"}' | jq -r .accessToken)
curl -s localhost:8000/api/v1/forms/convert -H "Authorization: Bearer $TOKEN" \
  -F 'file=@Wniosek o zwrot opłaty skarbowej.pdf' | jq '.report.rules | length'
```

Błędy: `400` (`BAD_FILENAME`, `EMPTY`, `FILE_TOO_LARGE`, `MIME_MISMATCH`), `401`, `415` (`BAD_EXTENSION`),
`422` (`NOTHING_EXTRACTED`), `504` (przekroczony czas). Plik sprawdzany po rozszerzeniu i sygnaturze bajtów
(magic bytes), trzymany tylko w pamięci na czas żądania.

## Konfiguracja (`.env`)

`APP_ENV`, `PORT`, `JWT_SECRET`, `JWT_EXPIRES_S`, `JWT_ISSUER`, `JWT_AUDIENCE`, `AUTH_CLIENT_ID`, `AUTH_CLIENT_SECRET`,
`MAX_FILE_BYTES`, `MAX_BATCH_FILES`, `MAX_OCR_PAGES`, `REQUEST_TIMEOUT_S`, `LLM_ENABLED`, `OLLAMA_URL`, `LLM_MODEL`,
`LLM_TIMEOUT_S`, `TESSERACT_CMD`, `DEMO_UI`. Opis i wartości domyślne: `.env.example`.

## Architektura

```
plik → ingest (rozszerzenie, MIME, nazwa, rozmiar)
     → extract (pdfplumber / OCR Tesseract / python-docx / openpyxl / ODS xml / DOC olefile) → SourceDoc (bloki + bbox)
     → infer (układ + katalog pojęć: sekcje, pola, typy, walidatory, REQUIRED, zależności) → DraftForm z confidence
     → llm (opcjonalnie: lokalny model doprecyzowuje niepewne pola; timeout, cache, fallback do reguł)
     → dictionaries (słowniki, dane inicjalne MLPZ/EXTERNAL_SYSTEM, propozycje nowych słowników)
     → build (UUID, techName, siatka, strony MAIN/FINISH, flow, stany SHOW w JSONata)
     → validate (schema + 29 reguł COI + auto-naprawa) → {form, report}
```

Każdy krok to czysta funkcja z kontraktem w `src/formproof/types/`. Brak bazy danych – usługa bezstanowa.
Zero reguł pisanych pod konkretne pliki: heurystyki działają na układzie i treści etykiet.

## Jakość i licencje

```bash
uv run pytest                     # testy jednostkowe + e2e API na materiałach (jeśli dostępne)
uv run python scripts/eval/run.py # metryki vs wzorcowy JSON formularza 1
uv run python scripts/license_check.py   # blokuje zależności copyleft (GPL/AGPL)
```

Obraz: `python:3.14.0-alpine3.22`, użytkownik `app`, system plików tylko do odczytu. Zależności tylko na licencjach
MIT/BSD/Apache/MPL.

## Ograniczenia (uczciwie)

- Słowniki Powiat/Gmina/Miejscowość to próbka (pełny TERYT nie jest dołączony); Kraje, Numery kierunkowe, Województwo – pełne.
- DOC (binarny Word) – tylko tekst, bez układu.
- Jakość OCR zależy od skanu; pola z OCR mają niższe `confidence` i trafiają do przeglądu.
- Wynik to propozycja do przeglądu przez urzędnika, nie ostateczna decyzja.

Licencja: MIT.
