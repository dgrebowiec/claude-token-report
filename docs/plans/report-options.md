# Plan: spójne opcje raportu — bez sprzecznych ustawień i bez opcji, które po cichu nic nie robią

## Statusy kroków

| # | Krok | Status |
|---|------|--------|
| 1 | Jedno miejsce reguł: `resolve()` i błędy przy sprzecznych flagach | DONE |
| 2 | Szczegółowość = tylko długość tabel (`compact` / `long`) | DONE |
| 3 | Raport skrócony jako zestaw sekcji, a nie osobny tryb renderowania | DONE |
| 4 | Porównanie (`--diff`) zgodne z sekcjami raportu | DONE |
| 5 | Stopka „Ustawienia tego raportu” | DONE |
| 6 | `--dry-run`: co pokaże raport, bez liczenia | DONE |
| 7 | Konfigurator: ekran z pełną listą opcji i ich stanem | DONE |
| 8 | README i dokumentacja opcji | DONE |

Statusy: `TODO` — nie zaczęty, `IN_PROGRESS` — w trakcie (może być tylko jeden), `DONE` — ukończony i zweryfikowany.

## Jak korzystać z tego planu

- **Człowiek:** przeczytaj „Kontekst” i „Cel”; stan prac widać w tabeli wyżej, szczegóły
  w [`report-options_progress.md`](report-options_progress.md), dokumentację funkcjonalności
  w [`docs/references/report-options.md`](../references/report-options.md) (powstaje w kroku 1).
- **Agent, polecenie „kontynuuj PLAN”:** jeśli jest krok `IN_PROGRESS` — dokończ go
  (najpierw przeczytaj jego ostatni wpis w `report-options_progress.md`); jeśli nie ma — weź pierwszy `TODO`.
  Realizuj **jeden krok**, potem zrelacjonuj wynik i zatrzymaj się.
- Przed rozpoczęciem kroku ustaw mu `IN_PROGRESS`; `DONE` ustaw dopiero, gdy spełnione są
  wszystkie kryteria akceptacji i przeszła weryfikacja.
- W trakcie prowadź równolegle: dziennik `report-options_progress.md` (co zrobiono, wyniki, problemy)
  oraz dokumentację `docs/references/report-options.md`.
- Nie zmieniaj po cichu treści kroków. Odstępstwo → wpis w dzienniku i w sekcji „Zmiany planu”.
- **Nie twórz issues ani epików na GitHubie** — w tym projekcie cały plan żyje w repo (decyzja właściciela).

## Kontekst (skąd ten plan)

`claude-token-report` (pakiet `token_report/`, uruchamiany `python3 -m token_report`) liczy zużycie tokenów
Claude Code z lokalnych transkryptów i wypisuje raport w terminalu, HTML (`--html`) albo Markdown (`--md`).
Opcje rosły po kolei i zrobił się z nich „misz-masz”: da się ustawić sprzeczne opcje, a część opcji w danej
kombinacji nic nie zmienia — bez żadnego komunikatu. Właściciel zgłosił to tak: „da się ustawić sprzeczne opcje
np. wybrać kilka sekcji i odpalić z opcją diff i w raporcie brak sekcji, która pokazuje diff. Tak samo z wersją
minimal, normal… też w niektórych nie widać różnicy”.

Stan zastany (sprawdzony 2026-10-25 na kodzie i uruchomieniami):

1. `--short --diff --html X` — porównanie w ogóle nie trafia do HTML: `html_report` w
   `token_report/report_html.py` ma osobną gałąź `if ctx.short:`, która składa stronę bez `_comparison` i `_daily`.
   W terminalu porównanie się pojawia (`cli.py` drukuje `text_diff` przed raportem) — tekst i HTML się różnią.
2. `--session --diff` — porównanie znika bez słowa (dla `--session` bez okresu `cli.py` zeruje `window.start`,
   więc nie ma poprzedniego okresu).
3. `--short --bash --full` — trzy sprzeczne flagi, brak błędu; `report_text.text_report` w gałęzi `ctx.short`
   ignoruje sekcje i `--full`.
4. `--diff` porównuje zawsze ten sam stały zestaw (`text_diff` w `report_text.py`: liczby ogólne, czynności,
   modele, projekty, wnioski o długich rozmowach i wygasłym cache), niezależnie od wybranych sekcji; o sekcjach
   bez porównania (bash, skills, map) raport milczy.
