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

## 2026-10-25 — Krok 2: Szczegółowość = tylko długość tabel (`compact` / `long`)

- Status: DONE.
- Zrobione:
  - `settings.py`: `LEVELS = ("compact", "long")`, domyślnie `compact`; `MINIMAL_ELEMENTS` usunięte, `shown()` =
    wybrane elementy w kolejności `ELEMENTS`; migracja w `from_dict` przez tabelę `OLD_LEVELS`
    (`minimal` → `compact` + ∩ `activities, models, sessions`, puste → te trzy; `normal` → `compact`;
    `detailed` → `long`; nieznany → `compact`); `describe_level` z listą elementów bez tabel z `ELEMENT_INFO`
    (import lokalny — `options` importuje `settings`).
  - `options.py`: `ElementInfo(has_tables, comparable)` i `ELEMENT_INFO`; `long_tables` z zapisanego `long`
    albo `--long`; `--long` na liście opcji raportu (błąd przy osobnych poleceniach).
  - `cli.py`: flaga `--long` (grupa „zakres i widok”); adapter `_apply_plan(ctx, plan)` — `short` tylko dla bazy
    `short` (zapisany poziom nie robi już raportu skróconego), parametr `saved` usunięty; tekst pomocy `--configure`.
  - `configure.py`: podgląd `compact`/`long` (`section_preview` → `_preview` + notka „long tables do not change this
    section” dla elementów bez tabel), usunięte gałęzie `minimal` i nieprawdziwe dopiski „detailed” w `time`,
    `breakdown`, `cache` (te sekcje nie zależą od długości tabel); dopisek „(long nic tu nie zmienia)” przy włączonych
    elementach bez tabel; nagłówek „Długość tabel”; `key_help`/`line_help` zaktualizowane.
  - Testy: `tests/test_options.py` (`--long` z każdą bazą, `ELEMENT_INFO`, `MigrationTest` — każdy stary poziom,
    `--long` przy osobnych poleceniach), `tests/test_end_to_end.py` (stary `minimal` z pliku, `--long` nie zmienia
    sekcji, konfigurator zapisuje `long`, podgląd, reset → `compact`).
  - `docs/references/report-options.md`: oś długości tabel, `--long`, tabela wierszy, migracja, `has_tables`.
- Ustalenie `has_tables` (z `report_text.py` / `report_html.py`):
  - `activities` — tak (tekst 8/16, HTML 8/20); `models` — tak (5/10); `sessions` — tak (tekst 5/10, HTML 5/15);
    `skills` — tak (tekst 5/10 na listę; HTML używane 5/10, nieużywane 10/20).
  - `tips`, `time`, `cache`, `bash`, `map` — nie (brak tabel zależnych od `ctx.rows`; stałe limity, np. powtórne
    odczyty 6, mapa 4 instrukcje); `breakdown` — nie (tekst `TOP_ROWS`/2 na sztywno, HTML `top=12`).
- Weryfikacja: `python3 -m unittest` — 90 testów OK (było 82). Ręcznie (`CLAUDE_TOKEN_REPORT_CONFIG` w scratchpadzie):
  plik `{"level":"detailed","elements":["models","bash"]}` → `Settings(level='long', elements=['models','bash'])`,
  plan `long_tables=True`, raport z sekcjami MODELS i BASH NOISE; `--days 30` z/bez `--long` — te same nagłówki
  sekcji (domyślny zestaw i zestaw z 5 sekcjami), różnice tylko w wierszach czynności i najcięższych rozmów;
  HTML `--skills` z/bez `--long` — te same `<h2>`, więcej wierszy; `--list --long` → kod 2; konfigurator liniowy
  (`-l pl`) pokazuje „długość tabel: long”, zapisuje nowy format.
- Decyzje / odstępstwa:
  - Zapisany stary `minimal` nie renderuje już raportu skróconego (stopka „To skrócony raport…” znika) — po
    migracji to zwykły zestaw elementów `compact`; zgodnie z modelem (presety ≠ konfiguracja).
  - `--short --long`: raport `--short` ma do kroku 3 osobną ścieżkę ze sztywnymi długościami, więc wydłużają się
    w nim tylko najcięższe rozmowy (tekst) / rozmowy (HTML). Opisane w dokumentacji jako ograniczenie do kroku 3.
  - Tekst pomocy `--configure` poprawiony już teraz (mówił o minimal/normal/detailed, które przestały istnieć);
    reszta pomocy i README — krok 8.
  - Opisy poziomów podają faktyczne liczby („rankingi po 5 wierszy (czynności po 8)”), nie samo „5 wierszy”.
