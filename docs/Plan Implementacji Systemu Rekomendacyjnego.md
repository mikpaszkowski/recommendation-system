# **Architektura Systemu Konwersacyjnej Rekomendacji Nowej Generacji: Kompleksowy Plan Implementacji Modułu Hybrydowego, Semantycznego i Pamięciowego**

## **1\. Wstęp Teoretyczny i Uzasadnienie Architektury**

Współczesne systemy rekomendacyjne (CRS \- Conversational Recommender Systems) przechodzą fundamentalną transformację, ewoluując z prostych mechanizmów filtrowania kolaboratywnego w stronę zaawansowanych agentów kognitywnych zdolnych do prowadzenia wieloetapowych, kontekstowych dialogów. Analiza literatury przedmiotu wskazuje na istnienie krytycznej luki pomiędzy możliwościami generatywnymi Dużych Modeli Językowych (LLM) a precyzją wymagana w systemach decyzyjnych. Tradycyjne podejścia często zawodzą w scenariuszach, gdzie preferencje użytkownika są niejawne, dynamicznie zmienne lub gdy system napotyka problem zimnego startu. Niniejszy raport definiuje architekturę, która adresuje te wyzwania poprzez integrację trzech filarów: hybrydowego modelowania preferencji, semantycznego wnioskowania opartego na grafach wiedzy oraz adaptacyjnej pamięci długoterminowej.

Kluczowym wyzwaniem, które ten projekt ma na celu rozwiązać, jest dychotomia między elastycznością konwersacji a precyzją rekomendacji. LLM, takie jak GPT-4 czy Llama 3, wykazują bezprecedensowe zdolności w rozumieniu języka naturalnego i wnioskowaniu zdroworozsądkowym.1 Jednakże, ich bezpośrednie zastosowanie w systemach rekomendacyjnych obarczone jest ryzykiem halucynacji oraz trudnościami w obsłudze wielkoskalowych korpusów przedmiotów, które dynamicznie się zmieniają.2 Co więcej, użytkownicy rzadko wyrażają swoje preferencje w sposób bezpośredni i kategoryczny; częściej są one ukryte w niuansach językowych, co wymaga zaawansowanych mechanizmów ekstrakcji i kwantyfikacji.1

Proponowana architektura *Knowledge Enhanced Conversational Reasoning* (KECR) oraz *Memory-enhanced CRS* (MemoCRS) stanowi odpowiedź na potrzebę budowania systemów, które nie tylko "polecają", ale "rozumieją" i "pamiętają". System ten musi zarządzać ciągłością preferencji użytkownika na przestrzeni wielu sesji, redukując szum informacyjny i redundancję historycznych dialogów.4 Plan wdrożenia został podzielony na trzy fazy, z których każda stanowi fundament dla kolejnej, tworząc spójny ekosystem technologiczny.

## ---

**2\. Faza I: Implementacja Modelu Hybrydowego LLM+BERT (Ekstrakcja i Kwantyfikacja)**

Pierwsza faza projektu koncentruje się na warstwie percepcyjnej systemu. Jej celem jest przekształcenie nieustrukturyzowanego strumienia dialogu w ustrukturyzowane, kwantyfikowalne sygnały decyzyjne. Innowacyjność tego podejścia polega na zastosowaniu architektury hybrydowej, która wykorzystuje generatywne zdolności LLM do identyfikacji jakościowej oraz dyskryminacyjne zdolności modelu BERT do oceny ilościowej.

### **2.1. Ekstrakcja Niejawnych Preferencji: Rola LLM**

W interakcjach człowiek-komputer, preferencje użytkowników często pozostają niejawne. Użytkownik, stwierdzając "Podobał mi się 'Mroczny Rycerz' ze względu na mroczną atmosferę", nie wskazuje wprost gatunku "Thriller psychologiczny", lecz implikuje go poprzez opis cech. Wykorzystanie LLM w tej fazie służy do "tłumaczenia" języka naturalnego na przestrzeń atrybutów domenowych.

