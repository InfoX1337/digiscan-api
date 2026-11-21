# STATE
Faza: 1 DONE (wyróżnik A: Dowód i zaufanie, patrz idea.md). Następna: Faza 2 (Plan)
Start sesji: 2026-11-21 11:35 (event startuje 11:00). Deadline: ok. 21:30 (10 h od 11:35).
Następny krok: /clear -> 'hackathon-sprint-app, kontynuuj' -> Faza 2. Materiały rozpakowane: COI/.work/mat, tekst: COI/.work/txt (schema.json, example1.json, reguły, słowniki, dane.txt). Dodać .work do .gitignore.

## Decyzje
- Skill domyślny stack (Next.js/Supabase/Vercel/Claude API) ODRZUCONY: regulamin zakazuje SaaS/API/LLM-only-API. Stack (wybór usera): Node.js + TypeScript + pnpm (Fastify), Docker (node alpine, wersja pinned), lokalne parsery + OCR + lokalny LLM (open weights).
- Faza 1 "pomysł" = wybór strategii wyróżnika (innowacja) w ramach z góry zadanego produktu.

## Środowisko (sprawdzone)
OK: node 24, git, gh, ffmpeg, docker 29.9, ollama (qwen3.5:4b), python3.14, uv, java 21, playwright chromium. Mac M4 24 GB RAM.
Nie dotyczy: vercel, supabase (SaaS zakazane). Brak ANTHROPIC_API_KEY (i dobrze – nie w runtime).
Repo: git init zrobione, brak remote.

## Linki / worktree / problemy
brak / brak / materiały Discord niepobrane (kluczowe: schema JSON + przykłady).
- Wybór usera: TS/pnpm. Ryzyko: regulamin 'preferuje' Java 21/Python 3.14 (nie wymaga). Zaakceptowane; w README uzasadnić. Uwaga licencje npm: bez GPL/AGPL (np. unikać mupdf; pdfjs-dist/mammoth/exceljs/tesseract.js = Apache/BSD/MIT OK).
- AI: hybryda – parsery+reguły dla struktury, lokalny LLM (Ollama, open weights, w docker-compose) do typów pól/słowników/zależności, fallback bez LLM. Brak LLM-API w runtime.
- Zasady AI/kodu hacknation.pl: nie sprawdzone, regulamin COI dopuszcza AI do pisania kodu.
