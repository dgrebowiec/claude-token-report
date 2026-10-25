# Opcje raportu: model, presety i reguły pierwszeństwa

O tym, co pokaże raport, decyduje jedna funkcja: `token_report/options.py` → `resolve(args, saved)`.
Dostaje sparsowane argumenty (`cli.build_parser`) i ustawienia zapisane przez `--configure`
(`None`, gdy nic nie zapisano albo podano `--no-config`), a zwraca `ReportPlan` albo rzuca `OptionsError`.
`cli.main` wywołuje ją zaraz po parsowaniu, przed obsługą jakiegokolwiek polecenia; `OptionsError`
trafia do użytkownika jako błąd `argparse` (kod wyjścia 2).

## Osie

| Oś | Wartości | Skąd |
|---|---|---|
| Okres | `--days`, `--date`, `--from/--to`, `--today`, `--yesterday`, `--all`, `--rolling` | `periods.resolve_window` |
| Zakres | cała historia z okresu / `--session` | flaga |
| Elementy | podsumowanie (zawsze) + rdzeń `activities, models, sessions, tips` + sekcje `time, breakdown, cache, bash, skills, map` | konfiguracja, preset, `--only`, flagi sekcji |
| Długość tabel | `compact` (5 wierszy) / `long` (10 wierszy) | konfiguracja (`level`), preset `--full`, `--long` |
| Modyfikatory | `--diff`, `--daily` | flagi |

## `ReportPlan`

| Pole | Znaczenie |
|---|---|
| `elements` | elementy raportu poza podsumowaniem, w kolejności `settings.ELEMENTS` |
| `long_tables` | długie tabele (10 wierszy zamiast 5) |
| `diff`, `daily`, `session` | modyfikatory i zakres pojedynczej sesji |
| `origin` | element → `default` / `config` / `preset` / `flag` (skąd się wziął; `--only` = `flag`) |
| `base` | skąd zestaw bazowy: `default` / `config` / `short` / `full` / `only` / `md` |
| `only` | elementy podane w `--only` (dla stopki: odróżnia je od dopisanych flag sekcji) |
| `notes` | miękkie uwagi do stopki raportu; przy `--diff` — linia „Bez porównania: …” (patrz niżej), inaczej puste |
| `has(element)` | czy element jest w raporcie |

`ReportContext.plan` przechowuje plan (`cli.main` podaje go przy tworzeniu kontekstu; bez podania —
plan raportu domyślnego: rdzeń, krótkie tabele). Renderery pytają tylko o plan:
`ctx.has(element)` = `plan.has(element)`, `ctx.rows` = 10 przy `long_tables`, inaczej 5.
`ReportContext` nie ma już pól `short`, `full`, `only_chosen`, `sections`, `core`.

## Jedna ścieżka renderowania

`report_text.text_report` i `report_html.html_report` mają jedną ścieżkę: podsumowanie (zawsze), bloki
pojedynczej sesji, potem każdy element planu w stałej kolejności, na końcu stopka „Ustawienia tego raportu”
(patrz niżej). Nie ma osobnego trybu „raport skrócony” ani jego stopki — `--short` to tylko zestaw elementów, więc:

- `--short --bash` (i każda flaga sekcji) dopisuje sekcję do krótkiego zestawu;
- `--short --long` wydłuża wszystkie tabele krótkiego zestawu (czynności, modele, rozmowy);
- w HTML porównanie (`--diff`, `_comparison`) i „dzień po dniu” (`--daily`, `_daily`) są składane zawsze, gdy
  są dane — niezależnie od presetu; w terminalu i MD drukowane jak dotąd przed raportem;
- raport `--short` ma te same liczby wierszy co domyślny (np. czynności 8, modele 5), także w HTML.

Pojedyncza sesja (`--session`): po podsumowaniu bloki `_session_info` / `_session_models` / `_session_files`
(tekst) albo „Szczegóły sesji” (HTML), potem czynności (jeśli w planie), a zamiast rankingu rozmów —
fazy sesji (`_session_phases`, tekst); tabela modeli nie jest powtarzana (modele są w szczegółach sesji).
Tak samo z `--short` i bez niego.

