# Analiza procesu rekomendacji CRS 2.0 (stan na 20.10.2026)

Oct 20, 2026 · @Nicolas

## Najważniejsze wnioski

Graf v2 i fuzja RRF usunęły dwa największe problemy z 10.10 (puste węzły-zaślepki i sumowanie wyników), ale potok rekomendacji prawie nie korzysta jeszcze z nowej treści grafu. Drzewo kategorii (1 183 węzły `Taxon`), indeks pełnotekstowy oraz pola `features`, `details_text` i `description` istnieją w Neo4j, a mimo to resolver, filtry, Critic i generator odpowiedzi ich nie czytają.

- **Co działa lepiej:** każdy produkt ma tytuł (8 bez tytułu na 265 307), recenzje z osadzeniem ma 99,995% produktów, fuzja kanałów jest rangowa (RRF), a fałszywe CLARIFY zostały naprawione (R2a).
- **Co nadal psuje rekomendacje:** kategoria jest rozwiązywana wobec 38 działów Amazona („mouse” → „GPS & Navigation”, „keyboard” → „Musical Instruments”), Critic nie widzi parametrów i w 8 z 21 zapytań bazowego przebiegu v2 odrzucił wszystkich kandydatów, a odpowiedź końcowa nadal powstaje bez cech produktu.
- **Największy zysk za najmniejszy koszt:** połączyć kod z grafem v2 — rozwiązywać kategorię do drzewa `Taxon`, filtrować po poddrzewie, dodać indeks pełnotekstowy jako kanał RRF i przekazywać `features`/`details_text` do Critica i generatora. Większość tych zmian to dni pracy, nie tygodnie.
- **W Waszej mapie drogowej brakuje osobnego pakietu „konsumpcja grafu v2”.** Proponuję go wstawić przed R3–R4, bo od niego zależą RS-24, RS-10, RS-12 i RS-17.

## 1. Co się zmieniło od 10.10

Od commita `e6593f7` weszły trzy wydania: R1 (fuzja RRF), R2a (naprawa fałszywych CLARIFY) i F4 (przebudowa grafu do v2, aktywna od 20.10). Zmieniły się głównie `graph_search_tool.py`, nowy `score_fusion.py`, `orchestrator.py`, prompt ekstrakcji i cały potok `graph_v2`. Bez zmian pozostały `critic_agent.py`, `kecr_tool.py`, `prompt_constructor.py`, `dialogue_manager.py`, `session_schema.py`, `resolver_service.py`, `profile_tool.py` i `ui/app.py`.

| Wydanie | Co się zmieniło | Wpływ na proces rekomendacji |
| --- | --- | --- |
| R1 | Każdy kanał (tytuł, atrybut, recenzja) zwraca listę z produktem raz, wg najlepszego dopasowania (MaxP); listy łączy RRF (k = 60); bonus za preferencje skalowany do wyniku RRF; rangi kanałów w `eval_trace` | Koniec przewagi produktów z dużą liczbą recenzji; wyniki ograniczone do ok. 0,049 |
| R2a | Rzeczownik główny = kategoria; przy braku kategorii jedno wywołanie odzyskujące z `product_type_decided`; `clarify_reason`; naprawione „1500 → 150”; listy marek/kategorii przekazywane jako `brands`/`categories` | Mniej zbędnych pytań; pytanie tylko, gdy typ produktu naprawdę nie jest znany |
| F4 (graf v2) | Graf z surowych plików Amazon 2023: 8 produktów bez tytułu (było 104 281); 3,38 mln recenzji (max 20 na produkt) z `timestamp`, `helpful_vote`, `verified`; recenzje z osadzeniem na 99,995% produktów; drzewo `Taxon` (1 183 węzły, `IN_TAXON`, `BROADER`); indeks pełnotekstowy na `title`, `description`, `features`, `details_text`; 38 węzłów `Category` | Dane, o które prosiła poprzednia analiza, są już w grafie; kod wyszukiwania i odpowiedzi jeszcze z nich nie korzysta |

### Status ustaleń z 10.10

