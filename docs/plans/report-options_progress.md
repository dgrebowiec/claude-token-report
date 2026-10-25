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

## 2026-10-25 — Krok 3: Raport skrócony jako zestaw sekcji, a nie osobny tryb renderowania

- Status: DONE.
- Zrobione:
  - `context.py`: `ReportContext` bez pól `short`, `full`, `only_chosen`, `sections`, `core`; pole
    `plan: ReportPlan` (domyślnie plan raportu domyślnego — `_default_plan`, import lokalny, bo `options`
    importuje `context`); `wants`/`shows` zastąpione jedną metodą `has(element)` = `plan.has`; `rows` z
    `plan.long_tables`.
  - `cli.py`: adapter `_apply_plan` usunięty, plan podawany do `ReportContext(..., plan=plan)`; zbędne importy
    (`SECTIONS`, `ReportPlan`) usunięte.
  - `report_text.text_report`, `report_html.html_report`: gałęzie `if ctx.short:` usunięte, jedna ścieżka;
    długości z planu (tekst: czynności `ctx.rows + 3/6` = 8/16; HTML: 8/20, rozmowy `rows + 5` przy long).
    Stopka „To skrócony raport…” usunięta; podpowiedź „Więcej szczegółów” (`_FLAGS`/`_more`) liczona z planu,
    teraz także w `--short`. HTML: `_comparison`/`_daily` zawsze, gdy są dane. Import `TOP_ROWS` w HTML usunięty.
  - `tips.py`: `ctx.has(...)`; zachowanie dla `ctx=None` bez zmian.
  - Testy: `test_waste` — `ReportContext(..., plan=ReportPlan(ELEMENTS, long_tables=True))` zamiast `full=True`,
    nowy przypadek planu `--short --bash` (sekcja bash w tekście i HTML); `test_end_to_end` — `test_short`
    (brak starej stopki, jest „More detail”), nowe `test_short_is_a_set_of_elements` i
    `test_html_short_keeps_comparison_and_daily`, `--session --short` ma fazy sesji.
  - `docs/references/report-options.md`: presety jako zestawy elementów, „Jedna ścieżka renderowania”,
    bloki pojedynczej sesji, `tips`; usunięte ograniczenie `--short --long`.
- Weryfikacja:
  - `python3 -m unittest` — 92 testy OK (było 90).
  - `grep -n "ctx.short\|ctx.full\|only_chosen" token_report/` — pusto.
  - HTML (scratchpad, `CLAUDE_TOKEN_REPORT_CONFIG` na nieistniejący plik w scratchpadzie, okres 15–21.10):
    `--short --diff` → `<h2>Comparison` z „… vs 2026-10-08..2026-10-14 (7 days)”, potem czynności, modele,
    rozmowy; `--short --daily` → `<h2>Day by day`; żaden plik nie zawiera „short report”.
  - Porównanie przed/po (skrypt zrzucający 22 warianty: tekst, HTML, MD; zrzut przed zmianą odtwarzalny 1:1):
    bez zmian — domyślny tekst, HTML, `--diff`, `--daily`, `--diff --daily --html`, `--long`, `--cache --skills`,
    `--session` (tekst i HTML). `--full` i domyślny MD różnią się tylko liczbą linii plików `report_text.py`,
    `report_html.py`, `cli.py` w mapie projektu (pliki zmieniły się w tym kroku) — nie zmiana raportu.
- Różnice celowe (tylko presety `--short` i `--session --short`):
  - `--short` (tekst/MD): zamiast „To skrócony raport…” — „More detail: …” i linia o `--explain`.
  - `--short --long`: czynności 16 wierszy i modele do 10 (wcześniej sztywno 8 / 5).
  - `--short --bash`: sekcja BASH NOISE jest w raporcie (wcześniej ignorowana).
  - `--short --html`: dochodzi blok „Co znaczą tokeny surowe i ważone” (`_explanation`) i „Więcej szczegółów”;
    czynności 8 zamiast 10, modele 5 zamiast do 12 (jak w raporcie domyślnym); z `--diff` / `--daily`
    są porównanie / „dzień po dniu”.
  - `--session --short`: tekst — dochodzi „WHERE THE TOKENS GO” przed fazami sesji (czynności są w zestawie
    `--short`); HTML — dochodzi „Where the tokens go” i objaśnienie. Fazy sesji (`_session_phases`) i szczegóły
    sesji zostają.
- Decyzje / odstępstwa:
  - Zamiast dwóch metod `wants`/`shows` jedna `ReportContext.has` (obie i tak znaczyłyby `plan.has`).
  - Brak danych o szumie Basha w syntetycznych transkryptach e2e — obecność sekcji bash przy `--short --bash`
    sprawdzana w `test_waste` (dane z szumem) i w e2e przez brak `--bash` w „More detail”.

## 2026-10-25 — Krok 4: Porównanie (`--diff`) zgodne z sekcjami raportu