`tips.tips(stats, ctx)` używa `ctx.has(sekcja)`: podpowiedź o sekcji spoza planu kończy się flagą
(„Szczegóły: --cache”); `ctx=None` — bez dopisków o flagach.

## Presety (nazwane wartości osi)

Preset to tylko zestaw elementów i długość tabel — nie tryb renderowania. Raport z presetem składa się
tak samo jak każdy inny.

| Preset | Elementy | Tabele | `base` |
|---|---|---|---|
| domyślny (bez niczego) | `activities, models, sessions, tips` | krótkie | `default` |
| `--short` | `activities, models, sessions` | krótkie | `short` |
| `--full` | wszystkie | długie | `full` |
| `--md PLIK` bez presetu, `--only`, flag sekcji i konfiguracji | wszystkie | długie | `md` |
| zapisana konfiguracja | `Settings.shown()` (wybrane elementy) | z `level` (`compact` / `long`) | `config` |

`--long` w każdym wierszu tej tabeli zmienia tylko kolumnę „Tabele” na długie.

## Długość tabel (`compact` / `long`) i `--long`

Oś mówi wyłącznie, ile wierszy mają tabele rankingowe — nie dodaje, nie usuwa i nie zmienia sekcji.

| Element | `compact` | `long` |
|---|---|---|
| `activities` | 8 wierszy (+ „pozostałe”) | 16 w terminalu/MD, 20 w HTML |
| `models` | 5 | 10 |
| `sessions` | 5 | 10 w terminalu/MD, 15 w HTML |
| `skills` | 5 na listę (HTML: nieużywane 10) | 10 na listę (HTML: nieużywane 20) |

Pozostałe elementy (`tips`, `time`, `breakdown`, `cache`, `bash`, `map`) mają tabele o stałej długości
albo nie mają tabel — długość tabel ich nie zmienia. Źródło prawdy: `options.ELEMENT_INFO[element].has_tables`
(ustalone z rendererów: liczba wierszy zależy od `ctx.rows` / długich tabel); z tej tabeli korzystają
`settings.describe_level` i konfigurator (dopisek „long nic tu nie zmienia” przy włączonych elementach bez tabel,
notka w podglądzie sekcji).

- `--long` (grupa „zakres i widok”) — długie tabele bez zmiany zestawu elementów; działa z każdą bazą
  (domyślny, konfiguracja, `--short`, `--only`). `--short --long` jest dozwolone (krótki zestaw, długie tabele —
  wydłużają się wszystkie jego tabele).
- `--full` = wszystkie elementy + `long` (`--full --long` nie jest błędem, `--long` jest wtedy zbędne).
- Zapisany `level: "long"` daje długie tabele; `--long` przy zapisanym `compact` wydłuża je tylko w tym uruchomieniu.

`ReportPlan.long_tables` niesie wynik.

## Porównanie (`--diff`) a elementy raportu

Blok porównania (tekst: `report_text.text_diff`, HTML: `report_html._comparison`, MD: ten sam tekst co
w terminalu) składa się wyłącznie z części dla elementów, które są w raporcie — modyfikator nie włącza
ukrytych elementów. Liczby ogólne (podsumowanie) są zawsze, więc `--diff` zawsze coś porównuje.
Źródło prawdy: `options.ELEMENT_INFO[element].comparable`.