5. Poziomy z konfiguratora (`settings.LEVELS = ("minimal", "normal", "detailed")`) mieszają dwie osie:
   `minimal` to w praktyce zestaw sekcji (`MINIMAL_ELEMENTS`), a `normal`/`detailed` różnią się tylko liczbą
   wierszy tabel (`context.CORE_ROWS = 5` / `TOP_ROWS = 10`) — w sekcjach bez rankingów nie widać różnicy.
6. `--full` znaczy dwie rzeczy naraz: wszystkie sekcje i długie tabele (`ReportContext.wants` / `rows`).
   Przy zapisanej konfiguracji „detailed” `cli.py` ustawia `ctx.full=True` + `ctx.only_chosen=True`, żeby
   rozdzielić te znaczenia — stąd flaga-łatka `only_chosen`.
7. Zapisana konfiguracja jest w całości ignorowana, gdy podasz jakąkolwiek flagę sekcji
   (`cli._saved_settings`): `--bash` daje raport domyślny + bash, a nie zestaw z konfiguracji + bash.
8. `--md` bez flag i bez konfiguracji włącza `ctx.full` (analiza ma mieć wszystkie dane) — reguła ukryta w `cli.py`.

**Decyzje właściciela:**
- „Propozycje są spoko” — zaakceptowany model: cztery niezależne osie (okres, zakres, sekcje, szczegółowość)
  + modyfikatory (`--diff`, `--daily`); sprzeczne flagi → błąd; flagi wiersza poleceń mają pierwszeństwo przed
  konfiguracją; modyfikator działa tylko na tym, co jest w raporcie; każdy raport mówi, czego nie pokazał i dlaczego;
  w konfiguratorze widok wszystkich opcji z oznaczeniem wykluczeń; `--dry-run`.
- „W tym projekcie nie twórz zadań w GitHubie” — plan i postęp tylko w repo, mimo że kroków jest ponad 5.
- Wcześniejsza obawa właściciela: „gorzej jak ktoś uruchomi coś z jakąś opcją, a sekcja jest wyłączona — to co
  wtedy” → odpowiedź planu: reguły pierwszeństwa (krok 1) + stopka „Ustawienia tego raportu” (krok 5) +
  `--dry-run` (krok 6). Nic nie może zniknąć po cichu.

**Model docelowy (obowiązuje we wszystkich krokach):**

| Oś | Wartości | Skąd |
|---|---|---|
| Okres | `--days`, `--date`, `--from/--to`, `--today`, `--yesterday`, `--all`, `--rolling` | bez zmian (`periods.resolve_window`) |
| Zakres | cała historia z okresu / `--session` | flaga |
| Elementy | podsumowanie (zawsze) + rdzeń `activities, models, sessions, tips` + sekcje `time, breakdown, cache, bash, skills, map` | konfiguracja, preset, flagi |
| Długość tabel | `compact` (5 wierszy) / `long` (10 wierszy) | konfiguracja, preset, `--long` |
| Modyfikatory | `--diff`, `--daily` | flagi |

Presety to tylko nazwane wartości osi — nie tryby renderowania:
- domyślny: elementy `activities, models, sessions, tips`, `compact`;
- `--short`: elementy `activities, models, sessions`, `compact`;
- `--full`: wszystkie elementy, `long`;
- `--md` bez presetu, flag sekcji i konfiguracji: jak `--full` (zachowuje dzisiejsze zachowanie, ale jawnie w `resolve`).

Reguły pierwszeństwa (od najsilniejszej):
1. Sprzeczne flagi w jednym poleceniu → błąd `argparse`-owy (`ap.error`) z nazwami flag (wzór: komunikat o okresie
   w `periods.resolve_window`).
2. Preset (`--short`/`--full`) albo `--only LISTA` zastępuje zestaw elementów z konfiguracji.
3. Flagi sekcji (`--bash`, `--cache`, …) **dopisują** sekcje do zestawu bazowego (konfiguracja albo preset albo domyślny).
4. `--no-config` — baza = domyślny zestaw.
5. Modyfikator działa na elementach, które są w raporcie; nigdy nie włącza ukrytych. Podsumowanie jest zawsze,
   więc `--diff` zawsze coś porównuje.

