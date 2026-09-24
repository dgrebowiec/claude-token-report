"""--explain: what raw and weighted tokens mean."""
from __future__ import annotations

from .i18n import L

EXPLAIN_PL = """\
CO ZNACZĄ LICZBY W TYM RAPORCIE
================================

1. JAK CLAUDE CODE ZUŻYWA TOKENY
   Token to kawałek tekstu (średnio 3-4 znaki). Model nie ma pamięci między
   zapytaniami, więc przy KAŻDYM wywołaniu Claude Code wysyła mu całą
   dotychczasową rozmowę: instrukcje systemowe, opisy narzędzi, CLAUDE.md,
   Twoje wiadomości, odpowiedzi modelu i wyniki narzędzi (treść plików,
   wyjście komend).
   Jedna Twoja prośba to zwykle od kilku do kilkudziesięciu wywołań: model
   czyta plik (wywołanie), szuka czegoś (wywołanie), edytuje (wywołanie)...
   i przy każdym z nich czyta CAŁĄ rozmowę od początku.

2. CZTERY RODZAJE TOKENÓW (tak zapisuje je Claude Code w transkryptach)
   wejście          nowy tekst, którego nie było w cache            waga x1
   odczyt z cache   część rozmowy wysłana już wcześniej, trzymana
                    w pamięci podręcznej (cache). Zwykle 90%+
                    wszystkich tokenów.                             waga x0.1
   zapis do cache   nowy fragment rozmowy (np. wynik narzędzia)
                    zapisany w cache, żeby następne wywołanie mogło
                    go tanio odczytać                   waga x1.25 (5 min) / x2 (1 h)
   wyjście          to, co model napisał: tekst, kod, wywołania
                    narzędzi, myślenie                              waga x5

3. SKĄD TE MNOŻNIKI?
   Z oficjalnego cennika API Anthropic. Dla każdego modelu obowiązują te
   same proporcje: odczyt z cache kosztuje 10% ceny zwykłego wejścia,
   zapis do cache 125% (cache 5-minutowy) lub 200% (1-godzinny), a wyjście
   5 razy tyle co wejście (np. Opus 5: 5 USD za 1M tokenów wejścia i 25 USD
   za 1M wyjścia). Wyjątki: Fable 5.1 ma odczyt z cache x0.025, Opus 5.5 x0.05.
   Na planie Pro/Max nie płacisz za tokeny, tylko masz limit użycia. Anthropic
   nie publikuje dokładnego wzoru tego limitu. Wiadomo, że droższe modele
   zużywają go szybciej. Raport ZAKŁADA, że limit liczy tokeny w tych samych
   proporcjach co cennik. To najlepsze dostępne przybliżenie, ale nie
   oficjalna liczba.

4. TOKENY SUROWE (NIEWAŻONE)
   Zwykła suma wszystkich czterech rodzajów, każdy token liczony tak samo.
   Wychodzą ogromne liczby (setki milionów), bo ta sama rozmowa jest
   czytana przy każdym wywołaniu. Surowe tokeny mówią, ILE TEKSTU przeszło
   przez model, ale nie, JAK MOCNO obciążyło to limit.

5. TOKENY WAŻONE (główna miara raportu)
   Każdy token mnożony przez wagę swojego rodzaju ORAZ wagę modelu:

     ważone = (wejście x1 + odczyt_cache x0.1 + zapis_cache x1.25 + wyjście x5)
              x waga modelu

   Przykład jednego wywołania przy rozmowie o długości ok. 100 tys. tokenów:
     odczyt z cache 100 000  x 0.1  = 10 000
     zapis do cache   2 000  x 1.25 =  2 500
     wyjście            500  x 5    =  2 500
     na Opus 5 (waga x1):   SUROWE 102 500   WAŻONE 15 000
     na Sonnet 5 (x0.4):    SUROWE 102 500   WAŻONE  6 000
   97% surowych tokenów to tani odczyt z cache, a obciążenie limitu rozkłada
   się prawie po równo na czytanie, zapis i odpowiedź.

6. WAGI MODELI (względem Opus 5)
   Fable 5 / 5.1         x2      Sonnet 4.x          x0.6
   Opus 5, Opus 4.5-4.8  x1      Sonnet 5            x0.4
   Opus 5.5              x0.8    Haiku 4.5           x0.2
   Ta sama praca na Sonnecie 5 obciąża limit 2.5 raza mniej niż na Opusie 5.

7. DLACZEGO DŁUGIE ROZMOWY ZUŻYWAJĄ WIĘCEJ
   Wywołanie przy rozmowie o długości 300 tys. tokenów musi ją całą
   przeczytać, więc samo czytanie to ok. 30 tys. tokenów ważonych, za każdym
   razem. Przy rozmowie o długości 50 tys. to tylko 5 tys. Dlatego:
     /clear    zaczyna od zera (najlepsze przy nowym, niezwiązanym zadaniu),
     /compact  zastępuje rozmowę krótkim podsumowaniem.

8. WYGASŁY CACHE
   Cache trzyma rozmowę przez 5 minut (czasem godzinę) od ostatniego użycia.
   Po dłuższej przerwie następne wywołanie musi zapisać CAŁĄ rozmowę od nowa
   (x1.25 zamiast x0.1, czyli 12.5 raza więcej za ten sam tekst).

9. JAK LICZONE SĄ CZYNNOŚCI („na co idą tokeny”)
   Każde wywołanie jest przypisane do narzędzia, którego model w nim użył
   (Read, Edit, Bash: git...). Gdy użył kilku naraz, dzielone jest po równo.
   Wywołanie bez narzędzia to odpowiedź tekstowa do Ciebie.
   Większość obciążenia to czytanie rozmowy, więc kategoria mówi, CO MODEL
   ROBIŁ w danym kroku, a nie co zajmuje w rozmowie najwięcej miejsca.

10. POZOSTAŁE POJĘCIA
   wywołanie      jedno zapytanie do modelu (jedna jego odpowiedź)
   kontekst/ctx   cała rozmowa, którą model czyta w danym wywołaniu
   subagent       osobna instancja Claude (narzędzie Agent) z własnym, czystym
                  kontekstem; jej praca nie wydłuża głównej rozmowy
   sesja          jedna rozmowa (plik transkryptu + jej subagenci)

Raport czyta wyłącznie lokalne pliki ~/.claude/projects/**/*.jsonl,
niczego nie wysyła i nie zużywa tokenów. Wagi: tabela cen w pliku
token_report/pricing.py (stan 2026-09).
"""

