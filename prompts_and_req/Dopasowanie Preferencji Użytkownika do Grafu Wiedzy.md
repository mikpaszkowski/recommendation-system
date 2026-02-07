# **Architektura Semantycznej Zgodności w Konwersacyjnych Systemach Rekomendacyjnych: Kompleksowa Analiza Strategii Mostkowania Luki Między Preferencjami a Grafem Wiedzy**

## **1\. Wstęp: Paradygmat Neuro-Symboliczny w Systemach CRS**

Współczesne systemy rekomendacyjne (Conversational Recommender Systems – CRS) przechodzą obecnie fundamentalną transformację architektoniczną, ewoluując z prostych mechanizmów filtrowania kolaboratywnego w stronę zaawansowanych agentów kognitywnych, zdolnych do prowadzenia wieloetapowych, kontekstowych dialogów z użytkownikiem. Analiza przedstawionego "Planu Implementacji Systemu Rekomendacyjnego" 1 wskazuje na ambitną próbę stworzenia systemu hybrydowego, który integruje generatywne możliwości Dużych Modeli Językowych (LLM) z precyzją wnioskowania na Grafach Wiedzy (Knowledge Graph – KG). Projekt ten słusznie identyfikuje kluczowe fazy rozwoju: od ekstrakcji preferencji, przez ich kwantyfikację za pomocą klasyfikatora BERT, aż po semantyczne wnioskowanie i zarządzanie dialogiem. Jednakże, między etapem ekstrakcji niejawnych preferencji z dialogu a etapem wnioskowania na strukturze grafu, leży krytyczny obszar technologiczny, często określany w literaturze przedmiotu jako „Luka Semantyczna” (Semantic Gap).

Rozwiązanie problemu rozbieżności między „miękkimi”, nieustrukturyzowanymi sygnałami płynącymi z języka naturalnego a „twardymi”, dyskretnymi encjami w bazie danych (w tym przypadku opartej na zbiorze Amazon Reviews 2023\) nie jest trywialnym zadaniem mapowania słów kluczowych. Jest to wyzwanie wielowymiarowe, wymagające zastosowania zaawansowanych technik uczenia reprezentacji (Representation Learning), neuronowego łączenia encji (Neural Entity Linking) oraz alignmentu przestrzeni wektorowych. Błąd na tym etapie propaguje się w dół potoku przetwarzania – nawet najlepiej skalibrowany klasyfikator BERT nie będzie w stanie poprawnie skwantyfikować preferencji, jeśli zostały one błędnie przypisane do nieodpowiednich węzłów w grafie lub jeśli system nie potrafił znaleźć odpowiedników pojęć użytkownika w swojej bazie wiedzy.2

Niniejszy raport stanowi wyczerpującą analizę technologiczną i metodologiczną, mającą na celu dostarczenie konkretnych rekomendacji implementacyjnych dla systemu CRS. Skupiamy się tu na moście łączącym Fazę I (Percepcja) z Fazą II (Wnioskowanie Semantyczne) opisaną w planie.1 Opierając się na najnowszych badaniach z lat 2023–2025, w tym na analizie architektur takich jak KECR (Knowledge Enhanced Conversational Reasoning), ReFinED czy RecLLM, raport ten definiuje, w jaki sposób wykorzystać potencjał zbioru Amazon Reviews 2023 do zbudowania robustnego mechanizmu semantycznego dopasowania. Celem jest przejście od prostego dopasowania leksykalnego do głębokiego zrozumienia intencji, gdzie system rozumie, że zapytanie o „klimatyczny kryminał w stylu skandynawskim” powinno aktywować konkretne klastry w grafie wiedzy, nawet jeśli słowa te nie występują wprost w metadanych produktów.

## **2\. Anatomia Danych i Wyzwania Strukturalne: Amazon Reviews 2023**

Zanim przejdziemy do doboru konkretnych algorytmów, konieczne jest głębokie zrozumienie substratu danych, na którym system będzie operował. Zbiór Amazon Reviews 2023 to jeden z największych i najbardziej złożonych korpusów danych e-commerce dostępnych dla badaczy, co stwarza zarówno unikalne możliwości, jak i specyficzne wyzwania dla procesu Entity Linking i alignmentu.4

### **2.1. Skala i Heterogeniczność Grafu Wiedzy**