Proces ten opiera się na zaawansowanym promptingu (*Instruction Tuning*), który instruuje model, aby pełnił rolę analityka preferencji. LLM analizuje kontekst rozmowy ($Conv$) i generuje zbiór atrybutów $U\_i$, które zostały pozytywnie zweryfikowane w toku dialogu. Badania wykazują, że modele takie jak GPT-3.5-turbo oraz GPT-4 osiągają wysoką skuteczność w identyfikacji kategorii preferowanych, nawet jeśli nie zostały one wymienione wprost.1 Kluczowe jest tu zastosowanie podejścia *Chain-of-Thought* (CoT), które zmusza model do jawnego wyprowadzenia wnioskowania przed podaniem finalnej klasyfikacji, co znacząco redukuje błędy interpretacyjne.

Dodatkowo, system musi być zdolny do ekstrakcji atrybutów osobistych użytkownika, takich jak zawód czy hobby, które wykraczają poza standardową taksonomię produktów. W tym celu implementowany jest mechanizm *Hidden Attribute Models* (HAM) lub jego wariant oparty na wyszukiwaniu – *Retrieval-based HAM* (RHAM). RHAM wykorzystuje zewnętrzne bazy wiedzy do mapowania słów kluczowych (np. "trampki", "maraton") na atrybuty wysokiego poziomu (np. "Biegacz").5 Pozwala to na budowanie głębszego profilu użytkownika, który będzie wykorzystywany w późniejszych fazach do personalizacji stylu komunikacji.

### **2.2. Kwantyfikacja Preferencji: Rola Klasyfikatora BERT**

Samo zidentyfikowanie kategorii jest niewystarczające dla precyzyjnego silnika rekomendacyjnego. Informacja o tym, że użytkownik lubi "Komedie" i "Romanse", jest zbyt ogólna. Kluczowe jest zrozumienie relatywnej siły tych preferencji. W tym celu, w drugiej części Fazy I, wprowadzamy klasyfikator wieloetykietowy (Multi-label Classifier) oparty na architekturze BERT.1

Architektura tego podmodułu składa się z enkodera BERT, który przetwarza sekwencję dialogu na wektorową reprezentację kontekstową, a następnie przekazuje ją przez serię warstw gęstych (Dense Layers). Konfiguracja warstw (np. 768 \-\> 384 \-\> 128 \-\> $N$, gdzie $N$ to liczba kategorii) pozwala na stopniową kompresję informacji semantycznej do postaci wektora prawdopodobieństw $P\_i$. Każdy element tego wektora odpowiada jednej kategorii domenowej (np. gatunkowi filmowemu) i przyjmuje wartość z przedziału , reprezentującą pewność modelu co do preferencji użytkownika w danym wymiarze.

Trening tego klasyfikatora odbywa się w paradygmacie *Weak Supervision* lub *Distillation*, gdzie etykiety generowane przez LLM w procesie ekstrakcji jakościowej ($U\_i$) służą jako "ground truth" dla modelu BERT. Takie podejście pozwala na wykorzystanie wiedzy zawartej w LLM do wytrenowania mniejszego, szybszego i bardziej deterministycznego modelu, który może być uruchamiany w czasie rzeczywistym przy każdym nowym zdaniu użytkownika.

### **2.3. Rekonstrukcja Konwersacji i Wzbogacanie Kontekstu**

Finalnym krokiem w Fazie I jest zamknięcie pętli sprzężenia zwrotnego poprzez rekonstrukcję kontekstu konwersacji. Surowy tekst dialogu jest wzbogacany o wyekstrahowane i skwantyfikowane preferencje, tworząc nową reprezentację $Conv^{+P\_i}$.

Tabela 1\. Porównanie skuteczności różnych reprezentacji kontekstu w procesie rekomendacji (na podstawie 1).

| Typ Kontekstu | Opis | Wpływ na Recall@20 | Wpływ na NDCG@20 |
| :---- | :---- | :---- | :---- |
| **Conv** | Surowy tekst dialogu. | Bazowy | Bazowy |
| **Conv \+ $U\_i$** | Dialog \+ kategorie kategoryczne (np.). | Umiarkowany wzrost | Umiarkowany wzrost |
| **Conv \+ $P\_i$** | Dialog \+ kategorie z wagami (np.). | **Znaczący wzrost (+23.3% dla ReDial)** | **Znaczący wzrost** |

Jak wynika z danych przedstawionych w Tabeli 1, jawne dołączenie numerycznych wartości preferencji do promptu dla LLM drastycznie poprawia jakość rekomendacji. Model językowy, otrzymując precyzyjne wagi, jest w stanie lepiej zbalansować sprzeczne sygnały i wygenerować listę rekomendacji, która ściślej odpowiada rzeczywistym potrzebom użytkownika. Jest to realizacja koncepcji *Profile-Augmented Prompting*, która redukuje szum informacyjny i pozwala modelowi skupić się na najistotniejszych sygnałach decyzyjnych.