**Odrzucone / odłożone warianty:**
- Kolumny „wcześniej / zmiana” wewnątrz każdej sekcji raportu — odłożone: wymaga przepisania każdej sekcji w trzech
  rendererach; blok porównania filtrowany według sekcji (krok 4) daje tę samą informację przy małej zmianie.
  Można wrócić po skończeniu planu.
- Wchłonięcie `--daily` do sekcji `time` — odrzucone: „dzień po dniu” ma własne karty i zmiany dzienne, a zależność
  modyfikatora od sekcji wprowadziłaby właśnie taki rodzaj zaskoczenia, który plan usuwa. `--daily` zostaje
  samodzielnym blokiem, pokazywanym zawsze, gdy o niego poproszono.
- Poziom szczegółowości zmieniający treść każdej sekcji (np. skrócona i pełna wersja sekcji cache) — odrzucone:
  dużo pracy, a i tak trzeba by tłumaczyć, co gdzie się zmienia. Zamiast tego oś mówi uczciwie „tylko długość tabel”,
  a konfigurator pokazuje, których sekcji to nie dotyczy.

**Ograniczenia i założenia:**
- Bez nowych zależności (projekt: czysty Python, testy `unittest`).
- Teksty dla użytkownika zawsze dwujęzyczne przez `L("pl", "en")` z `token_report/i18n.py`.
- Stary plik konfiguracji (`~/.claude/claude-token-report.json`, `{"level": "minimal|normal|detailed", "elements": [...]}`)
  musi się dalej wczytywać (migracja w kroku 2).
- `--session --daily` działa dziś sensownie (dni jednej sesji) — zostaje dozwolone. `--session --diff` → błąd.
- Polecenia osobne (`--list`, `--explain`, `--configure`, `--reset-config`) z opcjami raportu → błąd
  „X to osobne polecenie, nie przyjmuje opcji raportu: …”. Opcje globalne (`--lang`, `--color/--no-color`, `--dir`)
  są dozwolone wszędzie.

**Mapa: prośba → krok**

| prośba | krok |
|---|---|
| sprzeczne opcje mają być niemożliwe albo jasne | 1 |
| minimal / normal / detailed — nie widać różnicy | 2, 3, 7 |
| sekcje + `--diff` → brak porównania sekcji | 3, 4 |
| widok wszystkich opcji w konfiguratorze z wykluczeniami | 7 |
| „ktoś uruchomi z opcją, a sekcja wyłączona — co wtedy” | 1, 5, 6 |
| rozpisać tak, żeby po `/clear` było wiadomo, o co chodzi | ten plik |

## Zatwierdzanie zmian

Domyślnie: commit (wiadomość po angielsku) na gałęzi `report-options` po każdym kroku, bez PR, bez `push`.
Wyjątki (data — ustalenie):
- 2026-10-25 — żadnych issues/epików na GitHubie.

## Cel i definicja ukończenia całości

Każda kombinacja opcji albo daje raport, w którym każda podana opcja ma widoczny skutek, albo kończy się
jasnym błędem; raport i konfigurator mówią, co pokazano, czego nie i dlaczego. Plan jest skończony, gdy:
- wszystkie przypadki 1–8 z „Kontekstu” są naprawione i każdy ma test;
- `python3 -m unittest` przechodzi;
- `ReportContext` nie ma pól `short`, `full`, `only_chosen` (zastąpione planem z `resolve`);
- README i `docs/references/report-options.md` opisują model osi i reguły pierwszeństwa.

## Poza zakresem

- Kolumny porównania wewnątrz sekcji (patrz „Odrzucone”).
- Nowe sekcje raportu i zmiany w obliczeniach (`stats.py`, `waste.py`, `hotspots.py`).
- Zmiana wyglądu HTML poza nowymi elementami (stopka, notka porównania).
- Issues/PR na GitHubie.

## Mapa kodu