Zbiór ten zawiera ponad 571 milionów recenzji, 48 milionów przedmiotów (Items) oraz dziesiątki milionów użytkowników, obejmując interakcje z lat 1996–2023.5 W przeciwieństwie do starszych wersji (2014, 2018), edycja 2023 charakteryzuje się znacznie bogatszymi metadanymi i drobnoziarnistymi znacznikami czasu (na poziomie sekund), co jest kluczowe dla modelowania sekwencyjnego, ale wprowadza też szum informacyjny w procesie budowania statycznego grafu wiedzy.7

Struktura grafu, który musi zostać zbudowany na tych danych, jest z natury heterogeniczna. Węzły nie są jednorodne; reprezentują one fundamentalnie różne byty ontologiczne:

* **Produkty (Items/ASINs):** Centralne węzły grafu, posiadające atrybuty takie jak tytuł, opis, cena, a także bogate cechy multimodalne (obrazy, wideo).6  
* **Kategorie (Categories):** Hierarchiczna struktura taksonomii Amazon (np. Electronics \-\> Computers \-\> Laptops), która jest kluczowa dla generalizacji preferencji.8  
* **Marki (Brands):** Encje grupujące produkty, często będące przedmiotem bezpośrednich zapytań użytkowników.  
* **Użytkownicy (Users):** Węzły reprezentujące historię interakcji, łączące się z produktami poprzez relacje PURCHASED lub REVIEWED.8  
* **Cechy/Aspekty (Fine-grained Features):** To tu leży największe wyzwanie. W nowym zbiorze metadane zawierają pola features (listy punktowane) oraz description 6, które są tekstem nieustrukturyzowanym. Aby graf był użyteczny dla CRS, te opisy muszą zostać przetworzone na węzły cech (np. "Battery Life", "Noise Cancellation"), co wymaga zaawansowanej ekstrakcji informacji (OpenIE) lub wykorzystania LLM do strukturyzacji.9

### **2.2. Problem Rzadkości i "Zimnego Startu" Encji**

Przy skali 48 milionów produktów, graf Amazon Reviews 2023 charakteryzuje się wysokim stopniem rzadkości (sparsity). Większość produktów ma zaledwie kilka interakcji, co sprawia, że metody oparte wyłącznie na strukturze (np. klasyczne Collaborative Filtering czy proste embeddingi węzłów typu Node2Vec) nie będą w stanie wygenerować reprezentatywnych wektorów dla produktów z "długiego ogona" (long-tail items).11 Dla systemu CRS oznacza to, że mechanizm mapowania preferencji nie może polegać wyłącznie na ID produktu. Musi on silnie wykorzystywać **zawartość semantyczną (Content-Based Features)** – tytuły i recenzje. To właśnie w recenzjach użytkownicy wyrażają swoje preferencje językiem naturalnym, który jest najbliższy językowi dialogu. Dlatego też, alignment musi zachodzić na poziomie tekst-tekst (dialog vs. recenzja/opis), a dopiero potem być zakotwiczany w grafie.12

### **2.3. Rozbieżność Słownikowa (Vocabulary Mismatch)**

Fundamentalnym problemem, który system musi rozwiązać, jest dysonans między językiem użytkownika a językiem katalogu.

* **Język Użytkownika:** Jest nieprecyzyjny, emocjonalny, używa skrótów myślowych i pojęć subiektywnych (np. "laptop, który nie zamula", "elegancki zegarek").  
* **Język Katalogu (Amazon Metadata):** Jest techniczny, specyficzny, pełen żargonu i parametrów (np. "Intel Core i7-12700H", "Stainless Steel Bezel").

Tradycyjne metody oparte na dopasowaniu leksykalnym (np. BM25, TF-IDF) czy prostej wyszukiwarce opartej na słowach kluczowych (keyword search) są w tym scenariuszu nieskuteczne. Nie potrafią one połączyć zapytania o "niezamulający laptop" z parametrem "16GB RAM" lub "SSD Drive". Rozwiązanie tego problemu wymaga przejścia na **Dense Retrieval** i semantyczne dopasowanie wektorowe, które jest w stanie uchwycić te ukryte korelacje.14

## **3\. Strategia Rozwiązania: Trójwarstwowa Architektura Semantycznej Integracji**

Aby skutecznie rozwiązać problem rozbieżności w systemie opisanym w 1, rekomenduje się odejście od monolitycznego podejścia na rzecz trójwarstwowej architektury integracji. Każda warstwa adresuje inny aspekt luki semantycznej, tworząc kaskadowy system filtracji i dopasowania.

