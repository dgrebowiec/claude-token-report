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
| `notes` | miękkie uwagi do stopki raportu (obecnie zawsze puste) |
| `has(element)` | czy element jest w raporcie |

`ReportContext.plan` przechowuje plan. Renderery czytają jeszcze stare pola `ReportContext`
(`short`, `full`, `sections`, `core`, `only_chosen`), które `cli._apply_plan` wypełnia z planu:
`short` = baza `short`, `full` = `long_tables`, sekcje i rdzeń = elementy planu.

## Presety (nazwane wartości osi)

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
  (domyślny, konfiguracja, `--short`, `--only`). `--short --long` jest dozwolone (krótki zestaw, długie tabele).
  Ograniczenie: raport `--short` ma jeszcze osobną ścieżkę renderowania ze sztywnymi długościami
  (tekst: czynności 8, modele 5; HTML: czynności 10, modele do 12), więc `--short --long` wydłuża w nim tylko
  najcięższe rozmowy — znika po scaleniu ścieżek (krok 3 planu).
- `--full` = wszystkie elementy + `long` (`--full --long` nie jest błędem, `--long` jest wtedy zbędne).
- Zapisany `level: "long"` daje długie tabele; `--long` przy zapisanym `compact` wydłuża je tylko w tym uruchomieniu.

`ReportPlan.long_tables` niesie wynik. `ElementInfo.comparable` (czy `--diff` ma porównanie dla elementu)
jest na razie `True` tylko dla `activities` i `models`.

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
| osobne polecenie + opcja raportu | `--list is a separate command, it takes no report options: --bash` |
| dwa osobne polecenia naraz | `give one command at a time, got: --list --explain` |
| nieznany element w `--only` | `argument --only: unknown element: foo (allowed: …)` |
| kilka sposobów podania okresu | `set the period one way only, got: …` (`periods.resolve_window`) |

Osobne polecenia: `--list`, `--explain`, `--configure`, `--reset-config`. Opcje raportu: okres
(`--days`, `--date`, `--from`, `--to`, `--today`, `--yesterday`, `--all`, `--rolling`), flagi sekcji,
`--short`, `--full`, `--long`, `--only`, `--diff`, `--daily`, `--session`, `--html`, `--md`, `--private`, `--no-config`.
Opcje globalne dozwolone wszędzie: `--lang`, `--color` / `--no-color`, `--dir`.

`--session --daily` jest dozwolone (dni jednej sesji).

## Testy

`tests/test_options.py` — presety, konfiguracja + flaga sekcji, `--only`, `--no-config`, `--md`,
`--long` (z każdą bazą), `ELEMENT_INFO`, migracja każdego starego poziomu (`MigrationTest`), każdy twardy błąd
i kod wyjścia 2 z `cli.main`. `tests/test_end_to_end.py` — `--long` nie zmienia sekcji, stary `minimal`
z pliku, konfigurator (zapis `long`, podgląd `compact`/`long`, przywracanie domyślnych).