- `token_report/cli.py` — parser (`build_parser`), `main`, `_saved_settings`, budowa `ReportContext`; tu podpinamy `resolve`.
- `token_report/options.py` — **do utworzenia**: `ReportPlan`, `resolve()`, `OptionsError`, tabela możliwości elementów.
- `token_report/context.py` — `ReportContext`, `SECTIONS`, `TOP_ROWS`, `CORE_ROWS`, metody `wants`/`shows`/`rows`.
- `token_report/settings.py` — `Settings`, `CORE`, `ELEMENTS`, `LEVELS`, `MINIMAL_ELEMENTS`, `describe*`, `from_dict` (migracja).
- `token_report/report_text.py` — `text_report` (gałąź `if ctx.short:`), `text_diff`, `_compare_groups`, `text_daily`, `_FLAGS`.
- `token_report/report_html.py` — `html_report` (gałąź `if ctx.short:`), `_comparison`, `_daily`, `_more`.
- `token_report/report_md.py` — `md_report` (składa bloki tekstowe).
- `token_report/tips.py` — używa `ctx.wants` (podpowiedzi „Szczegóły: --cache”).
- `token_report/configure.py` — konfigurator: `Editor`, `section_preview`, `key_help`, `line_help`, `run_tui`, `run`.
- `token_report/periods.py` — `picked_options`, `resolve_window` (wzór komunikatu błędu).
- Testy: `tests/test_units.py`, `tests/test_end_to_end.py`, nowy `tests/test_options.py` (**do utworzenia**).
- Testy: `python3 -m unittest` (z katalogu repo). Uruchomienie: `python3 -m token_report [opcje]`.
- Izolacja od własnej konfiguracji przy ręcznych próbach: `CLAUDE_TOKEN_REPORT_CONFIG=/ścieżka/nieistniejąca.json`.
- Uwaga: w systemie nie ma polecenia `python`, tylko `python3`.

## Kroki

### Krok 1: Jedno miejsce reguł: `resolve()` i błędy przy sprzecznych flagach

- **Po co:** dziś reguły „co pokazać” są rozsiane po `cli.py`, `ReportContext` i rendererach, więc sprzeczności
  przechodzą bez słowa; jedna funkcja daje jedno źródło prawdy dla CLI, konfiguratora i `--dry-run`.
- **Zależy od:** brak.
- **Co zrobić:**
  1. Utwórz `token_report/options.py` z:
     - `class OptionsError(ValueError)` — komunikat dla użytkownika (dwujęzyczny `L`).
     - `@dataclass(frozen=True) class ReportPlan`: `elements: Tuple[str, ...]` (w kolejności `settings.ELEMENTS`),
       `long_tables: bool`, `diff: bool`, `daily: bool`, `session: bool`,
       `origin: Dict[str, str]` (element → `"default" | "config" | "preset" | "flag"`),
       `base: str` (`"default" | "config" | "short" | "full" | "only" | "md"`), `notes: Tuple[str, ...]`
       (miękkie uwagi do stopki — na razie puste, wypełniają je kroki 4–5); metoda `has(element) -> bool`.
     - `resolve(args: argparse.Namespace, saved: Optional[Settings]) -> ReportPlan` realizująca
       presety i reguły pierwszeństwa z „Kontekstu”.
  2. Dodaj do parsera (`cli.build_parser`, grupa sekcji) `--only LISTA` (elementy po przecinku, nazwy jak w
     `settings.ELEMENTS`; nieznana nazwa → błąd z listą dozwolonych).
  3. Twarde błędy w `resolve` (każdy z testem): `--short` + `--full`; preset + `--only`; `--session` + `--diff`;
     osobne polecenie (`--list`, `--explain`, `--configure`, `--reset-config`) z którąkolwiek opcją raportu
     (okres, sekcje, presety, `--only`, `--diff`, `--daily`, `--session`, `--html`, `--md`, `--private`, `--no-config`).
     Sprawdzenie osobnych poleceń musi nastąpić **przed** ich obsługą w `cli.main`.
  4. W `cli.main` zastąp `_saved_settings` i ręczne ustawianie `ctx.short/full/only_chosen/sections/core`
     wywołaniem `resolve`; `OptionsError` → `ap.error(str(e))`. Na tym etapie wolno jeszcze przełożyć
     `ReportPlan` na stare pola `ReportContext` (adapter), żeby renderery działały bez zmian — usunięcie pól w kroku 3.
     Dodaj `plan: ReportPlan` do `ReportContext`.
  5. Zachowanie zmienione celowo: flagi sekcji dopisują się do konfiguracji (przypadek 7); `--md` bez niczego = jak `--full`,
     ale zapisane jako `base="md"`.
  6. Utwórz `tests/test_options.py`: testy macierzy — każdy twardy błąd, każdy preset, konfiguracja + flaga sekcji,
     `--only`, `--no-config`, `--md` domyślnie, stara konfiguracja `minimal` (do czasu kroku 2 zachowuje się jak `--short`).
     `args` buduj przez `cli.build_parser().parse_args([...])`.