Tabela 1\. Proponowana architektura trójwarstwowa dla systemu CRS opartego na Amazon Reviews 2023\.

| Warstwa | Nazwa Funkcjonalna | Główny Cel | Kluczowe Technologie | Rola w Planie |
| :---- | :---- | :---- | :---- | :---- |
| **I** | **Semantic Alignment (Wyrównanie)** | Matematyczne zbliżenie przestrzeni wektorowej dialogu i przestrzeni grafu wiedzy. | **MIM (Mutual Information Maximization)**, InfoNCE Loss, Contrastive Learning | Most między Fazą I a II. |
| **II** | **Neural Entity Linking (Identyfikacja)** | Precyzyjne mapowanie wzmianek na węzły (Seed Nodes) w obecności szumu. | **ReFinED**, GENRE, Zero-shot EL | Inicjalizacja wnioskowania grafowego. |
| **III** | **Scalable Retrieval (Wyszukiwanie)** | Szybka selekcja kandydatów z ogromnej przestrzeni (48M items) dla zapytań niejawnych. | **Generalized Dual Encoder (RecLLM)**, FAISS, ANN | Filtr wstępny dla KECR. |

Poniższe sekcje szczegółowo analizują implementację każdej z tych warstw, uzasadniając wybór konkretnych metod w kontekście specyfiki projektu.

## **4\. Warstwa I: Maksymalizacja Informacji Wzajemnej (MIM) – Silnik Semantyczny**

Najbardziej krytycznym elementem, który musi zostać dodany do systemu, aby zrealizować wizję architektury KECR, jest mechanizm **Maksymalizacji Informacji Wzajemnej (MIM)**. Jak wskazują badania nad modelami takimi jak KGSF (Knowledge Graph Semantic Fusion) czy InfoPO, MIM jest najskuteczniejszą metodą matematycznego wyrównania dwóch heterogenicznych przestrzeni danych: tekstu i grafu.16

### **4.1. Teoretyczne Podstawy MIM w Kontekście CRS**

Informacja wzajemna (Mutual Information \- MI) między dwiema zmiennymi losowymi $X$ (reprezentacja dialogu) i $Y$ (reprezentacja encji w grafie) jest miarą redukcji niepewności co do jednej zmiennej, gdy znamy drugą. Formalnie:

$$I(X; Y) \= \\sum\_{x \\in X} \\sum\_{y \\in Y} p(x, y) \\log \\left( \\frac{p(x, y)}{p(x)p(y)} \\right)$$  
W kontekście systemu rekomendacyjnego, celem jest wytrenowanie enkoderów w taki sposób, aby maksymalizować tę wartość. Oznacza to, że system, widząc wektor reprezentujący zdanie użytkownika "szukam czegoś do grania w 4K", powinien z maksymalnym prawdopodobieństwem wskazywać na wektory reprezentujące monitory 4K lub karty graficzne w grafie wiedzy, a z minimalnym na inne produkty.19 Jest to podejście znacznie bardziej robustne niż prosta minimalizacja błędu średniokwadratowego (MSE), ponieważ operuje na rozkładach prawdopodobieństwa i relacjach, a nie tylko na punktach.

### **4.2. Implementacja poprzez Contrastive Learning (InfoNCE)**

Bezpośrednie obliczenie MI jest w wysokowymiarowych przestrzeniach sieci neuronowych niewykonalne obliczeniowo. Dlatego w praktyce implementacyjnej należy wykorzystać estymatory oparte na **Contrastive Learning**, a konkretnie funkcję straty **InfoNCE** (Noise Contrastive Estimation). Jest to standard przemysłowy w nowoczesnych systemach NLP i RecSys.21

Rekomendowana funkcja celu dla Twojego systemu powinna wyglądać następująco:

$$\\mathcal{L}\_{InfoNCE} \= \- \\mathbb{E} \\left\[ \\log \\frac{\\exp(\\text{sim}(h\_{dialog}, h\_{entity}) / \\tau)}{\\sum\_{h\_{neg} \\in \\mathcal{N}} \\exp(\\text{sim}(h\_{dialog}, h\_{neg}) / \\tau)} \\right\]$$  
Gdzie:

* $h\_{dialog}$: Embedding fragmentu dialogu lub wyekstrahowanej preferencji, uzyskany z modelu językowego (np. BERT, o którym mowa w planie 1).  
* $h\_{entity}$: Embedding pozytywnej encji z grafu (np. produktu, który użytkownik ostatecznie kupił lub ocenił pozytywnie), uzyskany z sieci grafowej (GNN).  
* $\\mathcal{N}$: Zbiór negatywnych próbek (negative samples) – encji, które nie pasują do kontekstu. Dobór odpowiednich negatywów (Hard Negative Mining) jest kluczowy dla skuteczności modelu.  
* $\\tau$: Parametr temperatury, który kontroluje "ostrość" rozkładu.

### **4.3. Architektura Enkoderów: Integracja BERT i R-GCN**

Aby mechanizm MIM zadziałał, musisz zdefiniować, skąd pochodzą wektory $h$.

* **Enkoder Tekstu:** Plan zakłada użycie BERTa do kwantyfikacji. Ten sam model (lub jego wariant, np. Sentence-BERT) powinien służyć jako enkoder semantyczny dla MIM. Pozwoli to na wykorzystanie wiedzy językowej modelu do interpretacji niuansów.1  
* **Enkoder Grafu:** Tutaj kluczowe jest wykorzystanie **Relational Graph Convolutional Networks (R-GCN)**. Zwykłe GCN traktują wszystkie krawędzie tak samo. W grafie Amazon Reviews relacje są różnorodne (also\_bought, is\_category, brand\_of). R-GCN uczy się oddzielnych wag transformacji dla każdego typu relacji, co pozwala na stworzenie znacznie bogatszych reprezentacji encji.20 Embedding produktu wygenerowany przez R-GCN będzie zawierał w sobie "wiedzę" o jego sąsiedztwie – np. że jest to produkt marki Sony, powiązany z konsolami PlayStation.

Wdrożenie MIM polega na wspólnym trenowaniu (joint training) obu tych enkoderów na danych historycznych (pary: recenzja/dialog – zakupiony produkt), tak aby ich wyjścia były zalineowane w tej samej przestrzeni metrycznej.25

## **5\. Warstwa II: Neural Entity Linking (NEL) – Precyzyjna Identyfikacja**

MIM zapewnia ogólną zgodność semantyczną, ale system CRS potrzebuje również mechanizmu do "twardego" mapowania konkretnych nazw i fraz pojawiających się w dialogu na węzły w grafie. Jest to proces identyfikacji tzw. **Seed Nodes**, od których rozpoczyna się eksploracja grafu w algorytmie KECR.1

### **5.1. Specyfika Entity Linking w E-commerce**

Tradycyjne systemy Entity Linking (EL), trenowane na Wikipedii (jak DBpedia Spotlight), są nieskuteczne w domenie e-commerce. Powody są proste:

1. **Nazewnictwo:** Produkty mają skomplikowane nazwy ("Samsung Galaxy S23 Ultra 5G 256GB"), a użytkownicy używają skrótów ("S23").  
2. **Ambiwalencja:** Słowo "Apple" w Wikipedii to owoc lub firma. W Amazon Reviews to marka elektroniki, ale może też wystąpić w kontekście "apple slicer" (kategoria Kitchen).  
3. **Cold Start:** Codziennie pojawiają się nowe produkty, których nie było w zbiorze treningowym modelu.

### **5.2. Rekomendacja Technologiczna: ReFinED**

Dla Twojego systemu, opartego na danych Amazon, najpotężniejszym rozwiązaniem będzie model **ReFinED** (Retrieval-and-Fine-tuning for Entity Disambiguation), opracowany przez Amazon Science.27

**Dlaczego ReFinED?**

* **Architektura End-to-End:** W przeciwieństwie do klasycznych potoków (detekcja \-\> generowanie kandydatów \-\> ranking), ReFinED wykonuje wszystko w jednym przebiegu przez Transformer. Jest to kluczowe dla zachowania niskiej latencji w systemie konwersacyjnym.27  
* **Zero-Shot Capability:** ReFinED nie uczy się "na pamięć" identyfikatorów encji. Zamiast tego, uczy się dopasowywać wzmianki do **opisów teksturowych** encji i ich typów. Dzięki temu, gdy w bazie pojawi się nowy produkt (który ma opis i kategorię), system będzie w stanie go zlinkować bez konieczności re-treningu modelu. Jest to krytyczna cecha w dynamicznym środowisku e-commerce.27  
* **Efektywność:** Model ten jest zoptymalizowany pod kątem skalowalności, co jest niezbędne przy pracy z grafem zawierającym 48 milionów węzłów.