Aby rozwiązać problem niedoboru wysokiej jakości danych treningowych dla wieloetapowych dialogów, system wykorzystuje framework **IterChat**.6 IterChat dekomponuje skomplikowany proces ekstrakcji preferencji z wielu tur na iteracyjne, jednoetapowe procesy. Wykorzystuje GPT-4 do generowania schematów preferencji i syntetycznych dialogów, co pozwala na stworzenie robustnego zbioru treningowego dla modelu BERT, eliminując problem "Annotating Disaster" i propagacji błędów w uczeniu sekwencyjnym.

## ---

**3\. Faza II: Moduł Zarządzania Grafem Wiedzy (Semantyka i Wyjaśnialność)**

W drugiej fazie implementacji system zostaje wzbogacony o "mózg" semantyczny w postaci Grafu Wiedzy (Knowledge Graph \- KG). Same modele językowe, mimo że potężne, operują na statystycznych korelacjach słów, co może prowadzić do halucynacji i braku precyzji faktograficznej. KG stanowi ustrukturyzowaną bazę wiedzy, która zapewnia poprawność relacji między encjami oraz umożliwia generowanie wyjaśnialnych rekomendacji. Implementacja tej fazy opiera się na architekturze KECR (*Knowledge Enhanced Conversational Reasoning*).8

### **3.1. Integracja Przestrzeni Embeddingów: Mutual Information Maximization (MIM)**

Podstawowym wyzwaniem technicznym w tej fazie jest *Luka Semantyczna* (Semantic Gap) pomiędzy reprezentacją tekstową dialogu (generowaną przez LLM/BERT) a reprezentacją strukturalną encji w grafie (generowaną przez sieci grafowe). Encje w grafie (np. węzeł "Horror") i słowa w dialogu (np. "straszny film") pochodzą z różnych rozkładów wektorowych i nie są bezpośrednio porównywalne.

Aby rozwiązać ten problem, system implementuje mechanizm **Maksymalizacji Informacji Wzajemnej (MIM)**. Proces ten polega na wyrównaniu (alignment) przestrzeni embeddingów kontekstowych ($q\_t$) i embeddingów encji ($e\_v$). Embeddingi kontekstowe uzyskiwane są z enkodera tekstu, natomiast embeddingi encji generowane są przez grafowe sieci neuronowe, takie jak R-GCN (*Relational Graph Convolutional Network*), które agregują informacje z sąsiedztwa w grafie.8

Algorytm MIM wykorzystuje estymator Jensena-Shannona do minimalizacji rozbieżności między tymi rozkładami. System jest trenowany w trybie kontrastowym (contrastive learning), gdzie pary (wypowiedź, pasująca encja) są traktowane jako przykłady pozytywne, a pary (wypowiedź, losowa encja) jako negatywne. Funkcja celu wymusza, aby reprezentacje wektorowe pojęć semantycznie tożsamych (np. tekst "uwielbiam filmy o kosmosie" i węzeł "Sci-Fi") znajdowały się blisko siebie w wielowymiarowej przestrzeni. Dzięki temu, system "rozumie", że niejawne sygnały w tekście odnoszą się do konkretnych struktur w bazie wiedzy.8

### **3.2. Jawne Wnioskowanie i Ścieżki Wyjaśnialne**

W przeciwieństwie do systemów, które wykorzystują KG jedynie jako dodatkowe źródło cech (implicit knowledge distillation), proponowany moduł realizuje **Jawne Wnioskowanie** (*Explicit Reasoning*) na strukturze grafu.8 Jest to kluczowe dla zapewnienia transparentności i budowania zaufania użytkownika (Trustworthiness).

Proces wnioskowania przebiega następująco:

1. **Identyfikacja Punktów Startowych (Seed Nodes):** System mapuje encje wykryte w dialogu (np. "Incepcja") na węzły w grafie.  
2. **Ekspansja Ścieżek (Reasoning Chains):** Algorytm przeszukuje graf, eksplorując relacje wychodzące z punktów startowych (np. *Incepcja* $\\xrightarrow{directed\\\_by}$ *Christopher Nolan* $\\xrightarrow{directed}$ *Interstellar*).  
3. **Punktacja i Selekcja:** Każda ścieżka otrzymuje ocenę wiarygodności opartą na sile relacji oraz zgodności semantycznej z bieżącym kontekstem dialogu (obliczonej dzięki MIM). System wybiera tzw. "Prominent Reasoning Chain" – ścieżkę, która najlepiej łączy historię użytkownika z potencjalną rekomendacją.