| Ustalenie z 10.10 | Status dziś |
| --- | --- |
| Sumowanie wyników nagradza popularność | **Rozwiązane** (R1; suma została tylko jako wariant `sum_legacy`) |
| \~100 tys. węzłów-zaślepek bez tytułu | **Rozwiązane** (v2) |
| Fałszywe CLARIFY, prompt „1500 → 150” | **Rozwiązane** (R2a) |
| Brak drzewa kategorii | **Częściowo:** drzewo jest w grafie, ale resolver, filtr i relaksacja go nie używają |
| Brak parametrów technicznych | **Częściowo:** `features` i `details_text` są na produkcie i w indeksie pełnotekstowym, ale nie trafiają do osadzenia produktu, Critica ani odpowiedzi; `Attribute` nadal ma tylko Material/Color/Style/Size |
| Recenzje bez znacznika czasu i głosów | **W grafie rozwiązane, w kodzie nie:** `fetch_product_attributes` i KECR używają nazw `helpful_votes` i `timestamp_iso`, których w v2 nie ma (są `helpful_vote` i `timestamp` w ms) |
| Nieznana cena przechodzi każdy budżet | **Bez zmian** (zasada P-2); w v2 57% produktów nie ma ceny |
| Dwa ekstraktory LLM, parser widzi tylko bieżącą wiadomość | **Bez zmian** |
| Critic: 20 wywołań, bez parametrów, fail-open | **Bez zmian** |
| KECR: część historyczna nie działa, α nie wpływa na ranking | **Bez zmian** (v2 ma już potrzebne dane, ale zapytanie dalej szuka `REVIEWS` i `BOUGHT_TOGETHER`) |
| Prompt końcowy bez cech, preferencji i historii | **Bez zmian** |
| Błędy stanu dialogu (listy marek, zmiana kategorii, wycofanie, „99,99”) | **Bez zmian** (pliki niezmienione) |
| Relaksacja po cichu porzuca kategorię | **Bez zmian** |
| Neo4j 5.14, filtr po wyszukiwaniu ANN | **Bez zmian** (decyzja D-4 otwarta) |

## 2. Rzeczywisty przebieg tury SEARCH i różnice względem diagramu

Diagram z 19.10 dobrze oddaje strukturę potoku, ale część opisów dotyczy grafu v1, a kilka zachowań kodu w ogóle na nim nie widać. Tak wygląda tura SEARCH w kodzie na dziś:

1. **Parser (LLM #1)** czyta tylko bieżącą wiadomość i zwraca `SessionContext`; `DialogueManager` scala go regułami.
2. **Router (LLM #2)** wybiera akcję. Jeśli wybierze SEARCH bez kategorii, uruchamia się odzyskiwanie kategorii (LLM #3, ten sam prompt co parametry wyszukiwania), a jego wynik jest później użyty ponownie.
3. **Parametry wyszukiwania (LLM #3, jeśli nie było odzyskiwania)** ponownie wyciągają filtry i `semantic_query`; przy konflikcie nadpisują parser.
4. **Filtry katalogowe:** tylko cena, marka, wykluczona marka i kategoria; reszta staje się preferencjami miękkimi (z wariantami jednostek).
5. **Normalizacja:** marka i kategoria przez resolver nad węzłami `Brand` i 38 węzłami `Category` (nie `Taxon`).
6. **Wyszukiwanie:** trzy zapytania `db.index.vector.queryNodes` (k = 600 globalnie), dopiero potem `WHERE` z filtrami, MaxP na produkt, 100 produktów na kanał, RRF, top 20; bonus za preferencje miękkie.
7. **Relaksacja:** przy < 3 wynikach cena ±15%, potem usunięcie kategorii.
8. **Critic (20 wywołań LLM)** ocenia każdego kandydata osobno na podstawie tytułu, ceny, marki, działu, atrybutów Material/Color/Style/Size i fragmentów recenzji; zostają 3 najlepsze zatwierdzone.
9. **KECR** dla tych 3 produktów; **odpowiedź (ostatnie wywołanie LLM)** z tytułu, działu, marki, ceny i ścieżek KECR.

Razem ok. 23–25 wywołań LLM na turę, z czego 20 to Critic.

| Element diagramu | Co mówi diagram | Co robi kod / graf dziś |
| --- | --- | --- |
| Product titles, Reviews | „39% untitled ghost nodes”, recenzje na 2,2% produktów | To dane v1. W v2: 8 produktów bez tytułu, recenzje z osadzeniem na 99,995% produktów |
| Entity Resolver | exact → substring/regex → vector | Działa nad 38 działami Amazona, nie nad drzewem `Taxon`. W przebiegu bazowym v2: „mouse” → „GPS & Navigation” (odrzucone, próg 0,70), „keyboard” → „Musical Instruments”, „laptop” → „Office Products” (brak marginesu), „webcam” → „Camera & Photo” (przyjęte, czyli filtr na 33 743 produkty) |
| Cypher constraints | cena, kategoria, marka | Kategoria = regex po nazwie działu **lub** po tytule; krawędź `SUBCATEGORY_OF` już nie istnieje. `brands` i `categories` (listy z R2a) nie są obsługiwane w `_build_filters`, więc „Dell lub HP” kończy się brakiem filtra marki. Brak ceny = spełnia budżet |
| One list per channel → RRF | ranking po filtrach | Filtry działają dopiero na 600 globalnie najbliższych węzłach z indeksu; produkty spoza tego okna nie mogą się pojawić. W kanale atrybutów wspólne węzły (np. „Color: Black”) dają remisy rozstrzygane alfabetycznie po ASIN |
| Soft-preference bonus | „scaled to the fused score” | Jedno trafienie = 0,25 × 3/61 ≈ 0,0123, a 20 najlepszych wyników RRF mieści się zwykle w ok. 0,016–0,044. Warianty jednostek („128GB”, „128 GB”, „128”) sumują się, więc jedno wymaganie może dać 2–3 bonusy |
| MACS relaxation | przy < 3 wynikach | Bez zmian i bez informowania użytkownika; `relaxed_constraints` trafia tylko do `eval_trace` |
| Critic Agent | per-item, 20 kandydatów | Zgodne, ale Critic nie dostaje `features`, `details_text` ani `description`; przy błędzie zatwierdza produkt |
| KECR + α | gating α (0–1) | α to trzy stałe i porządkuje tylko wiersze dowodów; nie zmienia rekomendacji. Gdy brak dowodów, zwraca „Top-rated category recommendation” z oceną 5,0, jeśli ocena jest nieznana |
| Prompt Constructor | top-3 + \[GRAPH EVIDENCE\], LLM w granicach faktów grafu | Pozycje mają „Features: None specified”, blok preferencji jest pusty, brak historii rozmowy i uzasadnień Critica |
| Brakuje na diagramie | — | Indeks pełnotekstowy i drzewo `Taxon` (są w grafie, nie w przepływie); nadpisywanie parsera przez LLM parametrów wyszukiwania |

## 3. Główne luki i pułapki

Uporządkowane od największego wpływu na jakość rekomendacji.

1. **Graf v2 nie jest używany przez potok.** Przebudowa zmieniła dane, ale nie zachowanie systemu: `Taxon`, indeks pełnotekstowy, `features`, `details_text`, `description`, `helpful_vote` i `timestamp` nie są czytane przez żaden etap rekomendacji. Szablon osadzenia produktu celowo został w wersji v1 (tytuł + dział + 5 atrybutów + opis, bez `features`), więc kanał tytułów nie widzi punktów z cechami produktu.
2. **Kategoria trafia w zły poziom taksonomii.** Resolver porównuje „mouse” czy „laptop” z 38 działami Amazona, więc albo odrzuca dopasowanie i filtr opiera się na regexie po tytule, albo przyjmuje zbyt szeroki dział („webcam” → „Camera & Photo”, 33 743 produkty). Regex po tytule przepuszcza akcesoria („keyboard cover” dla „keyboard”), a gdy wyników jest za mało, relaksacja usuwa kategorię całkowicie. Drzewo `Taxon` z węzłami typu „Laptops” czy „Mice” leży obok i nie jest używane.
3. **Critic ocenia bez dowodów i dlatego odrzuca wszystko.** Ma sprawdzić „60 FPS” czy „bone conduction”, nie widząc `features` ani `details_text`. Fragmenty recenzji są pobierane z limitem 20 na wszystkich kandydatów razem i sortowane po polach, których w v2 nie ma. W bazowym przebiegu v2 Critic odrzucił wszystkich kandydatów w 8 z 21 zapytań (46 zatwierdzeń, 374 odrzucenia). Przy błędzie LLM nadal zatwierdza produkt.
4. **Wyjaśnienia nie są ugruntowane.** Generator dostaje tytuł, dział, markę, cenę i ścieżki KECR, które zwykle powtarzają filtr marki/kategorii albo są tekstem zastępczym. Gdy Critic odrzuci wszystko, prompt nie ma pozycji ani instrukcji, jak to powiedzieć. Uzasadnienia Critica, które są jedynym miejscem porównania produktu z wymaganiami, do generatora nie trafiają.
5. **Semantyka ograniczeń jest zbyt luźna i cicha.** 57% produktów bez ceny przechodzi każdy budżet; listy `brands`/`categories` znikają bez śladu; relaksacja ceny i kategorii nie jest komunikowana użytkownikowi.
6. **Szczegóły rankingu mogą przeważać nad fuzją.** Okno 600 najbliższych węzłów przed filtrami ogranicza recall przy wąskich filtrach. Remisy w kanale atrybutów dają wielu produktom rangę 1 przez wspólny węzeł typu „Color: Black”. Bonus za preferencje (≈ 0,0123 za trafienie, sumowany po wariantach jednostek) porównywalny z całą rozpiętością wyników top 20 oznacza, że dopasowanie napisu w tytule często decyduje bardziej niż RRF.
7. **Stan dialogu wciąż gubi informacje.** Parser widzi jedną wiadomość, a drugi ekstraktor go nadpisuje. Błędy potwierdzone 10.10 uruchomieniem kodu nadal są aktualne (pliki bez zmian): dwie wykluczone marki → zostaje jedna, „Dell lub HP” → HP, zmiana kategorii zachowuje stary budżet i parametry, nie da się wycofać budżetu, „99,99” → 9999.
8. **Personalizacja ma nowe ograniczenie danych.** Część historyczna KECR wymaga przepisania (AI-03), ale v2 trzyma najwyżej 20 recenzji na produkt i wyklucza pary z podziałów valid/test. 3,38 mln recenzji na 2,59 mln użytkowników to średnio ok. 1,3 recenzji na użytkownika, więc historie większości użytkowników w grafie będą krótkie lub urwane przez limit. Interfejs nadal używa sztywnego `test_user_chainlit`, którego nie ma w grafie.

## 4. Rekomendacje usprawnień według etapów potoku

Wszystkie propozycje mieszczą się w ograniczeniach projektu: bez trenowania modeli, Amazon Reviews 2023, Neo4j 5.14 (upgrade jako opcja).

### 4.1 Kategoria: rozwiązywanie do drzewa `Taxon`

- Osadź 1 183 węzły `Taxon` tekstem `nazwa + pełna ścieżka` (koszt pomijalny) albo dopasowuj je leksykalnie po lemacie nazwy. Resolver powinien zwracać węzeł `Taxon`, a nie `Category`.
- Przy kilku trafieniach wybieraj dokładną nazwę, a w razie remisu węzeł o największym `product_count` (np. „headphones” → „Headphones”, nie „Earbud Headphones”). Gdy dwaj kandydaci leżą w różnych gałęziach z podobnym wynikiem, zadaj pytanie zamiast zgadywać.
- Filtr kategorii jako poddrzewo, z regexem po tytule tylko dla 6,5% produktów bez `IN_TAXON`:

```cypher
// fragment WHERE w zapytaniu kanału (node = ParentProduct)
EXISTS { MATCH (node)-[:IN_TAXON]->(:Taxon)-[:BROADER*0..7]->(:Taxon {taxon_id: $taxon_id}) }
OR (NOT EXISTS { (node)-[:IN_TAXON]->() } AND toLower(node.title) =~ $title_regex)
```

- Relaksacja kategorii = jeden krok w górę po `BROADER`, nigdy usunięcie filtra; zmianę zgłaszaj użytkownikowi.
- To jest właśnie RS-24 i RS-10 z Waszej mapy; po v2 nie potrzebują już słownika typów budowanego od zera.

### 4.2 Wyszukiwanie: wykorzystać to, co v2 już ma

- **Kanał pełnotekstowy w RRF.** Indeks `product_fulltext_index` (title, description, features, details\_text) działa na 5.14 przez `db.index.fulltext.queryNodes`. Zwraca dokładnie kształt `ChannelHit`, więc wystarczy dodać kanał `lexical` do `CHANNELS` i nowe warianty fuzji. To najszybsza droga do trafień na „60fps”, „ePTZ”, „WH-1000XM5” czy „bone conduction”.
- **Szablon osadzenia `product_v2`** z ścieżką `Taxon`, 3–5 pierwszymi punktami `features` i kluczowymi `details`, w osobnym indeksie. Indeks v1 zostaje do porównań, więc nie tracicie porównywalności v1/v2.
- **Filtr przed ANN, gdy poddrzewo jest małe.** `Taxon.product_count` od razu mówi, ile produktów przejdzie filtr kategorii. Dla poddrzew do kilkudziesięciu tysięcy produktów pobierz kandydatów filtrem i policz kosinus dokładnie (funkcją Cypher, jeśli 5.14 ją ma, albo w Pythonie); dla dużych zostaw ANN z nadpróbkowaniem. To realizacja RS-07 bez czekania na upgrade Neo4j.
- **Kanał atrybutów:** dopóki `Attribute` to tylko Material/Color/Style/Size, włączaj go tylko, gdy zapytanie wspomina kolor, materiał, styl lub rozmiar, albo waż rzadkością wartości (RS-03). Remisy rozstrzygaj podobieństwem tytułu, nie ASIN-em.
- **Bonus za preferencje:** licz jeden bonus na wymaganie (maksimum po wariantach jednostek, nie suma) i rozważ przeniesienie go do weryfikacji cech (RS-12) zamiast dopasowania napisu w tytule.

### 4.3 Ograniczenia: trzy wartości i jawne kompromisy

- Obsłuż `brands` i `categories` w `_build_filters` (alternatywa marek, suma poddrzew), a nieznany klucz filtra loguj jako ostrzeżenie zamiast `debug`.
- Cena nieznana = „nieznana”, nie „spełnia”: produkty z ceną w budżecie przed produktami bez ceny, a te drugie z etykietą „cena niepodana”. Zasada P-2 („nieznane nie jest niezgodnością”) zostaje, ale porządek i komunikat muszą ją odzwierciedlać.
- `relaxed_constraints` przekaż do odpowiedzi i powiedz użytkownikowi, co poluzowano.

### 4.4 Critic: jedno wywołanie z prawdziwymi dowodami

- Dla każdego kandydata przekaż: 3–5 punktów `features`, istotne pola `details_text`, początek `description`, cenę z informacją, czy jest znana, oraz 2 recenzje na produkt posortowane po `helpful_vote` (z limitem na produkt, nie globalnym).
- Zamień 20 wywołań na jedno wywołanie listowe (RS-17) zwracające dla każdego wymagania: spełnione / naruszone / nieznane + cytat. Ranking ustala kod: najpierw liczba naruszonych wymagań, potem nieznanych, potem RRF.
- Przy błędzie wróć do kolejności RRF (fail-closed), nigdy nie zatwierdzaj w ciemno.
- Gdy nic nie przechodzi, pokaż najlepsze częściowe dopasowania z opisem, czego brakuje, zamiast pustej listy.

### 4.5 Wyjaśnienia i KECR

- Generator ma dostawać tabelę werdyktów Critica i fakty, na których się oparł, i tylko z nich pisać uzasadnienie (RS-18). Wtedy wyjaśnienie jest dokładnie powodem rankingu.
- Usuń tekst zastępczy „Top-rated category recommendation (5.0★)” przy braku oceny; brak dowodów to brak ścieżki, nie wymyślona ocena.
- Przepisz część historyczną KECR pod v2 (AI-03): `(:User)-[:WROTE]->(:Review {rating, verified, timestamp})-[:ABOUT_PRODUCT]->(:ParentProduct)`, wspólny węzeł `Taxon`, marka; bez `BOUGHT_TOGETHER`.
- Ze względu na limit 20 recenzji na produkt rozważ osobne, lekkie krawędzie historii użytkownika z podziału treningowego, np. `(:User)-[:REVIEWED {rating, timestamp, verified}]->(:ParentProduct)` bez tekstu recenzji i bez limitu. Inaczej ścieżki „bo kupiłeś X” będą rzadkie.
- Albo zrezygnuj z α, albo użyj go jako wagi osobnego kanału „grafowego” w RRF, żeby rzeczywiście wpływał na wybór.

### 4.6 Stan dialogu

- Połącz parser i LLM parametrów w jedno wywołanie (AI-07), które widzi historię i bieżący stan i zwraca operacje (`set`, `add`, `remove`, `replace`, `reset`) zamiast nowego stanu. Wtedy znikają konflikty i dodatkowe wywołanie odzyskiwania kategorii.
- W reduktorze: zbiory marek, reset potrzeby przy zmianie kategorii na nieprzynależną do poddrzewa, operacja `remove`, parsowanie liczb z uwzględnieniem przecinka dziesiętnego (`extract_numeric_robust` już istnieje, ale nie jest wywoływany).
- Prawdziwy użytkownik demo z grafu zamiast `test_user_chainlit`.

## 5. Proponowana kolejność prac

Wasza mapa drogowa ma teraz R2b (benchmark v2), potem R3–R5. Z punktu widzenia samego procesu rekomendacji proponuję wstawić przed R3 pakiet „konsumpcja grafu v2”: kilka zadań z R3–R5 (RS-24, RS-10, RS-07, RS-12, RS-17) staje się dużo prostszych, gdy kod czyta `Taxon`, pełny tekst i `features`. Prace nad benchmarkiem mogą iść równolegle.

| Etap | Zakres | Powód | Mapowanie na Waszą mapę |
| --- | --- | --- | --- |
| **0. Szybkie poprawki (1–3 dni)** | Nazwy pól recenzji (`helpful_vote`, `timestamp`) i limit recenzji na produkt; `features`/`details_text`/`description` w `DETAIL_QUERY`, dla Critica i generatora; obsługa `brands`/`categories` w filtrze; Critic fail-closed; komunikat o relaksacji; usunięcie zastępczej oceny 5,0 w KECR; jeden bonus na wymaganie | Usuwa najbardziej widoczne błędne zachowania przy niemal zerowym koszcie | AI-06, część RS-05, AI-08 (fail-closed) |
| **1. Konsumpcja grafu v2 (ok. 1 tydzień)** | Resolver kategorii na `Taxon`; filtr poddrzewa; relaksacja w górę po `BROADER`; kanał pełnotekstowy w RRF; filtr przed ANN dla małych poddrzew; szablon `product_v2` w osobnym indeksie | Daje użytek z przebudowy grafu; naprawia złą kategorię i brak trafień na parametry | Nowy pakiet; obejmuje RS-24, RS-10, RS-07 |
| **2. Weryfikacja i wyjaśnienia** | Jeden listowy Critic z werdyktami na wymaganie i cytatami; ranking deterministyczny po werdyktach; generator piszący tylko z tabeli werdyktów | Kończy odrzucanie wszystkich kandydatów i wyjaśnienia z wiedzy modelu; 20 wywołań → 1 | RS-17, RS-12, RS-18 (przesunięte z R4/R5) |
| **3. Stan dialogu** | Jedno wywołanie z operacjami na stanie, reduktor ze zbiorami i resetem potrzeby, parser liczb z przecinkiem | Naprawia wieloturowe błędy; usuwa zdublowany ekstraktor | AI-07, B1 |
| **4. Personalizacja** | KECR historyczny pod v2; lekkie krawędzie historii użytkownika; kanał grafowy w RRF zamiast α; prawdziwy użytkownik w UI | Dodaje wartość grafu, o której mówi teza, i kończy z martwym α | AI-03, AI-05, RS-14 |
| **5. Później** | Typowane parametry z ekstrakcją LLM i cytatami źródła; aspekty z recenzji; upgrade Neo4j (D-4); lepszy model osadzeń | Większy koszt; większość korzyści da się uzyskać wcześniej przez pełny tekst i `features` | RS-11, RS-13, D-4 |

## Otwarte pytania i czego nie sprawdziłem

- **Analiza opiera się na kodzie z 20.10 (`1e77f48`, gałąź `feature/afp-002-vector-aggregation`), dokumentacji grafu v2 i logu bazowego przebiegu `eval_2026-10-20_1142`.** Nie wykonywałem zapytań do Neo4j: liczby grafu pochodzą z `graph_state_snapshot.md` i `validation_report.json`. Log służył tylko do potwierdzenia zachowania potoku, nie do oceny jakości.
- **Historie użytkowników:** nie policzyłem, ilu użytkowników ma w v2 co najmniej 3 recenzje po limicie 20 na produkt. Warto to sprawdzić jednym zapytaniem przed przepisaniem KECR.
- **Remisy w kanale atrybutów:** mechanizm wynika z kodu (wspólne węzły `Attribute`, sortowanie po ASIN), a log pokazuje wiele produktów z rangą 1; nie zmierzyłem, jak często zmienia to top 20.
- **Dokładny kosinus na 5.14:** przed realizacją filtra przed ANN sprawdź, czy Wasza wersja ma funkcję `vector.similarity.cosine`; jeśli nie, licz podobieństwo w Pythonie.
- **Decyzja projektowa do podjęcia:** czy cena nieznana ma być tylko oznaczana, czy także obniżać pozycję. To zmienia zasadę P-2 i powinno trafić do Vision Report.
