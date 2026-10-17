---
name: token-efficiency
description: Ogranicza zużycie tokenów przy pracy z terminalem, plikami i danymi bez utraty informacji potrzebnych do poprawnego wyniku. Używaj przy poleceniach git, uruchamianiu testów lub lintera, czytaniu dużych plików, logów lub JSON-a oraz przy edycji dużych plików kodu.
---

# Oszczędność tokenów bez utraty jakości

Cel: niższy całkowity koszt do zweryfikowanego wyniku. Ucięty błąd, który wymusza kolejną pętlę, kosztuje więcej niż pełny log.

## Zasady

1. **Git:** zacznij od `git status -s` i `git diff --stat`; pełny diff pobieraj tylko dla pliku, który zmieniasz (`git diff -- ścieżka`).
2. **Testy i build:** używaj flag zwięzłości (`--bail`, `-x`, `-q`). Zachowaj pełny stack trace i podsumowanie z liczbą błędów.
3. **Dane strukturalne:** `jq`/`yq` zamiast wypisywania całego pliku; `grep -E "ERROR|WARN"` zamiast całego logu.
4. **Kod źródłowy, dwa etapy:** najpierw importy i sygnatury, potem docelowy fragment. Nigdy nie edytuj bez wglądu w importy i typy.
5. **Równolegle:** niezależne odczyty (read-only) uruchamiaj w jednej turze.
6. **Cache:** nie wstawiaj zmiennych danych (czas, losowe ID) na początek promptu i nie zmieniaj zestawu narzędzi MCP w trakcie sesji.

## Procedura awaryjna (fallback)

Jeśli polecenie kończy się błędem, a z przefiltrowanego wyjścia nie wynika przyczyna, **uruchom je ponownie bez filtra** i przeczytaj pełne wyjście. Nie zgaduj przyczyny na podstawie uciętego wyniku.

## Czego nie robić

- Nie używaj `head`/`tail` ani regexów na błędach kompilacji i stack trace'ach.
- Nie kompresuj kodu źródłowego narzędziami statystycznymi (np. LLMLingua).
- Nie opuszczaj uzasadnienia zmian w zadaniach architektonicznych i bezpieczeństwa.

## Szczegóły

Rozszerzone tabele i przykłady: `references/` (dodaj własne pliki w miarę potrzeb; ładują się tylko na żądanie).
