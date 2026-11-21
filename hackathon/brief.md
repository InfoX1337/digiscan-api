# Brief – COI „Cyfryzacja formularzy” (HackNation 2026)

Źródła: PDF-y w katalogu głównym (treść zadania + regulamin). Nagroda 25 000 zł, 1 zwycięzca.

## Cel
REST API: plik formularza (PDF, DOC/DOCX, ODS, XLSX, JPG/JPEG, PNG) -> JSON z konfiguracją formularza e-usługi
(struktura zgodna z przykładowymi JSON od COI, strony tematyczne, wymagania projektowe COI). Użytkownik: urzędnik cyfryzujący formularze.

## Twarde wymagania (minimum, 3.2 + 5)
- REST API, upload 1 pliku, odpowiedź JSON.
- Walidacja: rozszerzenie + MIME zgodne z zawartością; nazwa <=250 znaków, bez `; : > < / \ | ' * % $`; max rozmiar konfigurowalny (parametry app).
- Pliki tylko w pamięci/temp na czas żądania.
- Config: max rozmiar, parametry JWT, parametry integracyjne. (JWT auth w API.)
- Docker: oficjalne obrazy bazowe, lekkie (Alpine), wersje jawne, bez `latest`, dedykowany user bez uprawnień, tylko potrzebne porty, sekrety w runtime (env).
- README.md: build obrazu, uruchomienie, konfiguracja, opis REST API.
- Dokumentacja architektury.
- Języki preferowane: Java 21+ lub Python 3.14+.
- Licencje: open source, BEZ copyleft (AGPL/GPL).

## ZAKAZ (zmienia stack skilla!)
- Brak zewnętrznych API, MCP, SaaS. Brak modeli LLM dostępnych WYŁĄCZNIE przez API.
  -> Claude API/OpenAI w runtime NIEDOZWOLONE (do pisania/testowania kodu wolno).
  -> Dozwolone: lokalne open-weights (licencja nie-copyleft) w kontenerze, klasyczne parsery, OCR lokalny, reguły/heurystyki.
- Supabase/Vercel/Neon = SaaS -> poza runtime rozwiązania. Baza ewentualnie lokalna w Dockerze (lub brak bazy).

## Opcjonalne (punktowane, kolejność wag oceny)
I słowniki + dane inicjalne powiązane z polami; II propozycja nowego słownika; III zależności/przepływy między polami/sekcjami/stronami;
IV frontend do uploadu i podglądu JSON; V wizualizacja formularza z JSON (eUsługa); VI walidacje (typ, długość, PESEL, telefon), batch, makiety.

## Kryteria oceny
Kompletność 30% (minimum + opcjonalne I–V) | Intuicyjność 20% | Oryginalność 10% | Jakość kodu 20% | Potencjał wdrożeniowy + koszt 20%.

## Zgłoszenie
Tytuł + opis; prezentacja PDF <=10 slajdów; wynikowe JSON-y; film <=3 min w otwartym repo (link); repo kodu. Opcjonalnie: screeny, demo.
Finaliści: obrona na NOWYCH plikach przekazanych na miejscu -> rozwiązanie musi uogólniać, bez hardkodu pod przykłady.

## Zasoby (Discord, kanał Cyfryzacja formularzy/materiały-dodatkowe) – BRAK lokalnie, user musi pobrać
Przykładowe formularze + oczekiwane JSON + screeny eUsługi; formularze testowe; wymagania projektowe + założenia techniczne konfiguracji; słowniki i dane inicjalne; tokeny (20 pierwszych zespołów).

## Nieznane (do uzupełnienia)
Deadline, godziny pracy, umiejętności zespołu, zasady AI/kodu sprzed startu (regulamin ogólny hacknation.pl), sprzęt (GPU/RAM) pod lokalny model.
