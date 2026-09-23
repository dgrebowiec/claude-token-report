"""Texts behind the "?" marks in the HTML report."""
from __future__ import annotations

import html

from .i18n import L

HELP = {  # tooltip texts for the "?" marks in the HTML report: key -> (pl, en)
    "calls": ("Wywołanie = jedno zapytanie do modelu (jedna jego odpowiedź). Jedna Twoja "
              "wiadomość to zwykle wiele wywołań — każde użycie narzędzia to kolejne.",
              "A call is one request to the model (one model response). One message from you "
              "usually triggers many calls — every tool use is another one."),
    "raw": ("Cały tekst, który model przeczytał i napisał, każdy token liczony tak samo. "
            "Model czyta rozmowę od nowa przy każdym wywołaniu, więc liczba jest ogromna i "
            "sama w sobie niewiele mówi.",
            "All text the model read and wrote, every token counted the same. The model "
            "re-reads the conversation on every call, so the number is huge and says little "
            "on its own."),
    "weighted": ("Główna miara. Tokeny liczone według tego, jak mocno obciążają limit: odczyt "
                 "z cache x0.1, nowy tekst x1, zapis do cache x1.25, odpowiedź x5, razy waga "
                 "modelu (Opus 5 x1, Sonnet 5 x0.4). Proporcje wzięte z cennika API Anthropic.",
                 "The main measure. Tokens counted by how heavily they use your limit: cache "
                 "read x0.1, new text x1, cache write x1.25, output x5, times the model weight "
                 "(Opus 5 x1, Sonnet 5 x0.4). Ratios taken from Anthropic's API pricing."),
    "hit": ("Jaka część rozmowy była tanim powtórnym odczytem z cache. Powyżej ~90% to dobry "
            "wynik; spadki = przerwy dłuższe niż 5 min albo zmiana modelu.",
            "How much of the conversation was cheap re-reading from cache. Above ~90% is good; "
            "drops = breaks over 5 minutes or a model switch."),
    "avgcall": ("Ile tokenów ważonych zużywa średnio jedno wywołanie modelu.",
                "How many weighted tokens one model call uses on average."),
    "weight": ("Mnożnik rodzaju tokenu z cennika API: odczyt z cache kosztuje 10% zwykłego "
               "wejścia, zapis 125% (5 min) lub 200% (1 h), wyjście 500%.",
               "Token type multiplier from the API pricing: a cache read costs 10% of normal "
               "input, a write 125% (5 min) or 200% (1 h), output 500%."),
    "mweight": ("Jak mocno model obciąża limit względem Opus 5 (x1), wg proporcji cen API. Ta "
                "sama praca na modelu x0.4 zużywa 2.5 raza mniej.",
                "How heavily the model uses the limit relative to Opus 5 (x1), based on API "
                "price ratios. The same work on a x0.4 model uses 2.5 times less."),
    "types": ("Te same tokeny policzone na dwa sposoby. Surowe: prawie wszystko to odczyt z "
              "cache. Ważone: widać, że odpowiedzi i zapisy do cache obciążają limit dużo "
              "bardziej, niż sugeruje ich liczba.",
              "The same tokens counted two ways. Raw: almost everything is cache reads. "
              "Weighted: output and cache writes load the limit far more than their count "
              "suggests."),
    "time": ("Tokeny ważone w kolejnych dniach (lub tygodniach), podzielone na rodzaje. Najedź "
             "na słupek, żeby zobaczyć dokładne wartości.",
             "Weighted tokens per day (or week), split by type. Hover a bar for exact values."),
    "daily": ("Każdy dzień porównany z poprzednim (w tokenach ważonych), z czynnością, która "
              "zmieniła się najbardziej. ▲ więcej, ▼ mniej, = bez zmian (±1%). Pierwszy "
              "wiersz (baza) to dzień przed okresem.",
              "Each day compared with the previous one (in weighted tokens), with the activity "
              "that changed the most. ▲ more, ▼ less, = unchanged (±1%). The first row (base) "
              "is the day before the period."),
    "driver": ("Czynność, której zużycie zmieniło się najbardziej względem poprzedniego dnia.",
               "The activity whose usage changed the most compared with the previous day."),
    "activity": ("Każde wywołanie przypisane do narzędzia, którego model w nim użył (przy kilku "
                 "narzędziach — po równo). „Bez narzędzia” = odpowiedź tekstowa do Ciebie.",
                 "Each call is assigned to the tool the model used in it (split evenly if "
                 "several). 'No tool' = a text reply to you."),
    "uses": ("Ile razy model użył tego narzędzia.", "How many times the model used this tool."),
    "avg": ("Ile tokenów ważonych średnio na jedno wywołanie lub użycie.",
            "Average weighted tokens per call or use."),
    "models": ("Zużycie wg modelu. Droższy model obciąża limit mocniej za tę samą pracę.",
               "Usage by model. A pricier model uses more of the limit for the same work."),
    "side": ("Sesja główna = Twoja rozmowa. Subagenci = osobne instancje Claude uruchomione "
             "narzędziem Agent; mają własny kontekst, więc nie wydłużają głównej rozmowy.",
             "Main session = your conversation. Subagents = separate Claude instances started "
             "with the Agent tool; they have their own context and don't grow the main one."),
    "agents": ("Zużycie subagentów wg typu (wbudowane albo Twoje własne).",
               "Subagent usage by type (built-in or your own)."),
    "projects": ("Zużycie wg katalogu, w którym uruchomiono sesję.",
                 "Usage by the working directory the session was started in."),
    "length": ("Kontekst = cała rozmowa czytana przy danym wywołaniu. Rośnie z każdym krokiem, "
               "więc im dłuższa rozmowa, tym więcej waży każde wywołanie. Nowe zadanie → "
               "/clear, długa praca → /compact.",
               "Context = the whole conversation read in a call. It grows with every step, so "
               "the longer the conversation, the more each call weighs. New task → /clear, "
               "long work → /compact."),
    "reading": ("Część wywołania, która idzie tylko na ponowne przeczytanie rozmowy. Rośnie "
                "razem z długością rozmowy.",
                "The part of a call spent only on re-reading the conversation. It grows with "
                "the conversation's length."),
    "sessions": ("Najcięższe rozmowy (razem z ich subagentami). Temat = Twoja pierwsza prośba. "
                 "Szczegóły: --session <id>.", "The heaviest conversations (including their "
                 "subagents). Topic = your first request. Details: --session <id>."),
    "maxctx": ("Do jakiego rozmiaru (w tokenach) urosła główna rozmowa.",
               "How large (in tokens) the main conversation grew."),
    "subshare": ("Jaka część zużycia tej sesji przypadła na subagentów.",
                 "The share of this session's usage spent by subagents."),
    "rebuild": ("Cache trzyma rozmowę 5 minut (lub godzinę). Po dłuższej przerwie model "
                "zapisuje całą rozmowę od nowa (x1.25) zamiast ją odczytać (x0.1). Liczone, gdy "
                "rozmowa ma ≥20k tokenów i ≥50% z niej zapisano.",
                "The cache keeps the conversation for 5 minutes (or an hour). After a longer "
                "break the model writes it all again (x1.25) instead of reading it (x0.1). "
                "Counted when the conversation is ≥20k tokens and ≥50% of it was written."),
    "waste": ("O ile więcej zużyły te odbudowy niż zwykły odczyt z cache.",
              "How much more those rebuilds used than a normal cache read."),
    "reread": ("Odczyty (narzędzie Read) fragmentu pliku, który już był w rozmowie — bez zmian "
               "ani kompakcji pomiędzy.", "Read tool calls for a part of a file already in the "
               "conversation — no edit or compaction in between."),
    "tips": ("Wskazówki wyliczone automatycznie z liczb powyżej.",
             "Suggestions computed automatically from the numbers above."),
    "compare": ("Te same miary dla poprzedniego okresu o tej samej długości.",
                "The same metrics for the previous period of the same length."),
}


def help_mark(key: str) -> str:
    """a focusable '?' that shows an explanation tooltip"""
    pl, en = HELP[key]
    return (f"<button type=button class=q aria-label='{html.escape(L('wyjaśnienie', 'explain'))}'"
            f" data-tip='{html.escape(L(pl, en), quote=True)}'>?</button>")