- **Kryteria akceptacji:**
  - `python3 -m token_report --short --full` kończy się kodem 2 i komunikatem wymieniającym obie flagi.
  - `python3 -m token_report --session --diff` → błąd (kod 2), nie raport bez porównania.
  - `python3 -m token_report --list --bash` → błąd o osobnym poleceniu.
  - Z konfiguracją `{"level":"normal","elements":["activities","cache"]}` polecenie `--bash` pokazuje czynności, cache i bash.
  - `python3 -m unittest` przechodzi.
- **Weryfikacja:** `python3 -m unittest`; ręcznie powyższe polecenia z `CLAUDE_TOKEN_REPORT_CONFIG` wskazującym plik testowy.
- **Dokumentacja:** utwórz `docs/references/report-options.md` — model osi, presety, reguły pierwszeństwa, lista twardych błędów, `--only`.
- **Uwaga:** `--color`/`--no-color` mają `default=None` — nie traktuj ich jako opcji raportu. `--days` ma `default=None`, `--list` też
  (sprawdzaj `is not None`, nie prawdziwość — `--list 0` nie jest realnym przypadkiem, ale `--days 0.5` jest).

### Krok 2: Szczegółowość = tylko długość tabel (`compact` / `long`)

- **Po co:** poziomy `minimal/normal/detailed` mieszają wybór sekcji z długością tabel, przez co w wielu sekcjach „nie widać różnicy”.
- **Zależy od:** 1.
- **Co zrobić:**
  1. `settings.LEVELS = ("compact", "long")`; `Settings.level` domyślnie `"compact"`. Usuń `MINIMAL_ELEMENTS` z logiki `shown()` —
     `shown()` zwraca po prostu wybrane elementy w kolejności `ELEMENTS`.
  2. Migracja w `settings.from_dict`: `"minimal"` → `level="compact"` i `elements` = dotychczasowe ∩ `("activities","models","sessions")`
     (jeśli puste — te trzy); `"normal"` → `"compact"`; `"detailed"` → `"long"`. Zapis zawsze w nowym formacie.
  3. Dodaj flagę `--long` (grupa „zakres i widok”): długie tabele bez zmiany sekcji. `--full` = wszystkie elementy + `long`;
     `--short --long` jest dozwolone (krótki zestaw, długie tabele).
  4. W `options.py` tabela możliwości `ELEMENT_INFO: Dict[str, ElementInfo]` z polami `has_tables: bool` (czy długość tabel coś zmienia)
     i `comparable: bool` (czy `--diff` ma dla niego porównanie; wypełniane w kroku 4 — na razie wszystkie `False` poza `activities`, `models`).
     Ustal `has_tables` czytając renderery: element ma tabele, jeśli w `report_text.py` lub `report_html.py` jego liczba wierszy zależy od
     `ctx.rows`/`ctx.full`. Zapisz wynik w dzienniku.
  5. `settings.describe_level` — nowe opisy: „compact: tabele po 5 wierszy”, „long: tabele po 10 wierszy; nie zmienia sekcji bez tabel: …”
     (lista z `ELEMENT_INFO`).
  6. Testy migracji (każdy stary poziom) i `--long` w `tests/test_options.py` / `tests/test_units.py`.
- **Kryteria akceptacji:** stary plik z `"level":"detailed"` wczytuje się jako `long` z tymi samymi elementami; `--long` wydłuża tabele
  i nie dodaje sekcji; `python3 -m unittest` przechodzi.
- **Weryfikacja:** `python3 -m unittest`; ręcznie `python3 -m token_report --long` vs bez `--long` (różnica tylko w długości tabel).
- **Dokumentacja:** `docs/references/report-options.md` — oś długości tabel, `--long`, migracja starej konfiguracji, które elementy mają tabele.
- **Uwaga:** konfigurator (`configure.py`) używa `LEVELS` i `section_preview(element, level)` — musi dalej działać po zmianie nazw
  (podgląd dla `compact`/`long`); pełny ekran opcji to krok 7.