Wygenerowana ścieżka staje się nie tylko mechanizmem selekcji, ale również *Reasoning Flow* dla modułu generowania odpowiedzi. Zamiast generować rekomendację z "czarnej skrzynki", system jest w stanie skonstruować odpowiedź opartą na dowodach: "Skoro podobała Ci się *Incepcja*, polecam *Interstellar*, ponieważ oba filmy zostały wyreżyserowane przez Christophera Nolana i poruszają tematykę manipulacji rzeczywistością".8 Taka forma komunikacji jest znacznie bardziej naturalna i przekonująca dla użytkownika.

### **3.3. Skalowalne Wyszukiwanie: Dual Encoders i RecLLM**

W przypadku bardzo dużych korpusów przedmiotów (np. miliony filmów na YouTube), bezpośrednie wnioskowanie na pełnym grafie może być nieefektywne obliczeniowo. W tej fazie implementujemy również mechanizmy wyszukiwania inspirowane architekturą **RecLLM** 2, które służą jako wstępny filtr dla modułu wnioskowania grafowego.

Wykorzystujemy tu podejście *Generalized Dual Encoder*, gdzie jeden enkoder (LLM) przetwarza kontekst rozmowy, a drugi przetwarza metadane przedmiotów. Pozwala to na szybkie wyszukiwanie przybliżonych najbliższych sąsiadów (Approximate Nearest Neighbor \- ANN) w przestrzeni wektorowej. Dla scenariuszy wymagających dostępu do zewnętrznych API wyszukiwania, system implementuje strategię *Search API Lookup*, gdzie LLM generuje zapytanie tekstowe do zewnętrznej wyszukiwarki, a wyniki są następnie procesowane przez moduł grafowy. Taka hybrydyzacja zapewnia skalowalność przy zachowaniu głębi wnioskowania semantycznego.

## ---

**4\. Faza III: Moduł Zarządzania Dialogiem z Architekturą Pamięciową**

Trzecia faza projektu integruje warstwę percepcji i semantyki w spójny system decyzyjny, wyposażony w zaawansowaną pamięć długoterminową. Celem jest stworzenie agenta, który nie tylko reaguje na bieżące zapytanie, ale buduje relację z użytkownikiem w czasie, adaptując się do zmian jego gustu. Architektura ta czerpie z rozwiązań **MemoCRS** 4 oraz **CRIF**.9

### **4.1. Architektura Pamięciowa MemoCRS**

System implementuje dwuwarstwową strukturę pamięci, zaprojektowaną w celu rozwiązania problemów redundancji danych historycznych oraz problemu zimnego startu.

#### **4.1.1. Pamięć Specyficzna dla Użytkownika (User-Specific Memory \- UM)**

Tradycyjne podejście polegające na doklejaniu całej historii rozmów do promptu (context window) jest nieefektywne i generuje szum. Zamiast tego, system wykorzystuje dynamiczny bank pamięci oparty na encjach (entity-based memory bank).4 Pamięć ta przechowuje ustrukturyzowane wpisy w formacie:

$$Entry \= \\langle Entity, Attitude, Timestamp \\rangle$$

gdzie Entity to obiekt zainteresowania (np. aktorka Scarlett Johansson), Attitude to wyekstrahowana przez LLM postawa użytkownika (np. "Lubi jej role w Sci-Fi, ale nie w dramatach"), a Timestamp pozwala na zarządzanie świeżością danych.  
Zarządzanie tą pamięcią odbywa się poprzez dwa kluczowe procesy:

1. **Refinement (Oczyszczanie):** Po zakończeniu każdej sesji, LLM analizuje przebieg rozmowy i ekstrahuje/aktualizuje kluczowe preferencje, odrzucając szum (np. small talk). Dzięki temu pamięć jest skondensowana i pozbawiona redundancji.4  
2. **Retrieval (Wyszukiwanie Kontekstowe):** W nowej sesji system nie ładuje całej pamięci użytkownika. Używając mechanizmu *Retrieval-Augmented Generation* (RAG), pobiera tylko te wpisy, które są relewantne dla bieżącego tematu. Jeśli użytkownik pyta o komedie, system pobiera preferencje dotyczące komedii, ignorując nieistotne w tym momencie opinie o horrorach.4

