# Wyniki konwersji

Wynikowe JSON-y dla formularzy z materiałów zadania (formularze 1–4 i 9, wszystkie formaty).

- `<plik>.<rozszerzenie>.json` – czysty `form` wg schemy COI (gotowy do importu),
- `<plik>.<rozszerzenie>.report.json` – raport: pewność i źródło pól, lista do przeglądu, wynik 29 reguł COI, czasy.

Wygenerowane w kontenerze (Tesseract z językiem `pol`), tryb reguł bez LLM – deterministycznie:

```bash
docker compose build api
docker run --rm --read-only --tmpfs /tmp -e LLM_ENABLED=false -e PYTHONPATH=/app/src \
  -v "$PWD/<materiały>:/mat:ro" -v "$PWD/scripts:/scripts:ro" -v "$PWD/wyniki:/out" --user "$(id -u)" \
  coi-api python /scripts/export_results.py /mat /out
```

Stan: 40/40 formularzy zgodnych ze schemą COI, 29/29 reguł technicznych w każdym.