### Krok 3: Raport skrócony jako zestaw sekcji, a nie osobny tryb renderowania

- **Po co:** osobne gałęzie `if ctx.short:` w rendererach gubią porównanie i „dzień po dniu” (przypadek 1) i ignorują sekcje (przypadek 3).
- **Zależy od:** 2.
- **Co zrobić:**
  1. `ReportContext`: usuń pola `short`, `full`, `only_chosen`, `sections`, `core`; `wants(section)` i `shows(element)` → `plan.has(...)`;
     `rows` → `TOP_ROWS if plan.long_tables else CORE_ROWS`. Usuń adapter z kroku 1.
  2. `report_text.text_report` i `report_html.html_report`: usuń gałąź `if ctx.short:`; jedna ścieżka składa elementy z planu.
     Liczby wierszy, które w gałęzi short były na sztywno (np. `_activities(out, stats, 8)`), zastąp wartościami od `ctx.rows`
     tak jak w ścieżce domyślnej.
  3. W HTML `_comparison` i `_daily` są składane zawsze, gdy są dane (`prev`/`daily`), niezależnie od presetu.
  4. Usuń stopkę „To skrócony raport…” (zastąpi ją stopka z kroku 5); `_FLAGS`/`_more` podpowiadają brakujące sekcje na podstawie planu.
  5. `tips.py`: zamień `ctx.wants`/`ctx is None` na plan (zachowaj zachowanie dla `ctx=None`).
  6. Popraw testy, które sprawdzały `ctx.short`/`ctx.full`; dodaj test end-to-end: `--short --diff --html` zawiera porównanie,
     `--short --bash` zawiera sekcję bash.
- **Kryteria akceptacji:** `grep -n "ctx.short\|ctx.full\|only_chosen" token_report/` nic nie zwraca; `--short --diff --html X` zawiera
  blok porównania; `--short --daily --html X` zawiera „dzień po dniu”; `python3 -m unittest` przechodzi.
- **Weryfikacja:** `python3 -m unittest`; ręcznie HTML z `--short --diff` otwarty i sprawdzony.
- **Dokumentacja:** `docs/references/report-options.md` — presety jako zestawy elementów; renderery mają jedną ścieżkę.
- **Uwaga:** pojedyncza sesja (`ctx.session`/`ctx.detail`) ma własne bloki (`_session_info`, `_session_phases`) — nie zgub ich przy
  scalaniu ścieżek; w short-ścieżce `_session_phases` był pokazywany zamiast czynności/modeli/sesji.

### Krok 4: Porównanie (`--diff`) zgodne z sekcjami raportu

- **Po co:** dziś `--diff` porównuje stały zestaw, a o sekcjach bez porównania milczy (przypadek 4).
- **Zależy od:** 3.
- **Co zrobić:**
  1. Uzupełnij `ELEMENT_INFO[*].comparable`. Porównywalne na pewno: podsumowanie (zawsze), `activities`, `models`,
     `breakdown` (projekty — dziś w `text_diff`), `time` (rodzaje tokenów — dziś w tabeli ogólnej), `cache` (długie rozmowy, wygasły cache —
     dziś we „wnioskach”). Nieporównywalne: `map` (poprzedni okres liczony z `aggregate(..., hotspots=False)`), `skills`, `bash` — dla
     `bash` i `skills` sprawdź w `stats.py`, czy jest prosta liczba do porównania; jeśli tak — dodaj wiersz, jeśli nie — zostaw `False`
     i zapisz w dzienniku dlaczego.
  2. `text_diff` (i HTML `_comparison`) składa podsekcje porównania tylko dla elementów z `plan.elements` (liczby ogólne zawsze).
  3. Pod blokiem porównania jedna linia: „Bez porównania: <elementy z raportu, które nie są porównywalne>” — tylko gdy lista niepusta.
     Tę samą informację dopisz do `plan.notes` (do stopki z kroku 5).
  4. Testy: konfiguracja bez `models` + `--diff` → brak tabeli modeli w porównaniu; `--skills --diff` → linia „Bez porównania: skills”.