### **5.3. Alternatywa Generatywna: GENRE**

Jako alternatywę lub uzupełnienie warto rozważyć **GENRE** (Generative ENtity REtrieval). Jest to podejście, w którym model sequence-to-sequence (np. BART) generuje unikalną nazwę encji token po tokenie, zamiast wybierać ją z listy.30 GENRE sprawdza się doskonale, gdy nazwy encji mają strukturę semantyczną (co jest częste w nazwach produktów, np. Marka \+ Model \+ Wariant). Pozwala to na uniknięcie przechowywania gigantycznych indeksów wszystkich możliwych encji w pamięci, co przy 48 milionach produktów może być wąskim gardłem.

### **5.4. Query Rewriting i Normalizacja**

Przed przekazaniem tekstu do modułu EL, warto zastosować moduł **Query Rewriting** oparty na LLM. Jego zadaniem jest przekształcenie potocznego zapytania użytkownika w formę bardziej kanoniczną, zbliżoną do atrybutów w KG. Na przykład, zapytanie "coś na komary do kontaktu" może zostać przepisane na "elektryczny odstraszacz komarów wkładany do gniazdka", co znacznie ułatwia pracę modelowi ReFinED i zwiększa precyzję mapowania.31

## **6\. Warstwa III: Generalized Dual Encoder (RecLLM) – Skalowalność Wnioskowania**

Nawet przy najlepszym alignmencie i entity linkingu, bezpośrednie przeszukiwanie grafu dla każdego zapytania w czasie rzeczywistym jest niemożliwe przy skali Amazon Reviews 2023\. Plan implementacji słusznie wspomina o **Generalized Dual Encoder** jako mechanizmie retrievalu.1 Należy go potraktować jako "wstępny filtr" (coarse filter), który zawęża przestrzeń poszukiwań dla właściwego silnika wnioskującego KECR.

### **6.1. Architektura Dwururowa (Two-Tower Model)**

W tym podejściu trenujemy dwie niezależne sieci neuronowe (wieże):

1. **Context Tower (User Tower):** Przetwarza historię dialogu, bieżące zapytanie oraz wyekstrahowane preferencje (output z Fazy I), generując wektor zapytania $q$.  
2. **Item Tower:** Przetwarza zagregowane metadane produktu (tytuł, opis, średnia ocena, atrybuty z KG) i generuje wektor przedmiotu $i$. Ważne jest, aby wejście do Item Tower było wzbogacone o embeddingi grafowe z R-GCN (z Warstwy I), co pozwala na "przemycenie" informacji strukturalnej do procesu prostego retrievalu.3

Model jest trenowany tak, aby iloczyn skalarny (dot product) $q \\cdot i$ był wysoki dla par (użytkownik, relewantny przedmiot) i niski dla pozostałych.32

### **6.2. Indeksowanie ANN (FAISS)**

Kluczem do wydajności jest tutaj wykorzystanie biblioteki **FAISS** (Facebook AI Similarity Search).33 Pozwala ona na zaindeksowanie milionów wektorów produktów i wykonywanie przybliżonego wyszukiwania najbliższych sąsiadów (Approximate Nearest Neighbor \- ANN) w czasie rzędu milisekund.

* **Strategia:** Context Tower generuje wektor $q$. FAISS zwraca np. top-1000 kandydatów. Dopiero ten zredukowany zbiór jest przekazywany do cięższego obliczeniowo modułu wnioskowania grafowego (Graph Reasoning Module), który analizuje ścieżki i relacje, aby wybrać ostateczne top-5 rekomendacji.

## **7\. Walidacja i Weryfikacja Spójności (Consistency & Grounding)**

Ostatnim, ale nie mniej ważnym elementem rozwiązania problemu rozbieżności, jest weryfikacja poprawności. Systemy generatywne mają tendencję do halucynacji – mogą wymyślić atrybut produktu, który nie istnieje.

### **7.1. Schema-Constraint Generation**

Podczas ekstrakcji preferencji w Fazie I, LLM nie powinien generować dowolnego tekstu. Należy zastosować techniki **Constrained Decoding** (np. przy użyciu bibliotek takich jak guidance lub LMQL), które wymuszają na modelu generowanie wyjścia (np. JSON) zgodnego ze schematem (ontologią) grafu Amazon Reviews. Jeśli graf zawiera atrybut screen\_size, model nie powinien wygenerować atrybutu display\_dimension, lecz zmapować go na dozwolony token.35