| Element | Porównanie | Co porównuje |
|---|---|---|
| podsumowanie (zawsze) | tak | wywołania modelu, tokeny surowe, tokeny ważone, średnio na wywołanie, trafienia w cache |
| `activities` | tak | tabela „Na co idą tokeny (ważone)” (do 12 wierszy) |
| `models` | tak | tabela „Modele (ważone)” |
| `time` | tak | rodzaje tokenów (ważone) — wiersze pod „tokeny ważone” w tabeli ogólnej |
| `breakdown` | tak | tabela „Projekty (ważone)” |
| `cache` | tak | „Wnioski”: udział długich rozmów (kontekst > 200k) i nadmiar przez wygasły cache |
| `bash` | tak | „Wnioski”: udział szumu z poleceń Bash (długie wyniki bez ograniczenia) w zużyciu |
| `sessions` | nie | ranking rozmów — rozmowy z dwóch okresów to inne rozmowy, nie ma czego zestawić wiersz w wiersz |
| `tips` | nie | podpowiedzi to wnioski z bieżącego okresu, nie liczby |
| `skills` | nie | liczby opisują listę skilli (konfigurację), nie zużycie w okresie; „używane w N rozmowach” zależy od liczby rozmów |
| `map` | nie | poprzedni okres liczony bez mapy projektu (`aggregate(..., hotspots=False)`) |

Tabele grup (czynności, modele, projekty) mają do 12 wierszy, kolejność według sumy ważonych tokenów
z obu okresów — tak samo w tekście i HTML (HTML nie ma kolumny „różnica”, tylko „zmiana” ze strzałką).
Dla `bash` poprzedni okres dostaje `waste.find_waste` w `cli.main` tylko wtedy, gdy `bash` jest w planie
(`aggregate(..., hotspots=False)` go nie liczy).

Pod blokiem porównania jedna linia „Bez porównania: <elementy>” / „Not compared: <elementy>” — elementy
z raportu bez porównania, nazwami jak w `--only`; pomijana, gdy lista jest pusta
(`options.no_comparison_note`, `options.uncompared`). Ta sama linia trafia do `ReportPlan.notes`
(stopka nie powtarza jej jako osobnej linii — patrz niżej). Przykłady:

- domyślny raport + `--diff` → podsumowanie, czynności, modele; „Bez porównania: sessions, tips”;
- `--only activities,map --diff` → podsumowanie, czynności; „Bez porównania: map”;
- `--full --diff` → wszystkie części; „Bez porównania: sessions, tips, skills, map”;
- `--only activities,models --diff` → bez linii „Bez porównania”.

`--diff` zawsze ma poprzedni okres: jedyne okresy bez niego — `--all` i `--session` bez okresu — są
twardymi błędami (`--all --diff`, `--session --diff`, patrz „Twarde błędy”). Okno `--rolling` / ułamkowe `--days`
ma poprzednie okno tej samej długości. Poprzedni okres bez danych daje porównanie z zerami, nie znika.

## Stopka „Ustawienia tego raportu”

Każdy raport kończy się stopką z `options.describe_plan(plan, prev_label, config_path=None)` — 2–3 krótkie
linie (dwujęzyczne, `L`):

1. **Ustawienia** — skąd zestaw elementów (`plan.base`), dopisane flagi sekcji (`origin == "flag"`, poza
   `--only`), długość tabel, a gdy dotyczy: porównanie z poprzednim okresem (`ctx.prev_label`) z krótką listą
   elementów bez porównania, „dzień po dniu”.
2. **Więcej szczegółów** — flagi sekcji, których nie ma w raporcie, „albo --full (wszystko)”; pomijana, gdy
   raport ma wszystkie sekcje.
3. **Jak zmienić** — przy zestawie z konfiguracji: „Bez konfiguracji: --no-config · zmiana: --configure”, w innym
   razie „Własny zestaw na stałe: --configure”; zawsze „tokeny surowe i ważone: --explain”.

Dalej ewentualne inne `plan.notes`. Linia „Bez porównania: …” z `notes` nie jest powtarzana — raport pokazuje
ją już pod blokiem porównania (z `--diff` blok jest zawsze), a stopka wymienia te elementy skrótowo w linii 1.

Baza zestawu w linii 1:

| `base` | Tekst (pl) |
|---|---|
| `default` | `zestaw domyślny` |
| `config` | `sekcje z konfiguracji (<ścieżka>)` — `settings.settings_path()`, katalog domowy jako `~`; także przy `--private` (to nie dane projektu) |
| `short` / `full` | `--short` / `--full` |
| `only` | `--only <lista>` |
| `md` | `wszystkie elementy (domyślnie dla --md)` |