- **Kryteria akceptacji:** porównanie zawiera dokładnie te podsekcje, których elementy są w raporcie; elementy bez porównania są wymienione;
  wynik tekstowy, HTML i MD mówią to samo; `python3 -m unittest` przechodzi.
- **Weryfikacja:** `python3 -m unittest`; ręcznie `python3 -m token_report --only activities,map --diff`.
- **Dokumentacja:** `docs/references/report-options.md` — tabela „element → czy ma porównanie” (z `ELEMENT_INFO`).

### Krok 5: Stopka „Ustawienia tego raportu”

- **Po co:** odpowiedź na „ktoś uruchomi z opcją, a sekcja wyłączona — co wtedy”: raport zawsze mówi, skąd wziął zestaw i czego nie pokazał.
- **Zależy od:** 4.
- **Co zrobić:**
  1. W `options.py` funkcja `describe_plan(plan) -> List[str]` (dwujęzyczna) — 1–3 krótkie linie, np.:
     „Ustawienia: sekcje z konfiguracji (~/.claude/claude-token-report.json) + --bash · tabele krótkie · porównanie z 11–17.10”,
     „Bez porównania: skills, map”, „Bez konfiguracji: --no-config · zmiana: --configure”.
     Źródło bazy z `plan.base`/`plan.origin`; ścieżka konfiguracji z `settings.settings_path()` (przy `--private` bez zmian — to nie dane projektu).
  2. Wstaw ją na końcu raportu w `text_report`, `html_report` (`<p class=sub>`) i `md_report`, zamiast/obok dotychczasowej linii „Więcej szczegółów”
     (połącz, żeby nie było dwóch stopek mówiących o sekcjach).
  3. Testy: obecność stopki w trzech formatach; treść dla bazy `config`, `short`, `only`.
- **Kryteria akceptacji:** każdy raport (tekst/HTML/MD) kończy się stopką z bazą zestawu, długością tabel i — jeśli dotyczy — porównaniem
  i elementami bez porównania; `python3 -m unittest` przechodzi.
- **Weryfikacja:** `python3 -m unittest`; ręcznie raport domyślny, z konfiguracją, `--short --diff`.
- **Dokumentacja:** `docs/references/report-options.md` — opis stopki i przykład.

### Krok 6: `--dry-run`: co pokaże raport, bez liczenia

- **Po co:** pozwala sprawdzić skutek dowolnej kombinacji opcji przed wygenerowaniem raportu (zwłaszcza HTML do udostępnienia).
- **Zależy od:** 5.
- **Co zrobić:**
  1. Flaga `--dry-run` (grupa „wyjście”). W `cli.main` po `resolve` i `resolve_window`, **przed** `load(...)`: wypisz okres, zakres,
     listę elementów z pochodzeniem (`origin`), długość tabel, modyfikatory (z poprzednim okresem dla `--diff`), format wyjścia i plik,
     uwagi (`describe_plan`) i zakończ. Twarde błędy działają jak zwykle.
  2. `--dry-run` z osobnym poleceniem (`--list` itd.) → błąd z kroku 1.
  3. Testy: wynik dla kombinacji z konfiguracją i flagą; brak odczytu transkryptów (np. `--dir` na nieistniejący katalog nie przeszkadza —
     zdecyduj i zapisz w dzienniku; zalecane: `--dry-run` nie sprawdza katalogu).
- **Kryteria akceptacji:** `python3 -m token_report --short --bash --diff --dry-run` wypisuje plan bez raportu i bez czytania transkryptów;
  `python3 -m unittest` przechodzi.
- **Weryfikacja:** `python3 -m unittest`; ręcznie kilka kombinacji.
- **Dokumentacja:** `docs/references/report-options.md` — `--dry-run` z przykładem wyniku.

### Krok 7: Konfigurator: ekran z pełną listą opcji i ich stanem