### **7.2. Weryfikacja Ścieżek (Reasoning Chains)**

Siłą architektury KECR jest to, że rekomendacja nie jest "czarną skrzynką". System generuje ścieżkę w grafie: User \-\> Liked(Movie A) \-\> Director(X) \-\> Directed(Movie B). Przed przedstawieniem rekomendacji użytkownikowi, system musi zweryfikować istnienie tej ścieżki w grafie. Jest to naturalny mechanizm "Fact-Checking". Jeśli ścieżka nie istnieje (np. reżyser X nie nakręcił filmu B), rekomendacja powinna zostać odrzucona, nawet jeśli wskaźnik podobieństwa wektorowego był wysoki.1

## **8\. Szczegółowy Plan Działań Implementacyjnych**

W oparciu o powyższą analizę, oto konkretna lista kroków, które należy podjąć, aby zintegrować te rozwiązania z Twoim systemem:

1. **Przygotowanie Grafu (Graph Construction):**  
   * Użyj **PyTorch Geometric** do zbudowania heterogenicznego grafu na bazie Amazon Reviews 2023\.  
   * Węzły: User, Item, Brand, Category, Feature (z opisów).  
   * Krawędzie: Purchase, Review, Also\_Viewed, Also\_Bought (kluczowe dla collaborative filtering).  
2. **Trening Enkoderów (Pre-training with MIM):**  
   * Zaimplementuj pętlę treningową **Contrastive Learning** używając biblioteki info-nce-pytorch.  
   * Trenuj BERTa (tekst) i R-GCN (graf) tak, aby maksymalizować zgodność między tekstem recenzji a reprezentacją produktu. To jest fundament Twojego alignmentu.  
3. **Wdrożenie Entity Linking:**  
   * Zintegruj model **ReFinED** (dostępny jako open-source) do przetwarzania surowego dialogu.  
   * Skonfiguruj go do pracy w trybie zero-shot, wykorzystując opisy produktów z metadanych Amazon jako kontekst dla linkowania.  
4. **Budowa Indeksu Retrieval:**  
   * Wytrenuj prosty model Two-Tower (Context \+ Item) zasilany embeddingami z kroku 2\.  
   * Zaindeksuj wszystkie 48M produktów w **FAISS** (użyj indeksu HNSW dla balansu między szybkością a precyzją).  
5. **Integracja z Modułem Kwantyfikacji (BERT):**  
   * Dopiero teraz, gdy masz pewność, że preferencje są poprawnie zmapowane na encje grafu, przekaż je do klasyfikatora BERT opisanego w Twoim planie. Jego zadaniem będzie przypisanie wag (prawdopodobieństw) do tych zweryfikowanych encji/kategorii, co steruje ostatecznym rankingiem.

## **9\. Podsumowanie**

Rozwiązanie problemu rozbieżności między preferencjami użytkownika a encjami w grafie w systemie opartym na tak ogromnym zbiorze jak Amazon Reviews 2023 wymaga odejścia od prostych metod. Kluczem jest **semantyczna płynność** zapewniana przez MIM oraz **precyzja strukturalna** zapewniana przez ReFinED i R-GCN.

Zastosowanie proponowanej architektury – **MIM \+ ReFinED \+ Dual Encoder** – pozwoli Twojemu systemowi nie tylko "znaleźć produkt", ale "zrozumieć potrzebę" użytkownika i przełożyć ją na język grafu wiedzy. Jest to niezbędny krok, aby przejść do kolejnych faz planu, takich jak zaawansowane zarządzanie dialogiem i personalizacja oparta na pamięci długoterminowej. Taka konfiguracja technologiczna zapewnia skalowalność, odporność na błędy językowe użytkowników oraz wysoką jakość i wyjaśnialność rekomendacji.

#### **Cytowane prace**