#### **4.1.2. Pamięć Ogólna (General Memory \- GM)**

Dla nowych użytkowników (problem *cold-start*) lub w sytuacjach wymagających wiedzy ogólnej, system wykorzystuje Pamięć Ogólną.4 Składa się ona z:

1. **Wiedzy Kolaboratywnej:** Skondensowane wzorce zachowań populacji, pozyskiwane z zewnętrznych modeli eksperckich (np. "Osoby lubiące 'Władcę Pierścieni' często sięgają po 'Hobbita'").  
2. **Wytycznych Rozumowania (Reasoning Guidelines):** Zestaw zasad i heurystyk dla LLM, które sterują procesem wnioskowania (np. strategie zadawania pytań doprecyzowujących). System może samodzielnie aktualizować te wytyczne na podstawie analizy sukcesów i porażek w poprzednich interakcjach.4

### **4.2. Adaptacja i Detekcja Zmian: Mechanizm PAMU**

Preferencje użytkowników nie są statyczne; ewoluują w czasie (tzw. *preference drift*). Aby system mógł się do tego adaptować, implementujemy mechanizm **Preference-Aware Memory Update (PAMU)**.10

PAMU wykorzystuje zaawansowaną analizę szeregów czasowych preferencji:

* **Sliding Window Average (SW):** Monitoruje krótkoterminowe fluktuacje i "chwilowe zachcianki" (średnia z ostatnich $N$ interakcji).  
* **Exponential Moving Average (EMA):** Modeluje długoterminowe, stabilne trendy w guście użytkownika.  
* **Divergence Detection:** System w czasie rzeczywistym oblicza rozbieżność między SW a EMA. Nagły wzrost tej różnicy sygnalizuje zmianę paradygmatu (np. użytkownik nagle przestał oglądać filmy akcji na rzecz dokumentów). W takiej sytuacji system uruchamia procedurę aktualizacji wag w pamięci UM, nadając priorytet nowym sygnałom i potencjalnie inicjując dialog weryfikujący ("Zauważyłem, że ostatnio wybierasz inne filmy, czy zmienić kryteria rekomendacji?").10

Struktura pamięci jest zorganizowana zgodnie z koncepcją **Agentic Memory (A-MEM)**, inspirowaną metodą Zettelkasten. Nowe wspomnienia są automatycznie linkowane do istniejących na podstawie podobieństwa semantycznego, tworząc sieć wiedzy, która ewoluuje wraz z użytkownikiem.13

### **4.3. Zarządzanie Dialogiem i Strategia Decyzyjna (CRIF \+ IRL)**

Moduł zarządzania dialogiem odpowiada za podejmowanie decyzji o kolejnym kroku: czy system powinien zadać pytanie doprecyzowujące (Ask), czy przedstawić rekomendację (Recommend). Zamiast polegać na sztywnych regułach, system wykorzystuje **Inverse Reinforcement Learning (IRL)** zgodnie z frameworkiem CRIF.9

W podejściu tym system "uczy się" funkcji nagrody poprzez obserwację udanych interakcji. Sieć polityki ($\\pi$) optymalizuje swoje działanie tak, aby maksymalizować przewidywaną nagrodę, balansując między eksploracją (zadawaniem pytań w celu zmniejszenia entropii/niepewności) a eksploatacją (prezentowaniem rekomendacji). Dzięki IRL, system naturalnie przyswaja strategie konwersacyjne, np. zadawanie pytań o atrybuty na początku rozmowy i przechodzenie do rekomendacji dopiero po uzyskaniu wystarczającej pewności.9

Dodatkowo, system implementuje zaawansowaną obsługę negatywnego sprzężenia zwrotnego. Gdy rekomendacja zostaje odrzucona, system wykorzystuje wnioskowanie logiczne na podstawie historii sesji (CRIF Inference Module). Jeśli odrzucony przedmiot posiada atrybuty $A, B, C$, a użytkownik wcześniej potwierdził lubienie $A$ i $B$, system wnioskuje, że przyczyną odrzucenia jest prawdopodobnie atrybut $C$. Ta informacja jest natychmiastowo wykorzystywana do aktualizacji wektora preferencji, co pozwala na szybką korektę kursu w tej samej sesji.9