Gdzie stoi: terminal — ostatnie linie `text_report` (po wskazówkach, przed linią zamykającą; porównanie
i „dzień po dniu” są drukowane wcześniej); HTML — `<p class=sub>` z liniami rozdzielonymi `<br>` (`_settings`),
po ostatniej sekcji, tuż przed `<footer>` z wagami i datą wygenerowania; MD — ostatnia sekcja pliku
„## Ustawienia tego raportu” (lista `- …`), a blok raportu w MD jest bez stopki (`text_report(..., footer=False)`),
żeby nie była dwa razy. Treść we wszystkich trzech jest ta sama. Stopka zastąpiła dawne linie „Więcej
szczegółów” i „Pełne wyjaśnienie tokenów surowych i ważonych: --explain” (`_FLAGS` / `_more`).

Przykład — raport domyślny (`-l pl`):

```text
 Ustawienia: zestaw domyślny · tabele krótkie (5 wierszy)
 Więcej szczegółów: --time --breakdown --cache --bash --skills --project-map  albo --full (wszystko)
 Własny zestaw na stałe: --configure · tokeny surowe i ważone: --explain
```

Przykład — konfiguracja `{"level":"compact","elements":["activities","sessions","skills"]}` + `--bash --diff --daily`:

```text
 Ustawienia: sekcje z konfiguracji (~/.claude/claude-token-report.json) + --bash · tabele krótkie (5 wierszy) · porównanie z 2026-10-12..2026-10-18 (7 dni), bez porównania: sessions, skills · dzień po dniu
 Więcej szczegółów: --time --breakdown --cache --project-map  albo --full (wszystko)
 Bez konfiguracji: --no-config · zmiana: --configure · tokeny surowe i ważone: --explain
```

Przykład — `--short --diff` (en):

```text
 Settings: --short · compact tables (5 rows) · compared with 2026-10-12..2026-10-18 (7 days), not compared: sessions
 More detail: --time --breakdown --cache --bash --skills --project-map  or --full (everything)
 Your own saved set: --configure · raw and weighted tokens: --explain
```

## `--dry-run`: co pokaże raport, bez liczenia

`--dry-run` (grupa „wyjście”) wypisuje plan raportu i kończy — bez czytania transkryptów, bez zapisu plików
`--html` / `--md`. W `cli.main` działa po `resolve` (twarde błędy jak zwykle, kod 2) i po `resolve_window`
(błędy okresu też), ale **przed** sprawdzeniem katalogu transkryptów, szukaniem sesji i `load(...)`:

- katalog (`--dir` albo `~/.claude/projects`) nie jest sprawdzany — `--dir /nieistniejący --dry-run` działa,
  wynik mówi „(nie sprawdzano)”;
- `--session ID` nie jest szukana („szukana dopiero przy raporcie”); bez okresu — „cała sesja”;
- plik z `--html` / `--md` nie powstaje („(nie zapisano)”).

Treść (`options.describe_dry_run`, dwujęzyczna): okres (`periods.period_label`, ten sam co w nagłówku raportu),
zakres, elementy z pochodzeniem (podsumowanie — zawsze; `zestaw domyślny`, `konfiguracja`, `--short` / `--full`,
`--md (domyślnie wszystko)`, `--only`, flaga sekcji), długość tabel (przy `long` — elementy bez tabel, których to
nie zmienia, z `ELEMENT_INFO`), modyfikatory (`--diff` z poprzednim okresem i elementami bez porównania, `--daily`),
wyjście (terminal / pliki, `--private`), katalog transkryptów. Na końcu **stopka raportu** — dokładnie linie
`describe_plan`, które ten sam raport wypisze na końcu (jedno źródło, bez osobnej logiki).

`--dry-run` jest opcją raportu: z osobnym poleceniem (`--list --dry-run` itd.) → błąd
„--list is a separate command, it takes no report options: --dry-run”.