- Status: DONE.
- Zrobione:
  - `options.py`: `ELEMENT_INFO[*].comparable` — `True` dla `activities`, `models`, `time`, `breakdown`,
    `cache`, `bash`; `False` dla `sessions`, `tips`, `skills`, `map`. Nowe `uncompared(elements)` i
    `no_comparison_note(elements)` („Bez porównania: …” / „Not compared: …”, `""` gdy nic). `resolve` przy
    `--diff` wpisuje tę linię do `plan.notes`.
  - `report_text.text_diff`: liczby ogólne zawsze (wywołania, surowe, ważone, średnio na wywołanie,
    trafienia w cache); rodzaje tokenów tylko z `time`; tabele czynności / modeli / projektów tylko z
    `activities` / `models` / `breakdown`; „Wnioski” tylko z `cache` (długie rozmowy, wygasły cache) i/lub
    `bash` (nowy wiersz: udział szumu Basha); na końcu linia „Bez porównania”. Wnioski wydzielone do
    `diff_takeaways(cur, prev, ctx)` — używa ich też HTML.
  - `report_html._comparison` przepisane na te same części co tekst: tabela ogólna (+ rodzaje tokenów,
    + trafienia w cache w pp), tabele `<h3>` czynności / modele / projekty (do 12 wierszy, ta sama kolejność
    co w tekście: suma z obu okresów), „Wnioski” (`<ul>` w karcie), `<p class=sub>` z „Bez porównania”.
    CSS: `.cmp h3` jak `.sd h3`. MD używa `text_diff`, więc mówi to samo co terminal.
  - `cli.main`: przy `--diff` i `bash` w planie poprzedni okres dostaje `find_waste(prev_calls, sessions)`
    (`aggregate(..., hotspots=False)` nie liczy `waste`); bez `bash` — bez dodatkowego liczenia.
  - Testy: `test_options` — lista porównywalnych, `test_diff_notes_the_elements_without_comparison`;
    `test_end_to_end` — `test_diff_follows_the_elements_of_the_report` (konfiguracja bez `models` → brak
    tabeli modeli; z `--breakdown --cache --time` → projekty, wnioski, rodzaje tokenów; tekst, HTML i MD),
    `test_diff_names_the_elements_without_comparison` (`--skills --diff` → „Not compared: sessions, tips,
    skills”; `--only activities,models` → brak linii); `test_waste.test_diff_compares_the_bash_noise`.
  - `docs/references/report-options.md`: sekcja „Porównanie (`--diff`) a elementy raportu” z tabelą
    element → porównanie, przykłady, opis `notes`.
- Decyzja `bash` / `skills` (sprawdzone w `stats.py` / `waste.py`):
  - `bash` — porównywalny: jest prosta liczba `waste.noisy_weighted` (ważone tokeny długich wyników Basha
    bez ograniczenia, z ponownymi odczytami); porównywany jej udział w zużyciu, jak dwa dotychczasowe wnioski.
    Koszt: `find_waste` dla poprzedniego okresu, tylko gdy `bash` jest w planie. Bez zmian w obliczeniach.
  - `skills` — bez porównania: liczby sekcji (skille na liście, tokeny opisów, nieużywane) opisują
    konfigurację skilli, nie zużycie w okresie, a „używany w N rozmowach” rośnie z liczbą rozmów — zestawienie
    dwóch okresów nic by nie mówiło.
  - `sessions`, `tips` (nie wymienione w planie) — bez porównania: ranking rozmów z dwóch okresów to różne
    rozmowy, podpowiedzi to nie liczby.
- Weryfikacja:
  - `python3 -m unittest` — 96 testów OK (było 92).
  - Ręcznie, `CLAUDE_TOKEN_REPORT_CONFIG` na plik w scratchpadzie
    (`{"level":"compact","elements":["activities","sessions","skills"]}`), okres 15–21.10:
    `--only activities,map --diff` → liczby ogólne, czynności, „Not compared: map”; `--diff` → liczby ogólne,
    czynności, „Not compared: sessions, skills”; `--diff --bash --html` → czynności, „Takeaways” z szumem Basha
    (0.1% vs 1.3%), „Not compared: sessions, skills”.
  - Tekst, HTML i MD (`--diff`, `--full --diff`, `--diff --md`) porównane skryptem — te same części i liczby.
- Zmiany wyjścia domyślnego `--diff` (bez konfiguracji, `--from 2026-10-15 --to 2026-10-21`, przed/po):
  - tekst / MD z `-l pl` i `en`: znikają wiersze rodzajów tokenów (5 wierszy pod „tokeny ważone” — `time`
    nie jest w zestawie domyślnym), tabela „PROJEKTY (ważone)” (`breakdown` nie w zestawie) i „WNIOSKI”
    (`cache` nie w zestawie); dochodzi linia „Bez porównania: sessions, tips”. Czynności i modele bez zmian.
  - HTML: dochodzi wiersz „trafienia w cache” (był w tekście, nie w HTML), czynności przeniesione z tabeli
    ogólnej do osobnej tabeli `<h3>` w kolejności z tekstu (suma obu okresów zamiast samego bieżącego —
    np. „Bash: reading” wyżej, „Bash: build/test/lint” zamiast „asking the user”); dochodzi tabela modeli
    (wcześniej HTML w ogóle jej nie miał) i linia „Not compared: sessions, tips”.
  - `--full --diff` i `--md` bez niczego (wszystkie elementy): tekst/MD — dochodzi wniosek o szumie Basha
    i „Bez porównania: sessions, tips, skills, map”; HTML — dochodzą rodzaje tokenów, trafienia w cache,
    modele, projekty, wnioski (wszystko, co miał tekst) i ta sama linia.
  - Raport bez `--diff` — bez zmian (porównane 1:1; jedyne różnice w `--full` to liczby linii zmienionych
    plików w mapie projektu).
- Decyzje / odstępstwa:
  - Trafienia w cache liczone jako część podsumowania (podsumowanie je pokazuje), nie `cache`.
  - Kolumny HTML zostają „teraz / wcześniej / zmiana” (bez „różnica”) — te same wiersze i wartości co tekst;
    nazwy projektów w HTML nie są przycinane (tekst przycina do 37 znaków).
  - `report_html` importuje `diff_takeaways` z `report_text` (jedno miejsce treści wniosków).
  - Znalezione, nie zmienione: `--all --diff` gubi porównanie bez słowa — wpisane do „Otwarte pytania”.
