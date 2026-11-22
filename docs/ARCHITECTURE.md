# FormProof – architektura

## Kontekst

```
 urzędnik (przeglądarka)            system integrujący (np. kreator eUsług)
        │  UI web/ (HTML+JS)                 │  REST (JWT opcjonalnie)
        └──────────────┬─────────────────────┘
                       ▼
        ┌─────────────────────────────┐        ┌──────────────────────────┐
        │ kontener api (FastAPI)      │ HTTP   │ kontener ollama          │
        │ python:3.14.10-alpine3.24   │───────▶│ lokalny model open-weights│
        │ user app, read-only, tmpfs  │ (opcj.)│ (qwen3.5:4b, Apache-2.0) │
        │ Tesseract OCR (pol)         │        └──────────────────────────┘
        └─────────────────────────────┘
```

Bez bazy danych, kolejek i usług zewnętrznych. Wszystko działa w sieci lokalnej; żadnych SaaS ani API LLM
dostępnych tylko w chmurze. Usługa jest bezstanowa, więc skaluje się poziomo przez dodanie replik.

## Przepływ żądania `POST /api/v1/forms/convert`

| # | Warstwa | Moduł | Co robi | Wyjście |
|---|---|---|---|---|
| 0 | limit ciała | `limits.py` | 413 przy `Content-Length` > limit albo po przekroczeniu w trakcie odbioru | – |
| 1 | auth | `auth/` | opcjonalna (`AUTH_ENABLED`) weryfikacja JWT HS256 (`iss`, `aud`, `exp`) | claims |
| 2 | ingest | `ingest/` | nazwa (≤250, zakazane `; : > < / \ \| ' * % $`), rozszerzenie, `Content-Type`, magic bytes + struktura ZIP/OLE, rozmiar, ochrona przed zip bomb | `IngestedFile` (bajty w RAM) |
| 3 | extract | `extract/` | pdfplumber (PDF z tekstem), pypdfium2 + Tesseract (skany, obrazy), python-docx, olefile (DOC), openpyxl (XLSX), expat (ODS) | `SourceDoc`: bloki tekstu z bbox i stroną |
| 4 | infer | `infer/` | układ linii + katalog pojęć: sekcje, pola, typy, walidatory, REQUIRED, warianty wniosku, zależności SHOW | `DraftForm` z `confidence` i `evidence` |
| 5 | llm (opcj.) | `llm/` | tylko pola z pewnością < 0.8; lokalny model proponuje poprawki, fuzja z regułami (zmiana od LLM = 0.55, do przeglądu); timeout, cache, fallback | `DraftForm` |
| 6 | dictionaries | `dictionaries/` | dopasowanie słowników (Kraje, Numery kierunkowe, Województwo, TERYT – próbka), dane inicjalne, propozycje nowych słowników | `DraftForm` |
| 7 | build | `build/` | UUID, `techName`, siatka, strony MAIN/FINISH, flow, stany SHOW w JSONata | `FormDefinition` |
| 8 | validate | `validate/` | JSON Schema COI + 29 reguł technicznych + auto-naprawa | `form` + `rules` + `repairs` |
| 9 | report | `pipeline.py` | pewność i źródło pól, lista „Do przeglądu” (< 0.6), czasy etapów | `{form, report}` |

Każdy etap to czysta funkcja z kontraktem w `src/formproof/types/` (`source.py`, `draft.py`, `form.py`,
`report.py`, `stages.py`), więc etapy testuje się osobno i można je wymieniać (np. inny OCR albo model).

## Rozdział `form` / `report`

- `form` – wyłącznie struktura wg schemy COI (`FormDefinition.dump()`), bez dodatkowych kluczy, gotowa do importu.
- `report` – metadane dla człowieka: `confidence`, źródło (strona, bbox, tekst), wynik reguł, naprawy, propozycje
  słowników, użycie LLM. Dzięki temu import do kreatora nie wymaga czyszczenia JSON.

## Uogólnianie (nowe pliki)

Heurystyki działają na układzie i treści etykiet, nie na nazwach plików ani tytułach konkretnych formularzy.
Bloki standardowe (np. „Podmiot wniosku”, pełnomocnictwo, opłata skarbowa 17 zł) pochodzą z dokumentu standardów
eUsług COI i są dodawane tylko wtedy, gdy treść dokumentu je uzasadnia (np. sekcja wnioskodawcy z polem
„nazwa” obok imienia i nazwiska).

## Bezpieczeństwo

- Plik tylko w pamięci procesu (i `tmpfs` kontenera dla buforów multipart) na czas żądania; nic nie jest zapisywane.
- Kontener: oficjalny obraz Alpine z jawną wersją, użytkownik `app` bez uprawnień, system plików tylko do odczytu,
  jeden port (8000), sekrety wyłącznie z env w runtime.
- ODS parsowany przez stdlib expat (bez zewnętrznych encji XML), ZIP z limitem wpisów i rozmiaru po rozpakowaniu,
  OCR z limitem stron (`MAX_OCR_PAGES`), całe przetwarzanie z limitem czasu (`REQUEST_TIMEOUT_S`).
- Domyślnie (demo) API jest otwarte, `AUTH_ENABLED=false` – **nie do wdrożenia publicznego**.
  `AUTH_ENABLED=true` włącza JWT; z `APP_ENV=production` wymaga własnych `JWT_SECRET` i `AUTH_CLIENT_SECRET` oraz `DEMO_UI=false`, inaczej start się nie uda.

## Konfiguracja

Wyłącznie zmienne środowiskowe (`config.py`, opis w `.env.example`): limity (`MAX_FILE_BYTES`, `MAX_BATCH_FILES`,
`MAX_BATCH_BYTES`, `MAX_OCR_PAGES`, `REQUEST_TIMEOUT_S`), JWT (`JWT_SECRET`, `JWT_EXPIRES_S`, `JWT_ISSUER`,
`JWT_AUDIENCE`), klient API, integracja z LLM (`LLM_ENABLED`, `OLLAMA_URL`, `LLM_MODEL`, `LLM_TIMEOUT_S`), OCR.

## Koszt i wdrożenie

- Tryb reguł (bez LLM, zmierzone na 40 plikach z `wyniki/`): plik tekstowy zwykle < 1 s, skan 1,5–12 s (OCR);
  CPU, bez GPU, bez opłat licencyjnych i usług chmurowych.
- Z LLM: model 4B na CPU/GPU lokalnie; LLM jest opcjonalny i wyłączalny (`LLM_ENABLED=false`, `?llm=false`).
- Licencje zależności: MIT/BSD/Apache/MPL, sprawdzane skryptem `scripts/license_check.py` (blokuje GPL/AGPL).

## Testy

`uv run pytest` – testy jednostkowe etapów, kontrakt schemy COI, e2e API na materiałach (jeśli dostępne lokalnie);
`tests/e2e/ui_test_real.py` – Playwright na kontenerze; `scripts/eval/run.py` – metryki względem wzorcowego JSON.
