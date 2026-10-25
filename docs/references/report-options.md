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
| Długość tabel | krótkie (5 wierszy) / długie (10 wierszy) | konfiguracja (`detailed` = długie), preset `--full` |
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
(`short`, `full`, `sections`, `core`, `only_chosen`), które `cli._apply_plan` wypełnia z planu.

## Presety (nazwane wartości osi)

| Preset | Elementy | Tabele | `base` |
|---|---|---|---|
| domyślny (bez niczego) | `activities, models, sessions, tips` | krótkie | `default` |
| `--short` | `activities, models, sessions` | krótkie | `short` |
| `--full` | wszystkie | długie | `full` |
| `--md PLIK` bez presetu, `--only`, flag sekcji i konfiguracji | wszystkie | długie | `md` |
| zapisana konfiguracja | `Settings.shown()` | długie przy poziomie `detailed` | `config` |

Zapisany poziom `minimal` daje zestaw `Settings.shown()` (część wspólna z `activities, models, sessions`)
i nadal renderuje się jako raport skrócony.

## `--only LISTA`

Elementy po przecinku, nazwy jak w `settings.ELEMENTS`:
`activities, models, sessions, tips, time, breakdown, cache, bash, skills, map`.
Kolejność w raporcie jest zawsze kolejnością `ELEMENTS`, nie kolejnością na liście. Nieznana nazwa
(albo pusta lista) → błąd `argparse` z listą dozwolonych. Tabele krótkie. Przykład:
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
`--short`, `--full`, `--only`, `--diff`, `--daily`, `--session`, `--html`, `--md`, `--private`, `--no-config`.
Opcje globalne dozwolone wszędzie: `--lang`, `--color` / `--no-color`, `--dir`.

`--session --daily` jest dozwolone (dni jednej sesji).

## Testy

`tests/test_options.py` — presety, konfiguracja + flaga sekcji, `--only`, `--no-config`, `--md`,
stare poziomy `minimal` / `detailed`, każdy twardy błąd i kod wyjścia 2 z `cli.main`.