Moduł ten integruje również symulator użytkownika oparty na LLM, który pozwala na trenowanie i walidację strategii dialogowych w środowisku syntetycznym przed wdrożeniem produkcyjnym, co jest kluczowe dla systemów uczących się.2

## ---

**5\. Podsumowanie**

Przedstawiony plan implementacyjny definiuje architekturę CRS nowej generacji, która skutecznie adresuje ograniczenia obecnych rozwiązań.

1. **Faza I** zapewnia precyzyjną kwantyfikację intencji użytkownika, łącząc elastyczność LLM z determinizmem BERT.  
2. **Faza II** gwarantuje semantyczną spójność i wyjaśnialność rekomendacji dzięki jawnemu wnioskowaniu na Grafie Wiedzy i wyrównaniu przestrzeni wektorowych (MIM).  
3. **Faza III** wprowadza pamięć długoterminową i mechanizmy adaptacyjne (MemoCRS, PAMU, IRL), które pozwalają systemowi na ewolucję wraz z użytkownikiem i inteligentne zarządzanie dialogiem.

Taka holistyczna architektura, łącząca percepcję, rozumowanie i pamięć, stanowi solidny fundament dla budowy asystentów AI, które nie tylko przetwarzają zapytania, ale wchodzą w merytoryczną i spersonalizowaną interakcję z człowiekiem.

#### **Cytowane prace**

1. \[RES\] Conversational Recommender Systems based on Extracting Implicit Preferences with Large Language Models.pdf  
2. \[RES\] Leveraging Large Language Models in Conversational Recommender Systems.pdf  
3. Extracting\_Implicit\_User\_Preferences\_in\_Conversational\_Recommender\_Systems\_Using\_LLM.pdf  
4. MemoCRS\_Memory-enhanced\_Sequential\_Conversational\_Recommender\_Systems\_with\_LLM.pdf  
5. \[RES\] extracting\_personal\_info\_from\_conversation.pdf  
6. \[2508.01739\] Enhancing the Preference Extractor in Multi-turn Dialogues: From Annotating Disasters to Accurate Preference Extraction \- arXiv, otwierano: grudnia 28, 2025, [https://arxiv.org/abs/2508.01739](https://arxiv.org/abs/2508.01739)  
7. Enhancing the Preference Extractor in Multi-turn Dialogues: From Annotating Disasters to Accurate Preference Extraction \- ResearchGate, otwierano: grudnia 28, 2025, [https://www.researchgate.net/publication/394293152\_Enhancing\_the\_Preference\_Extractor\_in\_Multi-turn\_Dialogues\_From\_Annotating\_Disasters\_to\_Accurate\_Preference\_Extraction](https://www.researchgate.net/publication/394293152_Enhancing_the_Preference_Extractor_in_Multi-turn_Dialogues_From_Annotating_Disasters_to_Accurate_Preference_Extraction)  
8. \[System\] Explicit Knowledge Graph Reasoning for Conversational Recommendation.pdf  
9. Learning\_to\_Infer\_User\_Implicit\_Preference\_in\_Conversational\_Recommendation.pdf  
10. Preference-Aware Memory Update for Long-Term LLM Agents \- arXiv, otwierano: grudnia 28, 2025, [https://arxiv.org/html/2510.09720v1](https://arxiv.org/html/2510.09720v1)  
11. Preference-Aware Memory Update for Long-Term LLM Agents \- ChatPaper, otwierano: grudnia 28, 2025, [https://chatpaper.com/paper/199021](https://chatpaper.com/paper/199021)  
12. Preference-Aware Memory Update for Long-Term LLM Agents \- arXiv, otwierano: grudnia 28, 2025, [https://arxiv.org/pdf/2510.09720](https://arxiv.org/pdf/2510.09720)  
13. A-Mem: Agentic Memory for LLM Agents | OpenReview, otwierano: grudnia 28, 2025, [https://openreview.net/forum?id=FiM0M8gcct](https://openreview.net/forum?id=FiM0M8gcct)  
14. WujiangXu/A-mem: The code for NeurIPS 2025 paper "A-MEM: Agentic Memory for LLM Agents" \- GitHub, otwierano: grudnia 28, 2025, [https://github.com/WujiangXu/A-mem](https://github.com/WujiangXu/A-mem)