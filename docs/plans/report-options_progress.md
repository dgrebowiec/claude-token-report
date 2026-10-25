# Postęp: spójne opcje raportu

Plan: [report-options.md](report-options.md)

## 2026-10-25 — Krok 1: Jedno miejsce reguł: `resolve()` i błędy przy sprzecznych flagach

- Status: DONE.
- Zrobione:
  - `token_report/options.py` (nowy): `OptionsError`, `ReportPlan` (frozen, `has()`), `resolve(args, saved)`,
    `parse_only` (typ argparse dla `--only`), `report_options` (lista podanych opcji raportu).
  - `cli.py`: flaga `--only LISTA` w grupie sekcji; `resolve` wywoływane zaraz po `parse_args`, przed `--explain`/
    `--configure`/`--reset-config`/`--list`; `OptionsError` → `ap.error`. `_saved_settings` i ręczne ustawianie pól
    zastąpione adapterem `_apply_plan` (plan → `short/full/only_chosen/sections/core`; `only_chosen=True` zawsze,
    sekcje zawsze z planu).
  - `context.py`: pole `plan: Optional[ReportPlan]`.
  - `tests/test_options.py` (nowy, 18 testów): presety, konfiguracja + flaga, `--only` (też nieznana nazwa → kod 2),
    `--no-config`, `--md`, stare `minimal`/`detailed`, każdy twardy błąd, osobne polecenia × każda opcja raportu,
    opcje globalne dozwolone, kody wyjścia 2 z `cli.main`, `--reset-config --bash` nie usuwa pliku.
  - `tests/test_end_to_end.py`: `test_saved_settings_choose_elements` — celowa zmiana: flaga sekcji dopisuje się do
    konfiguracji (wcześniej ją zastępowała).
  - `docs/references/report-options.md` (nowy).
- Weryfikacja: `python3 -m unittest` — 82 testy OK (było 64). Ręcznie (z `CLAUDE_TOKEN_REPORT_CONFIG` w scratchpadzie):
  `--short --full`, `--session --diff`, `--list --bash`, `--explain --days 3`, `--only foo` → kod 2 z komunikatem;
  konfiguracja `{"level":"normal","elements":["activities","cache"]}` + `--bash` → sekcje: czynności, cache
  (długość rozmowy, wygasły cache, długie rozmowy, powtórne odczyty), bash. `--md` bez niczego daje te same nagłówki
  co przed zmianą (porównane ze starym kodem).
- Decyzje / odstępstwa:
  - Dodatkowy twardy błąd: dwa osobne polecenia naraz (np. `--list --explain`) — wcześniej wygrywało pierwsze
    obsłużone; to ta sama kategoria „sprzeczne flagi”.
  - `origin` dla `--only` = `"flag"`, dla presetu `md` = `"preset"`.
  - `--md` z flagą sekcji (np. `--md x --bash`) → baza `default` + bash (jak dotąd); z konfiguracją → `config`.
  - `--full --bash` itp. (flaga zbędna przy `--full`) nie jest błędem.
  - Zapisana konfiguracja jest wczytywana przed obsługą osobnych poleceń (potrzebna do `resolve`); `load` nie rzuca
    wyjątków, więc nie zmienia działania `--reset-config`.
  - Narzędzie Write blokowało utworzenie pliku `.md` przez subagenta — `docs/references/report-options.md`
    zapisany przez powłokę (plik jest wymagany przez plan).