1. Plan Implementacji Systemu Rekomendacyjnego  
2. STEP: Stepwise Curriculum Learning for Context-Knowledge Fusion in Conversational Recommendation \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/html/2508.10669v1](https://arxiv.org/html/2508.10669v1)  
3. Representation Learning with Large Language Models for Recommendation \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/html/2310.15950v5](https://arxiv.org/html/2310.15950v5)  
4. Personalized Graph-Based Retrieval for Large Language Models \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/html/2501.02157v1](https://arxiv.org/html/2501.02157v1)  
5. McAuley-Lab/Amazon-Reviews-2023 · Datasets at Hugging Face, otwierano: stycznia 11, 2026, [https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023)  
6. Amazon Reviews'23, otwierano: stycznia 11, 2026, [https://amazon-reviews-2023.github.io/](https://amazon-reviews-2023.github.io/)  
7. Bridging Language and Items for Retrieval and Recommendation \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/html/2403.03952v1](https://arxiv.org/html/2403.03952v1)  
8. Budowa Knowledge Graphu dla Rekomendacji.md  
9. Enhancing Knowledge Graph Extraction and Validation From Scholarly Publications Using Bibliographic Metadata \- PMC \- PubMed Central, otwierano: stycznia 11, 2026, [https://pmc.ncbi.nlm.nih.gov/articles/PMC8194279/](https://pmc.ncbi.nlm.nih.gov/articles/PMC8194279/)  
10. Generative Model Using Knowledge Graph for Document-Grounded Conversations \- MDPI, otwierano: stycznia 11, 2026, [https://www.mdpi.com/2076-3417/12/7/3367](https://www.mdpi.com/2076-3417/12/7/3367)  
11. Amazon 2023 Review Dataset \- Emergent Mind, otwierano: stycznia 11, 2026, [https://www.emergentmind.com/topics/amazon-2023-review-dataset](https://www.emergentmind.com/topics/amazon-2023-review-dataset)  
12. (PDF) Sentiment-Aware Recommendation Systems in E-Commerce: A Review from a Natural Language Processing Perspective \- ResearchGate, otwierano: stycznia 11, 2026, [https://www.researchgate.net/publication/391530713\_Sentiment-Aware\_Recommendation\_Systems\_in\_E-Commerce\_A\_Review\_from\_a\_Natural\_Language\_Processing\_Perspective](https://www.researchgate.net/publication/391530713_Sentiment-Aware_Recommendation_Systems_in_E-Commerce_A_Review_from_a_Natural_Language_Processing_Perspective)  
13. (PDF) Transformer and Pre-Transformer Model-Based Sentiment Prediction with Various Embeddings: A Case Study on Amazon Reviews \- ResearchGate, otwierano: stycznia 11, 2026, [https://www.researchgate.net/publication/398044762\_Transformer\_and\_Pre-Transformer\_Model-Based\_Sentiment\_Prediction\_with\_Various\_Embeddings\_A\_Case\_Study\_on\_Amazon\_Reviews](https://www.researchgate.net/publication/398044762_Transformer_and_Pre-Transformer_Model-Based_Sentiment_Prediction_with_Various_Embeddings_A_Case_Study_on_Amazon_Reviews)  
14. What is the difference between sparse and dense retrieval? \- Milvus, otwierano: stycznia 11, 2026, [https://milvus.io/ai-quick-reference/what-is-the-difference-between-sparse-and-dense-retrieval](https://milvus.io/ai-quick-reference/what-is-the-difference-between-sparse-and-dense-retrieval)  
15. MiniCOIL: Bridging Sparse Lexical and Semantic Retrieval | by Utkarsh Mittal \- Towards AI, otwierano: stycznia 11, 2026, [https://pub.towardsai.net/minicoil-bridging-sparse-lexical-and-semantic-retrieval-9c313666e602](https://pub.towardsai.net/minicoil-bridging-sparse-lexical-and-semantic-retrieval-9c313666e602)  
16. \[2305.00783\] Explicit Knowledge Graph Reasoning for Conversational Recommendation \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/abs/2305.00783](https://arxiv.org/abs/2305.00783)  
17. \[2007.04032\] Improving Conversational Recommender Systems via Knowledge Graph based Semantic Fusion \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/abs/2007.04032](https://arxiv.org/abs/2007.04032)  
18. InfoPO: On Mutual Information Maximization for Large Language Model Alignment \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/html/2505.08507v1](https://arxiv.org/html/2505.08507v1)  
19. Mutual information estimation for graph convolutional neural networks \- ResearchGate, otwierano: stycznia 11, 2026, [https://www.researchgate.net/publication/359646901\_Mutual\_information\_estimation\_for\_graph\_convolutional\_neural\_networks](https://www.researchgate.net/publication/359646901_Mutual_information_estimation_for_graph_convolutional_neural_networks)  
20. MIA: Mutual Information Alignment for Side Information-Enhanced Recommendation with Multiple Views \- eScholarship@McGill, otwierano: stycznia 11, 2026, [https://escholarship.mcgill.ca/downloads/sj139694g](https://escholarship.mcgill.ca/downloads/sj139694g)  
21. PyTorch implementation of the InfoNCE loss for self-supervised learning. \- GitHub, otwierano: stycznia 11, 2026, [https://github.com/RElbers/info-nce-pytorch](https://github.com/RElbers/info-nce-pytorch)  
22. PyG-SSL: A Graph Self-Supervised Learning Toolkit \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/html/2412.21151v1](https://arxiv.org/html/2412.21151v1)  
23. megagonlabs/ditto: Code for the paper "Deep Entity Matching with Pre-trained Language Models" \- GitHub, otwierano: stycznia 11, 2026, [https://github.com/megagonlabs/ditto](https://github.com/megagonlabs/ditto)  
24. Study on a User Preference Conversational Recommender Based on a Knowledge Graph, otwierano: stycznia 11, 2026, [https://www.mdpi.com/2079-9292/14/3/632](https://www.mdpi.com/2079-9292/14/3/632)  
25. A Mutual Information Perspective on Knowledge Graph Embedding \- ACL Anthology, otwierano: stycznia 11, 2026, [https://aclanthology.org/2025.acl-long.1077.pdf](https://aclanthology.org/2025.acl-long.1077.pdf)  
26. Paper List for Recommend-system PreTrained Models \- GitHub, otwierano: stycznia 11, 2026, [https://github.com/archersama/awesome-recommend-system-pretraining-papers](https://github.com/archersama/awesome-recommend-system-pretraining-papers)  
27. Improving “entity linking” between texts and knowledge bases \- Amazon Science, otwierano: stycznia 11, 2026, [https://www.amazon.science/blog/improving-entity-linking-between-texts-and-knowledge-bases](https://www.amazon.science/blog/improving-entity-linking-between-texts-and-knowledge-bases)  
28. mReFinED: An Efficient End-to-End Multilingual Entity Linking System \- GitHub, otwierano: stycznia 11, 2026, [https://github.com/mrpeerat/mReFinED](https://github.com/mrpeerat/mReFinED)  
29. amazon-science/ReFinED: ReFinED is an efficient and accurate entity linking (EL) system., otwierano: stycznia 11, 2026, [https://github.com/amazon-science/ReFinED](https://github.com/amazon-science/ReFinED)  
30. AUTOREGRESSIVE ENTITY RETRIEVAL \- OpenReview, otwierano: stycznia 11, 2026, [https://openreview.net/pdf?id=5k8F6UU39V](https://openreview.net/pdf?id=5k8F6UU39V)  
31. Advancing query rewriting in e-commerce via shopping intent learning \- Amazon Science, otwierano: stycznia 11, 2026, [https://www.amazon.science/publications/advancing-query-rewriting-in-e-commerce-via-shopping-intent-learning](https://www.amazon.science/publications/advancing-query-rewriting-in-e-commerce-via-shopping-intent-learning)  
32. Leveraging Large Language Models in Conversational Recommender Systems \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/pdf/2305.07961](https://arxiv.org/pdf/2305.07961)  
33. Similarity Search with FAISS: A Practical Guide to Efficient Indexing and Retrieval \- Medium, otwierano: stycznia 11, 2026, [https://medium.com/@devbytes/similarity-search-with-faiss-a-practical-guide-to-efficient-indexing-and-retrieval-e99dd0e55e8c](https://medium.com/@devbytes/similarity-search-with-faiss-a-practical-guide-to-efficient-indexing-and-retrieval-e99dd0e55e8c)  
34. Welcome to Faiss Documentation — Faiss documentation, otwierano: stycznia 11, 2026, [https://faiss.ai/](https://faiss.ai/)  
35. Knowledge Graphs with LLMs: Optimizing Decision-Making \- Addepto, otwierano: stycznia 11, 2026, [https://addepto.com/blog/leveraging-knowledge-graphs-with-llms-a-business-guide-to-enhanced-decision-making/](https://addepto.com/blog/leveraging-knowledge-graphs-with-llms-a-business-guide-to-enhanced-decision-making/)  
36. \[2411.14459\] Reasoning over User Preferences: Knowledge Graph-Augmented LLMs for Explainable Conversational Recommendations \- arXiv, otwierano: stycznia 11, 2026, [https://arxiv.org/abs/2411.14459](https://arxiv.org/abs/2411.14459)