EXPLAIN_EN = """\
WHAT THE NUMBERS IN THIS REPORT MEAN
====================================

1. HOW CLAUDE CODE USES TOKENS
   A token is a chunk of text (3-4 characters on average). The model has no
   memory between requests, so on EVERY call Claude Code sends it the whole
   conversation so far: system instructions, tool descriptions, CLAUDE.md,
   your messages, the model's replies and tool results (file contents,
   command output).
   One request from you usually means several to dozens of calls: the model
   reads a file (a call), searches (a call), edits (a call)... and every one
   of them re-reads the WHOLE conversation from the start.

2. FOUR TOKEN TYPES (as Claude Code records them in its transcripts)
   input          new text that was not in the cache              weight x1
   cache read     part of the conversation sent before and kept
                  in the cache. Usually 90%+ of all tokens.       weight x0.1
   cache write    a new piece of conversation (e.g. a tool result)
                  stored in the cache so the next call can read
                  it cheaply                       weight x1.25 (5 min) / x2 (1 h)
   output         what the model wrote: text, code, tool calls,
                  thinking                                        weight x5

3. WHERE DO THESE MULTIPLIERS COME FROM?
   From Anthropic's official API pricing. Every model uses the same ratios:
   a cache read costs 10% of a normal input token, a cache write 125%
   (5-minute cache) or 200% (1-hour cache), and output 5 times the input
   price (e.g. Opus 5: $5 per 1M input tokens and $25 per 1M output tokens).
   Exceptions: Fable 5.1 cache reads are x0.025, Opus 5.5 x0.05.
   On a Pro/Max plan you don't pay per token, you have a usage limit.
   Anthropic does not publish the exact formula behind it. It is known that
   pricier models use it faster. This report ASSUMES the limit counts tokens
   in the same proportions as the pricing. That is the best available proxy,
   not an official number.

4. RAW (UNWEIGHTED) TOKENS
   The plain sum of all four types, every token counted the same. The
   numbers get huge (hundreds of millions) because the same conversation is
   re-read on every call. Raw tokens tell you HOW MUCH TEXT went through the
   model, not HOW HEAVILY it used your limit.

5. WEIGHTED TOKENS (the main measure of this report)
   Each token is multiplied by the weight of its type AND the model's weight:

     weighted = (input x1 + cache_read x0.1 + cache_write x1.25 + output x5)
                x model weight

   Example of one call in a conversation of about 100k tokens:
     cache read  100,000  x 0.1  = 10,000
     cache write   2,000  x 1.25 =  2,500
     output          500  x 5    =  2,500
     on Opus 5 (weight x1):    RAW 102,500   WEIGHTED 15,000
     on Sonnet 5 (x0.4):       RAW 102,500   WEIGHTED  6,000
   97% of the raw tokens are cheap cache reads, yet the load on the limit is
   split almost evenly between reading, writing and answering.

6. MODEL WEIGHTS (relative to Opus 5)
   Fable 5 / 5.1         x2      Sonnet 4.x          x0.6
   Opus 5, Opus 4.5-4.8  x1      Sonnet 5            x0.4
   Opus 5.5              x0.8    Haiku 4.5           x0.2
   The same work on Sonnet 5 uses the limit 2.5 times less than on Opus 5.

7. WHY LONG CONVERSATIONS USE MORE
   A call in a 300k-token conversation has to read all of it, so reading
   alone is about 30k weighted tokens, every single time. In a 50k-token
   conversation it is only 5k. That's why:
     /clear    starts from zero (best when switching to an unrelated task),
     /compact  replaces the conversation with a short summary.

8. EXPIRED CACHE
   The cache keeps the conversation for 5 minutes (sometimes an hour) after
   its last use. After a longer break the next call has to write the WHOLE
   conversation again (x1.25 instead of x0.1, i.e. 12.5x more for the same
   text).

9. HOW ACTIVITIES ARE COUNTED ("where the tokens go")
   Each call is assigned to the tool the model used in it (Read, Edit,
   Bash: git...). If it used several at once, it is split evenly. A call
   without a tool is a text reply to you.
   Most of the load is re-reading the conversation, so the category says
   WHAT THE MODEL WAS DOING in that step, not what takes the most space.

10. OTHER TERMS
   call           one request to the model (one model response)
   context/ctx    the whole conversation the model reads in a call
   subagent       a separate Claude instance (Agent tool) with its own clean
                  context; its work does not grow the main conversation
   session        one conversation (transcript file + its subagents)

The report reads only local files ~/.claude/projects/**/*.jsonl, sends
nothing and uses no tokens. Weights: the price table in
token_report/pricing.py (as of 2026-09).
"""


def explain_text() -> str:
    return L(EXPLAIN_PL, EXPLAIN_EN)