Przykład — `--short --bash --diff --from 2026-10-15 --to 2026-10-21 --dry-run` (bez konfiguracji):

```text
--dry-run: what the report would show — nothing counted, no transcripts read
 Period:       2026-10-15..2026-10-21 (7 days)
 Scope:        all history in the period
 Elements:     summary     always
               activities  --short
               models      --short
               sessions    --short
               bash        --bash
 Tables:       compact (5 rows)
 Modifiers:    --diff: compared with 2026-10-08..2026-10-14 (7 days); not compared: sessions
 Output:       the terminal
 Transcripts:  ~/.claude/projects (not checked)
 Report footer:
   Settings: --short + --bash · compact tables (5 rows) · compared with 2026-10-08..2026-10-14 (7 days), not compared: sessions
   More detail: --time --breakdown --cache --skills --project-map  or --full (everything)
   Your own saved set: --configure · raw and weighted tokens: --explain
```

Przykład — konfiguracja `{"level":"compact","elements":["activities","sessions","skills"]}` +
`-l pl --bash --long --daily --html raport.html --dry-run` (okres 15–21.10):

```text
--dry-run: co pokaże raport — nic nie policzono, transkrypty nie zostały przeczytane
 Okres:        2026-10-15..2026-10-21 (7 dni)
 Zakres:       cała historia z okresu
 Elementy:     podsumowanie  zawsze
               activities    konfiguracja
               sessions      konfiguracja
               bash          --bash
               skills        konfiguracja
 Tabele:       długie (10 wierszy); bez zmian (bez tabel): bash
 Modyfikatory: --daily: dzień po dniu
 Wyjście:      HTML: raport.html (nie zapisano)
 Transkrypty:  ~/.claude/projects (nie sprawdzano)
 Stopka raportu:
   Ustawienia: sekcje z konfiguracji (~/.claude/claude-token-report.json) + --bash · tabele długie (10 wierszy) · dzień po dniu
   Więcej szczegółów: --time --breakdown --cache --project-map  albo --full (wszystko)
   Bez konfiguracji: --no-config · zmiana: --configure · tokeny surowe i ważone: --explain
```

## Plik konfiguracji i migracja starych poziomów

`~/.claude/claude-token-report.json` (albo `CLAUDE_TOKEN_REPORT_CONFIG`): `{"level": "compact" | "long",
"elements": [...]}`; domyślnie `compact` i `activities, models, sessions, tips`. `Settings.shown()` zwraca
wybrane elementy w kolejności `settings.ELEMENTS`.

Stare poziomy wczytuje `settings.from_dict` (tabela `settings.OLD_LEVELS`):

| Stary `level` | Nowy `level` | Elementy |
|---|---|---|
| `minimal` | `compact` | dotychczasowe ∩ `activities, models, sessions` (gdy puste — te trzy) |
| `normal` | `compact` | bez zmian |
| `detailed` | `long` | bez zmian |

Nieznany poziom → `compact`. Plik nie jest przepisywany przy wczytaniu; zapis (`--configure`) jest zawsze
w nowym formacie.

## `--only LISTA`

Elementy po przecinku, nazwy jak w `settings.ELEMENTS`:
`activities, models, sessions, tips, time, breakdown, cache, bash, skills, map`.
Kolejność w raporcie jest zawsze kolejnością `ELEMENTS`, nie kolejnością na liście. Nieznana nazwa
(albo pusta lista) → błąd `argparse` z listą dozwolonych. Tabele krótkie (długie z `--long`). Przykład:
`python3 -m token_report --only models,cache`.

## Reguły pierwszeństwa (od najsilniejszej)

1. Sprzeczne flagi w jednym poleceniu → błąd (lista niżej).
2. Preset (`--short` / `--full`) albo `--only` zastępuje zestaw z konfiguracji.
3. Flagi sekcji (`--time`, `--breakdown`, `--cache`, `--bash`, `--skills`, `--project-map`) **dopisują**
   sekcje do zestawu bazowego (konfiguracja, preset albo domyślny). Przykład: konfiguracja
   `{"level": "normal", "elements": ["activities", "cache"]}` + `--bash` → czynności, cache i bash.
