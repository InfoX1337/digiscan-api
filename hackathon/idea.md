# Idea – COI Cyfryzacja formularzy

**Pitch:** Dla urzędnika cyfryzującego formularze, który musi ręcznie sprawdzać każde pole, [nazwa robocza: FormProof] zamienia plik formularza (PDF/DOCX/ODS/XLSX/JPG/PNG) w JSON e-usługi zgodny ze schemą COI dzięki lokalnym parserom, OCR i lokalnemu LLM – i dołącza do każdego pola dowód.

**Opis:** REST API (JWT) przyjmuje plik, wyciąga strukturę (strony, sekcje, pola, typy, walidatory, słowniki, zależności JSONata, flow), zwraca JSON zgodny z `importowanyPlikJsonSchemat`. Opcjonalnie: słowniki (Województwo/Powiat/Gmina/Miejscowość/Kraje/Numery kierunkowe), dane inicjalne (PESEL/PESEL_ADDRESS/MLPZ), propozycja nowego słownika, UI upload + podgląd JSON + wizualizacja formularza. Wszystko offline, Docker Alpine, bez SaaS/LLM-API.

## Core
1. REST API + JWT + walidacja pliku (ext+MIME, nazwa, rozmiar), pliki tylko w pamięci/temp.
2. Ekstrakcja struktury z 6 formatów (parsery + OCR dla obrazów/skanów).
3. Generator JSON zgodny ze schemą + regułami COI (min 2 strony, FINISH tylko INFO_SECTION, pola w sekcjach, obligatoryjność, flow).
4. Słowniki + zależności JSONata + walidatory (PESEL/NIP/REGON/EMAIL/ZIP_CODE...).

## Element innowacyjny: Dowód i zaufanie
"Jako jedyni dajemy JSON z dowodem: każde pole niesie confidence i odniesienie do fragmentu źródła, a wbudowany walidator reguł COI z auto-naprawą kieruje urzędnika tylko do pól niepewnych, dzięki czemu cyfryzacja trwa minuty, nie godziny."
- Pole `confidence` (0-1) + `source` (tekst/bbox/strona) w osobnym raporcie `report` obok `form` (JSON formularza pozostaje czysty wg schemy; nadmiarowe klucze nie lądują w formularzu).
- Walidator zgodności z regułami COI + schemą, auto-naprawa (np. dodanie strony końcowej, flow, REQUIRED), wynik w raporcie.
- Pokaz w UI (≤20 s): klik w pole JSON/wizualizacji podświetla fragment oryginału; lista "do przeglądu" posortowana po niskim confidence.

## Persona
Urzędnik gminy/COI cyfryzujący wzór wniosku do e-usługi; chce szybko i bez błędów dostać gotowy plik konfiguracji.