- **Po co:** właściciel chce w konfiguratorze widok wszystkich opcji, z którego widać, co się wyklucza lub nie działa.
- **Zależy od:** 4 (potrzebne `ELEMENT_INFO` z `comparable`).
- **Co zrobić:**
  1. W `configure.py` widok „Podsumowanie” (pełnoekranowy `run_tui` i liniowy `run`): każdy element z `settings.ELEMENTS` w wierszu:
     `✓`/`·` (włączony/wyłączony), kolumna „długie tabele”: `tak` / `nie dotyczy` (z `has_tables`), kolumna „--diff”: `porównanie` /
     `bez porównania`; na górze długość tabel; pod spodem `⚠` z powodem dla ustawień bez skutku, np.
     „long nie zmienia: bash, cache” albo „wszystkie włączone elementy bez porównania — --diff pokaże tylko liczby ogólne”.
  2. Widok pojawia się przed zapisem (ENTER / `w`) z potwierdzeniem i pod nowym klawiszem (sprawdź, że nie koliduje z `KEYS`
     i klawiszami w `key_help`/`line_help`; zaktualizuj obie pomoce).
  3. Logika ostrzeżeń jako czysta funkcja w `options.py` (np. `warnings_for(settings) -> List[str]`), testowana jednostkowo;
     `configure.py` tylko ją wyświetla.
  4. Testy: `warnings_for` dla kilku konfiguracji; liniowy front-end (`run` z `ask=`) pokazuje podsumowanie przed zapisem.
- **Kryteria akceptacji:** w obu front-endach widać pełną listę z oznaczeniami; ostrzeżenia zgadzają się z tym, co pokazuje stopka raportu
  (ta sama tabela `ELEMENT_INFO`); `python3 -m unittest` przechodzi.
- **Weryfikacja:** `python3 -m unittest`; ręcznie `python3 -m token_report --configure` z `CLAUDE_TOKEN_REPORT_CONFIG` na plik testowy.
- **Dokumentacja:** `docs/references/report-options.md` — ekran podsumowania i znaczenie oznaczeń.

### Krok 8: README i dokumentacja opcji

- **Po co:** użytkownik ma znaleźć model osi i reguły w README, a nie odkrywać je metodą prób.
- **Zależy od:** 1–7.
- **Co zrobić:**
  1. README: sekcja o opcjach przepisana na model osi (tabela z „Kontekstu”), presety, reguły pierwszeństwa, `--only`, `--long`,
     `--dry-run`, stopka, migracja starej konfiguracji (poziomy `minimal/normal/detailed` → `compact/long`). Usuń sprzeczne stare opisy
     (szukaj `minimal`, `detailed`, `--full`, `--short`).
  2. `cli.build_parser`: teksty pomocy (`help=`, `epilog`, opisy grup) zgodne z modelem; `--configure` przestaje mówić o „minimal / normal / detailed”.
  3. Przejrzyj `docs/references/report-options.md` — stan obecny, bez historii.
- **Kryteria akceptacji:** `grep -rn "minimal\|detailed" README.md token_report/` zwraca tylko migrację w `settings.from_dict` (i jej opis);
  `python3 -m token_report --help` opisuje osie; `python3 -m unittest` przechodzi.
- **Weryfikacja:** `python3 -m unittest`; przeczytanie `--help` i README.
- **Dokumentacja:** README + `docs/references/report-options.md`.

## Zmiany planu

- 2026-10-25 (krok 2) — tekst pomocy `--configure` przepisany na `compact` / `long` już w kroku 2 (stare nazwy
  poziomów przestały istnieć); reszta pomocy i README zostaje w kroku 8.
- 2026-10-25 (krok 3) — `ReportContext.wants`/`shows` zastąpione jedną metodą `has(element)` (= `plan.has`),
  zamiast dwóch metod o tym samym działaniu.
- 2026-10-25 (krok 5, decyzja koordynatora; rozstrzyga otwarte pytanie z kroku 4) — `--all --diff` → twardy
  błąd w `options.resolve` (kod 2, jak `--session --diff`): cała historia nie ma poprzedniego okresu do
  porównania. Innych okresów bez poprzedniego nie ma (`previous_window_start` → `None` tylko przy
  `window.start is None`: `--all` i `--session` bez okresu, oba już błędem).
- 2026-10-25 (krok 5) — `ReportPlan` dostaje pole `only` (elementy z `--only`), żeby stopka odróżniała je od
  dopisanych flag sekcji (`origin` dla obu = `flag`).

## Otwarte pytania

<Brak. Wcześniejsza praca zacommitowana w `main` 2026-10-25 (a4af4fc); gałąź `report-options` zakładaj od `main`.>

Nie pushuj niczego do `main` (decyzja właściciela 2026-10-25) — tylko lokalne commity.