4. `--no-config` → konfiguracja jest pomijana, bazą jest zestaw domyślny (albo `md` dla `--md`).
5. Modyfikatory (`--diff`, `--daily`) działają na tym, co jest w raporcie, i nie włączają ukrytych elementów.

## Twarde błędy

| Kombinacja | Komunikat (en) |
|---|---|
| `--short` + `--full` | `--short and --full exclude each other …` |
| `--only` + `--short` albo `--full` | `--only and --short exclude each other: both pick the set of sections …` |
| `--session` + `--diff` | `--diff does not work with --session: a single session has no previous window …` |
| `--all` + `--diff` | `--diff does not work with --all: all history has no previous window to compare with` |
| osobne polecenie + opcja raportu | `--list is a separate command, it takes no report options: --bash` |
| dwa osobne polecenia naraz | `give one command at a time, got: --list --explain` |
| nieznany element w `--only` | `argument --only: unknown element: foo (allowed: …)` |
| kilka sposobów podania okresu | `set the period one way only, got: …` (`periods.resolve_window`) |

Osobne polecenia: `--list`, `--explain`, `--configure`, `--reset-config`. Opcje raportu: okres
(`--days`, `--date`, `--from`, `--to`, `--today`, `--yesterday`, `--all`, `--rolling`), flagi sekcji,
`--short`, `--full`, `--long`, `--only`, `--diff`, `--daily`, `--session`, `--html`, `--md`, `--private`, `--no-config`, `--dry-run`.
Opcje globalne dozwolone wszędzie: `--lang`, `--color` / `--no-color`, `--dir`.

`--session --daily` i `--all --daily` są dozwolone (dni jednej sesji / całej historii).

## Testy

`tests/test_options.py` — presety, konfiguracja + flaga sekcji, `--only`, `--no-config`, `--md`,
`--long` (z każdą bazą), `ELEMENT_INFO`, migracja każdego starego poziomu (`MigrationTest`), każdy twardy błąd
i kod wyjścia 2 z `cli.main`. `tests/test_end_to_end.py` — `--long` nie zmienia sekcji, stary `minimal`
z pliku, konfigurator (zapis `long`, podgląd `compact`/`long`, przywracanie domyślnych).
`--short` jako zestaw elementów: `test_short`, `test_short_is_a_set_of_elements` (flagi sekcji dopisują się,
`--short --long` — te same sekcje), `test_html_short_keeps_comparison_and_daily` (`--short --diff --html` ma
porównanie, `--short --daily --html` — „dzień po dniu”), `--session --short` ma fazy sesji;
`tests/test_waste.py` — plan `--short --bash` renderuje sekcję bash w tekście i HTML; porównanie szumu Basha
(`test_diff_compares_the_bash_noise`). Porównanie według elementów: `test_diff_follows_the_elements_of_the_report`
i `test_diff_names_the_elements_without_comparison` (tekst, HTML, MD), `test_diff_notes_the_elements_without_comparison`
(`plan.notes`), lista porównywalnych w `test_element_info_covers_every_element`. Stopka: `DescribePlanTest`
w `tests/test_options.py` (bazy `default`, `config` + flaga, `short` z `--diff --daily`, `only`, `full`, `md`,
po polsku, ścieżka z `~`), `test_every_format_ends_with_the_settings_footer` (tekst, HTML, MD mówią to samo,
stopka raz) i `test_footer_follows_the_preset` w `tests/test_end_to_end.py`. `--dry-run`: `DryRunTest` w `tests/test_options.py` (plan dla `--short --bash --diff`,
stopka = `describe_plan`, konfiguracja + flaga sekcji, pliki niezapisane, sesja nieszukana, błędy; odczyt
transkryptów — `load`, `find_session`, `recent_sessions` — kończy test błędem).
