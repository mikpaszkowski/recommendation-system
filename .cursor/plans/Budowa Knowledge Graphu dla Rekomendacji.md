# **Plan Implementacyjny Budowy Grafu Wiedzy i Systemu Rekomendacyjnego na Podstawie Zbioru Danych Amazon Reviews '23**

## **Wprowadzenie: Architektura "Trój-Modalnego" Grafu Wiedzy**

Budowa grafu wiedzy (Knowledge Graph, KG) na potrzeby nowoczesnych systemów rekomendacyjnych ze zbioru danych Amazon Reviews '23 1 jest procesem wykraczającym poza prostą replikację schematu relacyjnego. Aby stworzyć system, który nie tylko rekomenduje, ale także *rozumie* preferencje użytkownika i potrafi *wyjaśnić* swoje decyzje, konieczne jest wdrożenie architektury "trój-modalnej".

Niniejszy plan implementacyjny przedstawia strategię budowy ujednoliconego, heterogenicznego grafu, składającego się z trzech komplementarnych warstw, zintegrowanych w jednej bazie danych grafowej (np. Neo4j):

1. **Warstwa 1: Graf Strukturalny i Kolaboracyjny.** Ta warstwa stanowi fundament i jest budowana bezpośrednio z jawnych metadanych (ETL). Odpowiada na pytania: "Kto co kupił?", "Jakie są atrybuty produktów?" oraz "Co jest kupowane razem?". Jest to szkielet kolaboracyjny i oparty na treści.  
2. **Warstwa 2: Graf Preferencji Semantycznych.** Ta warstwa jest budowana poprzez inferencję z danych nieustrukturyzowanych (NLP/IE), a konkretnie z tekstu recenzji. Odpowiada na kluczowe pytanie: "*Dlaczego* użytkownicy kupują (lub nie kupują) określone produkty?". Modeluje ona ukryte gusta i preferencje.  
3. **Warstwa 3: Graf Leksykalny (GraphRAG).** Ta warstwa łączy surowy tekst z encjami w grafie. Odpowiada na pytania: "*Gdzie* w tekście znajdują się dowody na te preferencje?" oraz "Jak model językowy (LLM) może uzyskać dostęp do tej wiedzy w celu prowadzenia konwersacji?".

Wizja końcowa zakłada stworzenie jednego, spójnego grafu, który pozwala na jednoczesne trenowanie zaawansowanych Grafowych Sieci Neuronowych (GNN) na Warstwach 1 i 2 w celu generowania embeddingów dla rekomendacji, oraz na uruchamianie zapytań typu GraphRAG (Retrieval-Augmented Generation) na Warstwach 1 i 3 w celu zasilania konwersacyjnych, wyjaśnialnych systemów rekomendacyjnych (CRS).

## **Część 1: Fundament Grafu – Przetwarzanie i Modelowanie Danych Rdzeniowych (ETL)**

Ta faza koncentruje się wyłącznie na transformacji jawnych, (pół)ustrukturyzowanych danych ze zbioru Amazon Reviews '23 w stabilny szkielet grafu wiedzy. Jest to klasyczny proces Extract, Transform, Load (ETL) dostosowany do modelu grafowego.

### **1.1. Analiza Schematu Danych Źródłowych Amazon '23**

Punktem wyjścia jest szczegółowa analiza pól dostępnych w zbiorze danych 1:

* **Dane Użytkowników i Recenzji:** user\_id, timestamp (unix time), verified\_purchase (boolean), helpful\_vote (integer), text (przetwarzane w Części 2).  
* **Dane Produktów (Warianty):** asin (ID produktu/wariantu), price.  
* **Metadane Produktów (Rodzice):** parent\_asin (ID produktu nadrzędnego), title (nazwa), features (lista), description (lista), bought\_together (lista parent\_asin).  
* **Pół-ustrukturyzowane Metadane:** categories (lista hierarchiczna), details (słownik klucz-wartość, np. marka, materiał, rozmiar).2

### **1.2. Krytyczne Rozróżnienie: Product (asin) vs. ParentProduct (parent\_asin)**

Kluczowym wyzwaniem i jednocześnie fundamentalną decyzją projektową jest poprawne zamodelowanie rozróżnienia między asin a parent\_asin. Dokumentacja 1 wyraźnie wskazuje: "Products with different colors, styles, sizes usually belong to the same parent ID" oraz "Please use parent ID to find product meta".

Oznacza to, że:

1. Użytkownik (User) pisze recenzję (Review) o konkretnym wariancie, który kupił (np. "czerwone buty, rozmiar 42"), identyfikowanym przez asin.  
2. Jednakże wszystkie bogate metadane – takie jak bought\_together, categories i details (w tym marka) – są powiązane z produktem *nadrzędnym*, identyfikowanym przez parent\_asin (np. "model butów XYZ").

Błędne zamodelowanie, polegające na przypisaniu bought\_together bezpośrednio do asin, doprowadziłoby do utraty sygnału kolaboracyjnego i błędnych rekomendacji. Dlatego schemat grafu musi jawnie rozdzielić te dwie koncepcje i połączyć je relacją IS\_VARIANT\_OF. System rekomendacyjny będzie wówczas polecał ParentProduct, pozostawiając użytkownikowi wybór wariantu (koloru, rozmiaru).

### **1.3. Definiowanie Schematu Grafu (Węzły, Właściwości i Relacje)**

Na podstawie powyższej analizy definiuje się następujący schemat docelowy dla bazy danych grafowej.

**Tabela 1: Definicja Schematu Węzłów Rdzeniowych**

| Etykieta Węzła | Opis | Kluczowe Właściwości | Źródło Danych (Pole Amazon '23) |
| :---- | :---- | :---- | :---- |
| User | Recenzent/Użytkownik | userId: STRING (unikalny) | user\_id |
| Product | Konkretny wariant produktu | asin: STRING (unikalny), price: FLOAT | asin, price (z metadanych produktu) |
| ParentProduct | Ogólny koncept/model produktu | parentAsin: STRING (unikalny), title: STRING | parent\_asin, title (z metadanych rodzica) |
| Review | Recenzja napisana przez użytkownika | reviewId: STRING (generowany\*), timestamp: DATETIME, verified: BOOLEAN, helpfulVotes: INTEGER | user\_id \+ asin \+ timestamp, timestamp, verified\_purchase, helpful\_vote |
| Category | Kategoria produktu | name: STRING (unikalny) | categories (lista) |
| Brand | Marka produktu | name: STRING (unikalny) | details |
| Attribute | Generyczny atrybut produktu | name: STRING, value: STRING | details (pozostałe klucze-wartości) |

\* reviewId można wygenerować jako hash z user\_id, asin i timestamp, aby zapewnić unikalność.

**Tabela 2: Definicja Schematu Relacji Jawnych**

| Węzeł Startowy | Typ Relacji | Węzeł Końcowy | Właściwości Relacji | Źródło / Logika Biznesowa |
| :---- | :---- | :---- | :---- | :---- |
| User | WROTE | Review | Brak | Powiązanie autora z recenzją. |
| Review | ABOUT\_PRODUCT | Product | Brak | Powiązanie recenzji z kupionym wariantem (asin). |
| Product | IS\_VARIANT\_OF | ParentProduct | Brak | Kluczowe powiązanie asin z parent\_asin. |
| ParentProduct | BOUGHT\_TOGETHER | ParentProduct | Brak | Z listy bought\_together (łączenie parent\_asin). |
| ParentProduct | HAS\_BRAND | Brand | Brak | Ze słownika details. |
| ParentProduct | HAS\_ATTRIBUTE | Attribute | Brak | Ze słownika details (un-pivot). |
| ParentProduct | IN\_CATEGORY | Category | Brak | Relacja do najniższej (leaf) kategorii z listy categories. |
| Category | CHILD\_OF | Category | Brak | Modelowanie hierarchii z listy categories.5 |

### **1.4. Przewodnik Implementacyjny ETL**

Import tak dużego zbioru danych do Neo4j wymaga przetwarzania wsadowego. Użycie pojedynczych transakcji CREATE dla każdego wiersza jest niewydajne.6

* **Narzędzia:** pandas (do wczytania i wstępnego przetworzenia plików Parquet 7 lub JSON), neo4j-driver (oficjalny sterownik Pythona).  
* **Krok 1: Wczytanie Danych:** Wczytanie plików recenzji i metadanych do pandas.DataFrame.  
* **Krok 2: Import Węzłów (Cypher):** Użycie UNWIND $rows AS row MERGE (n:Label {id: row.id}) SET n \+= row.properties. Operacja MERGE zapewnia idempotentność i unikanie duplikatów. Dane są przekazywane jako parametr $rows (lista słowników).  
* **Krok 3: Import Relacji (Cypher):** Użycie UNWIND $relations AS r MATCH (a:LabelA {id: r.source}), (b:LabelB {id: r.target}) MERGE (a)--\>(b).  
* **Krok 4: Przetwarzanie Pół-Strukturalne (details i categories):**  
  * Słownik details 2: Wymaga logiki "un-pivot" zaimplementowanej w Pythonie przed importem. Należy iterować po słowniku details dla każdego produktu. Jeśli klucz to 'Brand', generuj relację HAS\_BRAND. Dla pozostałych kluczy (np. 'Material', 'Size') generuj węzły :Attribute i relacje HAS\_ATTRIBUTE.5  
  * Lista categories 2: Wymaga przetworzenia hierarchii.5 Dla listy \['Electronics', 'Computers', 'Laptops'\]:  
    1. Utwórz relację (ParentProduct)--\>(Category {name: 'Laptops'}).  
    2. Utwórz relacje hierarchiczne: MERGE (c1:Category {name: 'Electronics'}), MERGE (c2:Category {name: 'Computers'}) MERGE (c2)--\>(c1), MERGE (c3:Category {name: 'Laptops'}) MERGE (c3)--\>(c2).

## **Część 2: Wzbogacanie Grafu z Danych Niestrukturalnych – Ekstrakcja Wiedzy z Recenzji (IE i NLP)**

Ta sekcja opisuje transformację pola review.text 1 – danych nieustrukturyzowanych – w ustrukturyzowane, semantyczne relacje preferencji. Jest to klucz do zrozumienia *dlaczego* użytkownicy dokonują zakupów i co jest dla nich ważne.

### **2.1. Cel: Ekstrakcja Trójek (Aspekt, Opinia, Sentyment)**

Celem jest przekształcenie surowych recenzji w trójki semantyczne. Proces ten jest znany jako Aspect Sentiment Triplet Extraction (ASTE).8

* **Tekst Wejściowy:** "Bateria jest świetna, ale ekran jest zbyt ciemny."  
* **Wynik Docelowy (Trójki):** \[('bateria', 'świetna', 'Positive'), ('ekran', 'zbyt ciemny', 'Negative')\]

### **2.2. Krok 1: Wybór i Implementacja Potoku ABSA (Aspect-Based Sentiment Analysis)**

Do realizacji zadania ASTE dostępne są gotowe, zaawansowane biblioteki.

* **Opcje:**  
  1. **PyABSA:** Dedykowana, wysokowydajna biblioteka open-source zaprojektowana specjalnie do zadań ABSA, w tym ASTE.8 Oferuje wytrenowane modele, które można zastosować bezpośrednio.  
  2. **Hugging Face Transformers:** Użycie modeli dostrojonych do ABSA (np. yangheng/deberta-v3-base-absa-v1.1 11) lub frameworków takich jak SetFitABSA.12  
  3. **Podejścia Regułowe (np. spaCy):** Użycie parsowania zależności w spaCy do znalezienia par rzeczownik-przymiotnik (aspekt-opinia).14 Jest to szybsze, ale znacznie mniej dokładne i kruche.  
* **Zalecenie:** Zdecydowanie zaleca się użycie **PyABSA** ze względu na dojrzałość, wydajność i bezpośrednie wsparcie dla ekstrakcji trójek (ASTE).8  
* **Proces Implementacyjny (Python/PyABSA):**  
  1. Zainicjuj predyktor ASTE z PyABSA.  
  2. Pobierz pole text oraz reviewId z bazy danych (np. z DataFrame recenzji).  
  3. Przetwarzaj teksty w dużych partiach (batches) za pomocą funkcji batch\_predict.15  
  4. Wyniki (listy trójek) zmapuj z powrotem do reviewId, aby przygotować je do importu do grafu.

**Tabela 3: Wyniki Działania Potoku ABSA (Przykład Transformacji)**

| ID Recenzji | Tekst Wejściowy (skrócony) | Wynikowe Trójki (ASTE) |
| :---- | :---- | :---- |
| R123 | "The camera is amazing, but the battery drains fast." | \[('camera', 'amazing', 'Positive'), ('battery', 'drains fast', 'Negative')\] |
| R456 | "Great service, terrible food. The location was convenient." | \[('service', 'Great', 'Positive'), ('food', 'terrible', 'Negative'), ('location', 'convenient', 'Positive')\] |
| R789 | "I really liked the narrative style of the show." 16 | \[('narrative style', 'liked', 'Positive')\] |

### **2.3. Krok 2: Modelowanie i Normalizacja Wyinferowanej Wiedzy**

Przechowywanie surowych trójek w grafie jest nieefektywne. Należy je znormalizować.

* **Problem:** Model ABSA zwróci wiele wariantów tego samego aspektu: \['battery', 'battery life', 'batt life', 'akumulator'\]. Muszą one mapować na jeden, znormalizowany węzeł, np. (:Aspect {name: 'battery\_life'}).  
* **Nowe Węzły:** (:Aspect {name: STRING}) \- Reprezentuje *znormalizowany* aspekt.  
* **Nowe Relacje (Poziom Recenzji):**  
  * (:Review)--\>(:Aspect)  
  * Relacja r powinna przechowywać kontekst: r.sentiment (np. 'Positive') oraz r.opinion (np. 'amazing', 'drains fast').10  
* **Rozwiązanie (Normalizacja / Entity Linking):**  
  1. Po przetworzeniu dużej partii recenzji, wyodrębnij unikalną listę wszystkich terminów aspektów.  
  2. Zbuduj niestandardową bazę wiedzy (Knowledge Base, KB) 17 lub słownik (gazetteer) z encji już istniejących w grafie: ParentProduct.title, Attribute.name, Category.name.  
  3. Użyj spaCy's EntityRuler.19 Skonfiguruj go tak, aby dopasowywał wydobyte terminy aspektów do encji w Twojej KB. EntityRuler pozwala na priorytetyzację dopasowań.20  
  4. Dla terminów, które nie zostaną dopasowane (np. "fan\_noise", który może nie być formalnym atrybutem, ale jest ważny dla użytkowników), utwórz nowe, kanoniczne węzły :Aspect.

### **2.4. Krok 3: Agregacja Preferencji Użytkownika (Budowanie Profilu)**

Jest to kluczowy krok inferencyjny, który buduje długoterminowy profil użytkownika. Przechodzimy od "Użytkownik A *powiedział* 'bateria jest zła' w recenzji X" do "Użytkownik A *generalnie nie lubi* słabych baterii".

* **Cel:** Stworzenie zagregowanych, trwałych relacji preferencji: (:User)--\>(:Aspect) i (:User)--\>(:Aspect).21  
* **Algorytm Agregacji (Heurystyka):** Wymaga to zdefiniowania logiki biznesowej do agregacji sentymentów.22  
  1. **Zliczanie (Cypher):** Dla każdego użytkownika i każdego aspektu, z którym miał interakcje, zlicz liczbę pozytywnych, negatywnych i neutralnych wzmianek.  
     Cypher  
     MATCH (u:User)--\>(r:Review)--\>(a:Aspect)  
     RETURN u.userId, a.name, m.sentiment AS sentiment, COUNT(\*) AS count

  2. **Agregacja (Python/Pandas):** Przetwórz wyniki, aby dla każdej pary (u, a) uzyskać wektor zliczeń, np. {'Positive': 10, 'Negative': 2, 'Neutral': 1}.  
  3. **Zastosowanie Heurystyki:** Zastosuj zdefiniowane progi, aby podjąć decyzję o utworzeniu relacji PREFERS lub DISLIKES.26 Logika ta jest kluczowa dla dostrojenia czułości systemu.

**Tabela 4: Heurystyki Agregacji Sentymentu (Przykładowa Logika Biznesowa)**

| Parametr | Opis | Sugerowana Wartość | Uzasadnienie |
| :---- | :---- | :---- | :---- |
| min\_opinions\_threshold | Minimalna liczba opinii (pozytywnych \+ negatywnych) o danym aspekcie, aby wydać osąd. | 3 | Unikanie pochopnych wniosków i budowania profilu na podstawie pojedynczej, być może przypadkowej wzmianki.26 |
| preference\_threshold | Procent zgodnych opinii (np. positive / (positive \+ negative)) wymagany do utworzenia relacji. | 0.70 (tj. 70%) | Wymagamy silnej większości, aby stwierdzić trwałą "preferencję". Wartość 0.5 oznaczałaby brak preferencji. |
| dislike\_threshold | Procent zgodnych opinii (np. negative / (positive \+ negative)) wymagany do utworzenia relacji DISLIKES. | 0.70 (tj. 70%) | Symetryczne do preferencji; silne negatywne sygnały są kluczowe w rekomendacjach.21 |

Utworzenie tego grafu preferencji semantycznych ma fundamentalne znaczenie. Pozwala systemowi rekomendacyjnemu na rozwiązywanie problemu zimnego startu dla *nowych produktów*.28 Jeśli UserA ma relację DISLIKES z AspectX (np. 'głośny wentylator'), a na rynek wchodzi nowy ProductY, system może proaktywnie *unikać* rekomendowania ProductY użytkownikowi UserA, gdy tylko pierwsze recenzje ProductY (napisane przez innych użytkowników) zostaną przetworzone przez potok ABSA i wykażą negatywny sentyment wobec AspectX. System uczy się, że UserA prawdopodobnie nie polubi tego produktu, mimo że nigdy nie miał z nim interakcji.

## **Część 3: Architektura GraphRAG – Łączenie Wiedzy Semantycznej i Strukturalnej**

Ta faza buduje warstwę leksykalną grafu, niezbędną do zastosowań RAG (Retrieval-Augmented Generation).29 Celem jest umożliwienie modelom LLM odnajdywania *konkretnych fragmentów tekstu* (dowodów), które odnoszą się do encji i preferencji w grafie, co jest kluczowe dla rekomendacji konwersacyjnych i wyjaśnialnych.

### **3.1. Krok 1: Dzielenie Tekstu (Chunking)**

* **Źródła Tekstu:** Główne źródła tekstu to Review.text oraz ParentProduct.description i ParentProduct.features.1  
* **Strategia:** Teksty te muszą zostać podzielone na mniejsze, semantycznie spójne fragmenty (chunks).32  
* **Narzędzie:** langchain.text\_splitter.RecursiveCharacterTextSplitter.34 Jest to preferowane nad prostym dzieleniem na stałą wielkość, ponieważ próbuje dzielić tekst w naturalnych granicach (akapity, zdania).  
* **Parametry:**  
  * chunk\_size: Np. 500 (znaków lub tokenów, w zależności od metody) – musi być wystarczająco mały, aby zmieścić się w kontekście LLM, ale wystarczająco duży, aby zachować sens.  
  * chunk\_overlap: Np. 50 34 – kluczowy parametr zapewniający, że zdania lub koncepcje nie są gwałtownie przecinane na granicy fragmentów, co utrzymuje spójność semantyczną.  
* **Modelowanie w Grafie:**  
  * Utwórz węzły (:Chunk {chunkId: STRING, text: STRING, index: INTEGER}).37  
  * Utwórz relacje łączące fragment z jego źródłem: (:Chunk)--\>(:Review) lub (:Chunk)--\>(:ParentProduct).37  
  * Opcjonalnie: (:Chunk)--\>(:Chunk), aby zachować sekwencyjność.37

### **3.2. Krok 2: Generowanie Embeddingów Tekstowych (dla RAG)**

Każdy węzeł (:Chunk) musi posiadać reprezentację wektorową (embedding) do wyszukiwania semantycznego. *Uwaga: są to inne embeddingi niż te generowane przez GNN w Części 4\.*

* **Cel:** Umożliwienie wyszukiwania wektorowego (ANN) w celu znalezienia fragmentów tekstu semantycznie podobnych do zapytania użytkownika (np. "fragmenty mówiące o cichej pracy urządzenia").  
* **Wybór Modelu (Sentence Transformer):**  
  * BAAI/bge-m3 39: Jeden z najsilniejszych obecnie (2024) modeli open-source, wielojęzyczny, obsługuje duży kontekst.  
  * all-mpnet-base-v2 40: Starszy, ale wciąż solidny, szybki i powszechnie stosowany standard.  
* **Zalecenie:** **BAAI/bge-m3**.39  
* **Proces (Python \+ Neo4j):**  
  1. Załaduj SentenceTransformer("BAAI/bge-m3").  
  2. Pobierz wszystkie Chunk.text z Neo4j.  
  3. Wygeneruj embeddingi (model.encode(...)).  
  4. Zapisz embeddingi z powrotem do Neo4j jako właściwość c.embedding na węźle (:Chunk).  
  5. Utwórz indeks wektorowy w Neo4j, aby umożliwić szybkie wyszukiwanie: CREATE VECTOR INDEX chunk\_embedding\_index IF NOT EXISTS FOR (c:Chunk) ON (c.embedding) OPTIONS {indexConfig:...}.41

### **3.3. Krok 3: Łączenie Tekstu ze Strukturą Grafu (Relacja MENTIONS)**

Jest to serce architektury GraphRAG.38 Łączymy węzły (:Chunk) z encjami *strukturalnymi* (:Product, :Brand, :Aspect), które są w nich wymienione.43

* **Proces (Entity Linking na Fragmentach):**  
  1. **Zebranie Słownika (Gazetteer):** Użyj słownika encji stworzonego w Kroku 2.3 (ze wszystkich ParentProduct.title, Brand.name, Aspect.name).  
  2. **Konfiguracja spaCy EntityRuler:** Użyj tego samego, skonfigurowanego EntityRuler 19, który rozpoznaje encje z Twojego grafu. Upewnij się, że jest umieszczony w potoku spaCy *przed* domyślnym 'ner', aby priorytetyzować Twoje encje.20  
  3. **Przetwarzanie (Python):** Iteruj przez każdy węzeł (:Chunk):  
     * doc \= nlp(chunk.text)  
     * Dla każdego ent w doc.ents (znalezionego przez EntityRuler):  
       * Znajdź odpowiedni węzeł w grafie: MATCH (e:Label {name: ent.text}) WHERE e.label\_ \= ent.label\_ (użyj etykiety, aby rozróżnić :Brand od :Product o tej samej nazwie).  
       * Utwórz relację łączącą fragment tekstu z encją: MATCH (c:Chunk {chunkId:...}) MERGE (c)--\>(e).47

Połączenie tych trzech warstw w jednym grafie 30 tworzy potężną synergię. Powstały graf jest nie tylko magazynem danych, ale aktywnym mechanizmem rozumowania, który wspiera dwa kluczowe scenariusze:

1. **Synergia dla GNN (Część 4):** Grafowa Sieć Neuronowa, agregując informacje, może teraz podążać ścieżkami leksykalnymi, np. (ProductA)\<--(Chunk1)--\>(ProductB). Oznacza to, że jeśli dwa produkty są często *wspominane w tym samym kontekście tekstowym*, ich embeddingi GNN (nawet te do rekomendacji) staną się do siebie podobne. Tworzy to nową, potężną formę podobieństwa opartego na treści (content-based), wyuczoną na podstawie surowego tekstu.  
2. **Synergia dla RAG (LLM):** Kiedy system rekomendacyjny (oparty na GNN) poleci ProductA użytkownikowi UserA, a ten zapyta "Dlaczego?", system konwersacyjny (LLM) może wykonać zapytanie GraphRAG. Zapytanie to może prześledzić ścieżkę rozumowania, np. MATCH (u:User {id: 'UserA'})--\>(a:Aspect {name: 'battery\_life'})\<--(r:Review)--\>(c:Chunk) WHERE (c)--\>(p:Product {asin: 'ProductA'}) RETURN c.text, a.name. LLM otrzyma wtedy konkretny fragment recenzji (c.text) jako *dowód* (evidence), na podstawie którego może sformułować odpowiedź: "Polecam ProductA, ponieważ *preferujesz* aspekt battery\_life, a recenzje tego produktu zawierają fragmenty takie jak: '\[...\] *bateria trzyma niesamowicie długo* \[...\]'".

## **Część 4: Generowanie Reprezentacji Wektorowych – Od Grafu do Embeddingów (KGE i GNN)**

Mając kompletny, bogaty semantycznie graf (zbudowany w Częściach 1 i 2), celem jest teraz wygenerowanie wysokiej jakości, skondensowanych reprezentacji wektorowych (embeddingów) dla węzłów User i ParentProduct. Te embeddingi będą stanowić paliwo dla silnika rekomendacyjnego.

### **4.1. Cel: Embeddingi Kodujące Strukturę Grafu i Semantykę**

Chcemy, aby końcowy wektor (embedding) dla UserA kodował nie tylko to, co kupił (sygnał kolaboracyjny), ale także to, jakie ma atrybuty (treść) i co lubi/nie lubi (sentyment). Grafowe Sieci Neuronowe (GNN) są idealne do tego zadania, ponieważ działają poprzez agregację informacji z sąsiedztwa węzła, co pozwala na rozumowanie wieloskokowe (multi-hop reasoning).

### **4.2. Krok 1: Analiza Porównawcza i Wybór Modelu GNN**

Nasz graf jest *heterogeniczny* (posiada wiele typów węzłów, np. User, Product, Aspect) oraz *multirelacyjny* (posiada wiele typów krawędzi, np. BOUGHT\_TOGETHER, PREFERS, DISLIKES). Wybór modelu GNN ma kluczowe znaczenie.

**Tabela 5: Porównanie Modeli GNN dla Rekomendacji na Bogatym Grafie**

| Model | Obsługa Grafu Heterogenicznego | Obsługa Typów Relacji | Mechanizm Wagi Relacji | Adekwatność dla Grafu Amazon '23 |
| :---- | :---- | :---- | :---- | :---- |
| **LightGCN** 49 | Tak (zwykle Bipartite: User-Item) | Nie | Brak (traktuje wszystkie relacje tak samo) | **Niska**. Zignorowałby całe bogactwo semantyczne (aspekty, atrybuty). Uśredniłby sygnał DISLIKES z IN\_CATEGORY, co jest błędem.51 |
| **R-GCN** (Relational-GCN) 52 | Tak | Tak (uczy się oddzielnej macierzy wag dla każdego *typu* relacji) 53 | Statyczny (zależny od typu) | **Średnia**. Rozumie różnicę między PREFERS a BOUGHT\_TOGETHER. Jest to solidny wybór bazowy. |
| **KGAT** (Knowledge Graph Attention) 50 | Tak | Tak | **Dynamiczny (Uwaga/Attention)** 55 | **Wysoka (Zalecany)**. KGAT nie tylko rozróżnia typy relacji, ale *uczy się ich ważności* w kontekście. Może dynamicznie nauczyć się, że dla UserA relacja DISLIKES jest *ważniejsza* (ma wyższą wagę uwagi) niż relacja BOUGHT\_TOGETHER. |

Uzasadnienie wyboru **KGAT** 50 wynika bezpośrednio z bogactwa grafu zbudowanego w Częściach 1 i 2\. Stworzyliśmy graf, w którym relacje mają drastycznie różną wagę informacyjną. (User)--\>(Aspect) to potężny, negatywny sygnał. (Product)--\>(Category) to słaby sygnał kontekstowy. Zastosowanie modelu takiego jak LightGCN 49 zniweczyłoby tę pracę, uśredniając wszystkie sygnały.51 KGAT 55, dzięki mechanizmowi uwagi 56, jest zaprojektowany do dynamicznego ważenia istotności tej wiedzy i jest optymalnym wyborem.

### **4.3. Krok 2: Przewodnik Implementacyjny (PyTorch Geometric)**

* **Narzędzia:** PyTorch Geometric (PyG) 57 lub Deep Graph Library (DGL).60 PyG jest powszechnym wyborem ze względu na integrację z PyTorch.  
* **Krok 2a: Eksport Danych z Neo4j:** Wyeksportuj graf jako listy krawędzi (edge lists) dla każdego typu relacji.  
* **Krok 2b: Tworzenie HeteroData:** PyG 57 używa obiektu HeteroData do modelowania grafów heterogenicznych.  
  Python  
  from torch\_geometric.data import HeteroData

  data \= HeteroData()

  \# Załaduj cechy węzłów (lub inicjalizuj losowo embeddingi)  
  data\['user'\].x \= torch.randn(num\_users, 64)  
  data\['parent\_product'\].x \= torch.randn(num\_products, 64)  
  data\['aspect'\].x \= torch.randn(num\_aspects, 64)  
  \#...dla wszystkich typów węzłów

  \# Załaduj indeksy krawędzi (tensor \[2, num\_edges\])  
  \# Każdy typ relacji jest oddzielnym kluczem  
  data\['user', 'wrote', 'review'\].edge\_index \=...   
  data\['user', 'prefers', 'aspect'\].edge\_index \=...  
  data\['user', 'dislikes', 'aspect'\].edge\_index \=...  
  data\['parent\_product', 'bought\_together', 'parent\_product'\].edge\_index \=...  
  \#...dla wszystkich typów relacji z Tabeli 2 i Części 2

* **Krok 2c: Definicja Modelu GNN:** Zastosuj warstwy GNN obsługujące grafy heterogeniczne, takie jak HGTConv lub (dla KGAT) GATConv 59 owinięte w HeteroConv lub niestandardową implementację warstwy KGAT.  
* **Krok 2d: Pętla Treningowa (Link Prediction):**  
  * **Zadanie:** Wytrenuj model, aby przewidywał istniejące krawędzie interakcji (np. (User)-...-\>(Product)).  
  * **Proces:** Użyj negatywnego próbkowania (Negative Sampling). Dla każdej prawdziwej krawędzi interakcji (pozytywny przykład) wygeneruj kilka losowych, nieistniejących krawędzi (negatywne przykłady).  
  * **Funkcja Straty:** Użyj funkcji straty, która maksymalizuje wynik (np. podobieństwo cosinusowe) dla prawdziwych par i minimalizuje dla fałszywych, np. BCEWithLogitsLoss lub MarginRankLoss.  
* **Krok 2e: Ekstrakcja Embeddingów:** Po zakończeniu treningu, uruchom model na pełnym grafie (final\_embeddings \= model.encode(data)). Wynikowe wektory, final\_embeddings\['user'\] i final\_embeddings\['parent\_product'\], są gotowymi do użycia embeddingami rekomendacyjnymi.

### **4.4. Krok 3 (Zaawansowane): Wyrównanie Przestrzeni Semantycznych (Semantic Fusion)**

* **Problem:** Obecnie istnieją dwa zestawy embeddingów w dwóch różnych przestrzeniach wektorowych: (A) Chunk.embedding z modelu bge-m3 (dla RAG) oraz (B) ParentProduct.embedding z modelu GNN (dla rekomendacji).  
* **Cel:** Wyrównanie tych przestrzeni 62, aby tekst "cichy wentylator" (z A) był semantycznie blisko embeddingu GNN produktu "SilentLaptop" (z B).  
* **Technika:** **Mutual Information Maximization (MIM)** 65 lub ogólne uczenie kontrastowe (Contrastive Learning).63  
* **Implementacja:** Podczas treningu GNN (Krok 2d), dodaj drugą funkcję straty (loss\_alignment). Ta strata kontrastowa powinna *przyciągać* do siebie embedding GNN produktu (ParentProductP) i uśredniony embedding tekstowy jego opisów/recenzji (Chunk1, Chunk2...), jednocześnie *odpychając* go od embeddingów tekstowych innych, losowych produktów.  
* **Rezultat:** Końcowy embedding GNN staje się "świadomy semantycznie", kodując zarówno strukturę grafu, jak i znaczenie tekstowe swoich opisów.

## **Część 5: Plan Wdrożenia i Wykorzystania Embeddingów**

Ostatnim etapem jest operacjonalizacja embeddingów wygenerowanych w Części 4, aby mogły one obsługiwać zapytania rekomendacyjne w czasie rzeczywistym.

### **5.1. Problem: Wyszukiwanie k-Najbliższych Sąsiadów (kNN) na Skalę**

Posiadamy miliony wektorów User i ParentProduct. Obliczanie podobieństwa cosinusowego (brute-force) między zapytaniem (np. wektorem użytkownika) a wszystkimi wektorami produktów (miliony) jest zbyt wolne dla aplikacji czasu rzeczywistego.

* **Rozwiązanie:** Wyszukiwanie Przybliżonych Najbliższych Sąsiadów (Approximate Nearest Neighbor \- ANN).68

### **5.2. Krok 1: Wybór Biblioteki ANN**

* FAISS (Facebook AI Similarity Search) 68:  
  * *Zalety:* Standard branżowy, niezwykle szybki, wsparcie dla GPU 68, elastyczne typy indeksów (np. IndexIVFPQ – połączenie odwróconego pliku i kwantyzacji produktu), które pozwalają na kompromis między prędkością, zużyciem pamięci a dokładnością.73  
* ScaNN (Scalable Nearest Neighbors) 70:  
  * *Zalety:* Opracowany przez Google, często osiąga lepszą dokładność przy tej samej prędkości co FAISS, szczególnie dla iloczynu skalarnego (inner product), który jest powszechny w rekomendacjach.70  
* **Zalecenie:** **FAISS**.71 Ze względu na swoją dojrzałość, elastyczność konfiguracji (np. kwantyzacja produktu do kompresji wektorów) i szerokie wsparcie społeczności, FAISS jest solidnym i wszechstronnim wyborem do wdrożenia pierwszego systemu ANN.

### **5.3. Krok 2: Proces Rekomendacji (Offline i Online)**

Architektura musi być podzielona na dwa procesy: ciężkie obliczenia (trening GNN, budowanie indeksu) wykonywane offline i błyskawiczne wyszukiwanie (zapytania ANN) wykonywane online.

* **Proces Offline (wykonywany np. codziennie lub co tydzień):**  
  1. Uruchom potok ETL (Część 1), aby zaimportować nowych użytkowników, produkty i recenzje.  
  2. Uruchom potok NLP (Część 2), aby przetworzyć nowe recenzje i zaktualizować relacje MENTIONS\_ASPECT oraz PREFERS/DISLIKES.  
  3. Wytrenuj (lub do-trenuj) model GNN (KGAT) na zaktualizowanym grafie Neo4j (Część 4).  
  4. Wygeneruj *nowe*, kompletne embeddingi dla *wszystkich* węzłów User i ParentProduct.  
  5. Zbuduj (lub całkowicie przebuduj) dwa indeksy FAISS 76:  
     * user\_index.faiss: Zawiera wszystkie wektory użytkowników.  
     * product\_index.faiss: Zawiera wszystkie wektory ParentProduct.  
* **Proces Online (Czas Rzeczywisty \- obsługa zapytania API):**  
  * **Scenariusz 1: Rekomendacje dla strony głównej (User-to-Item):**  
    1. Użytkownik UserA loguje się.  
    2. Pobierz jego wstępnie obliczony wektor embedding\_user\_A (z bazy danych lub pamięci podręcznej).  
    3. Wykonaj zapytanie ANN: D, I \= product\_index.search(embedding\_user\_A, k=20).  
    4. Wynik I (Indeksy) to lista 20 parentAsin produktów, które należy polecić.  
  * **Scenariusz 2: Podobne produkty (Item-to-Item):**  
    1. Użytkownik przegląda stronę ParentProductP.  
    2. Pobierz embedding\_product\_P.  
    3. Wykonaj zapytanie ANN: D, I \= product\_index.search(embedding\_product\_P, k=10).  
    4. Wynik I to lista 10 parentAsin najbardziej podobnych produktów.  
  * **Scenariusz 3: Podobni użytkownicy (User-to-User):**  
    1. Pobierz embedding\_user\_A.  
    2. Wykonaj zapytanie ANN: D, I \= user\_index.search(embedding\_user\_A, k=5).  
    3. Wynik I to lista 5 użytkowników o najbardziej zbliżonych profilach preferencji.

### **Wnioski: Ujednolicony Silnik Rekomendacyjny**

Przedstawiony plan implementacyjny prowadzi do stworzenia systemu, który jest czymś więcej niż sumą jego części. Końcowe embeddingi wygenerowane przez KGAT (Część 4\) 55 i przeszukiwane przez FAISS (Część 5\) 71 nie reprezentują jednego, monolitycznego typu rekomendacji.

Są one *syntetyczną reprezentacją* trzech różnych paradygmatów filtrowania, których GNN *nauczył się* optymalnie równoważyć w celu przewidywania interakcji:

1. Filtrowanie Kolaboracyjne (CF) 77: Zostało włączone do GNN poprzez agregację ścieżek (User)-WROTE-\>...\<-WROTE-(OtherUser) oraz (ParentProduct)-BOUGHT\_TOGETHER-\>(OtherProduct).  
2. **Filtrowanie Oparte na Treści (Content-Based):** Zostało włączone poprzez agregację ścieżek (ParentProduct)-HAS\_ATTRIBUTE-\>(Attribute) i (ParentProduct)-IN\_CATEGORY-\>(Category).  
3. **Filtrowanie Oparte na Sentymentach/Preferencjach:** Jest to najbardziej innowacyjny element, włączony poprzez agregację ścieżek (User)-PREFERS-\>(Aspect) i (User)-DISLIKES-\>(Aspect).21

Kiedy FAISS search() 71 znajduje "najbliższy" wektor produktu do wektora użytkownika, "bliskość" w tej wyuczonej przestrzeni wektorowej jest złożoną, nieliniową funkcją, która automatycznie równoważy: "Jak bardzo ten produkt jest podobny do innych, które kupiłeś?" (CF), "Jak bardzo pasuje do atrybutów, które historycznie wybierałeś?" (Treść), oraz "Jak bardzo odpowiada Twoim ukrytym preferencjom semantycznym, takim jak 'cicha praca' czy 'długa żywotność baterii'?" (Sentyment). Jest to system holistyczny, realizujący pełną wizję rekomendacji opartych na grafach wiedzy.

#### **Cytowane prace**

1. Amazon Reviews 2023, otwierano: listopada 17, 2025, [https://amazon-reviews-2023.github.io/](https://amazon-reviews-2023.github.io/)  
2. McAuley-Lab/Amazon-Reviews-2023 · Datasets at Hugging Face, otwierano: listopada 17, 2025, [https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023)  
3. Amazon Reviews Data 2023 \- Kaggle, otwierano: listopada 17, 2025, [https://www.kaggle.com/datasets/wajahat1064/amazon-reviews-data-2023](https://www.kaggle.com/datasets/wajahat1064/amazon-reviews-data-2023)  
4. The Recommendation: what to shop \!\!\!\!\!\! | by Anirudh Narayana | Medium, otwierano: listopada 17, 2025, [https://medium.com/@akaniyar/the-recommendation-what-to-shop-42bd2bacc551](https://medium.com/@akaniyar/the-recommendation-what-to-shop-42bd2bacc551)  
5. Modeling Categories in a Graph Database \- Neo4j, otwierano: listopada 17, 2025, [https://neo4j.com/blog/developer/modeling-categories-in-a-graph-database/](https://neo4j.com/blog/developer/modeling-categories-in-a-graph-database/)  
6. Create a graph database in Neo4j using Python | by CJ Sullivan | TDS Archive \- Medium, otwierano: listopada 17, 2025, [https://medium.com/data-science/create-a-graph-database-in-neo4j-using-python-4172d40f89c4](https://medium.com/data-science/create-a-graph-database-in-neo4j-using-python-4172d40f89c4)  
7. Test data quality at scale with Deequ \- Amazon AWS, otwierano: listopada 17, 2025, [https://aws.amazon.com/blogs/big-data/test-data-quality-at-scale-with-deequ/](https://aws.amazon.com/blogs/big-data/test-data-quality-at-scale-with-deequ/)  
8. Introduction to PyABSA, otwierano: listopada 17, 2025, [https://pyabsa.readthedocs.io/en/v2/0\_intro/introduction.html](https://pyabsa.readthedocs.io/en/v2/0_intro/introduction.html)  
9. yangheng95/PyABSA: Sentiment Analysis, Text Classification, Text Augmentation, Text Adversarial defense, etc. \- GitHub, otwierano: listopada 17, 2025, [https://github.com/yangheng95/PyABSA](https://github.com/yangheng95/PyABSA)  
10. Aspect-Sentiment-Multiple-Opinion Triplet Extraction \- ResearchGate, otwierano: listopada 17, 2025, [https://www.researchgate.net/publication/355233699\_Aspect-Sentiment-Multiple-Opinion\_Triplet\_Extraction](https://www.researchgate.net/publication/355233699_Aspect-Sentiment-Multiple-Opinion_Triplet_Extraction)  
11. How to Implement Aspect-Based Sentiment Analysis with PyABSA \- fxis.ai, otwierano: listopada 17, 2025, [https://fxis.ai/edu/how-to-implement-aspect-based-sentiment-analysis-with-pyabsa/](https://fxis.ai/edu/how-to-implement-aspect-based-sentiment-analysis-with-pyabsa/)  
12. SetFit for Aspect Based Sentiment Analysis \- Hugging Face, otwierano: listopada 17, 2025, [https://huggingface.co/docs/setfit/how\_to/absa](https://huggingface.co/docs/setfit/how_to/absa)  
13. SetFitABSA: Few-Shot Aspect Based Sentiment Analysis using SetFit \- Hugging Face, otwierano: listopada 17, 2025, [https://huggingface.co/blog/setfit-absa](https://huggingface.co/blog/setfit-absa)  
14. Understanding Aspect-Based Sentiment Analysis: A Deep Dive into Review Data with Python | by Yolanda Yasyifa Basrul | Medium, otwierano: listopada 17, 2025, [https://medium.com/@yyasyifa/understanding-aspect-based-sentiment-analysis-a-deep-dive-into-review-data-with-python-85a69495bcc8](https://medium.com/@yyasyifa/understanding-aspect-based-sentiment-analysis-a-deep-dive-into-review-data-with-python-85a69495bcc8)  
15. pyabsa.tasks.AspectSentimentTripletExtraction.prediction.predictor, otwierano: listopada 17, 2025, [https://pyabsa.readthedocs.io/en/v2/autoapi/pyabsa/tasks/AspectSentimentTripletExtraction/prediction/predictor/](https://pyabsa.readthedocs.io/en/v2/autoapi/pyabsa/tasks/AspectSentimentTripletExtraction/prediction/predictor/)  
16. The power of Aspect Based Sentiment Analysis (with code) | by Kaushik Jagini \- Medium, otwierano: listopada 17, 2025, [https://medium.com/swlh/the-power-of-aspect-based-sentiment-analysis-18c3908ac53d](https://medium.com/swlh/the-power-of-aspect-based-sentiment-analysis-18c3908ac53d)  
17. EntityLinker · spaCy API Documentation, otwierano: listopada 17, 2025, [https://spacy.io/api/entitylinker](https://spacy.io/api/entitylinker)  
18. KnowledgeBase · spaCy API Documentation, otwierano: listopada 17, 2025, [https://spacy.io/api/kb](https://spacy.io/api/kb)  
19. Rule-based matching · spaCy Usage Documentation, otwierano: listopada 17, 2025, [https://spacy.io/usage/rule-based-matching](https://spacy.io/usage/rule-based-matching)  
20. How can I prioritize Rule Based Matching over trained NER Model in Spacy?, otwierano: listopada 17, 2025, [https://stackoverflow.com/questions/57703630/how-can-i-prioritize-rule-based-matching-over-trained-ner-model-in-spacy](https://stackoverflow.com/questions/57703630/how-can-i-prioritize-rule-based-matching-over-trained-ner-model-in-spacy)  
21. How to deal with negative preferences in recommender systems: a theoretical framework, otwierano: listopada 17, 2025, [https://pmc.ncbi.nlm.nih.gov/articles/PMC9038518/](https://pmc.ncbi.nlm.nih.gov/articles/PMC9038518/)  
22. Aspect-based Sentiment Analysis (ABSA) using Machine Learning Algorithms \- IEEE Xplore, otwierano: listopada 17, 2025, [https://ieeexplore.ieee.org/document/10549140/](https://ieeexplore.ieee.org/document/10549140/)  
23. Aspect-Based Sentiment Analysis by Leveraging Machine Learning Techniques, otwierano: listopada 17, 2025, [https://ieeexplore.ieee.org/document/10973644/](https://ieeexplore.ieee.org/document/10973644/)  
24. Sentiment Summarization: Evaluating and Learning User Preferences \- Google Research, otwierano: listopada 17, 2025, [https://research.google.com/pubs/archive/35073.pdf](https://research.google.com/pubs/archive/35073.pdf)  
25. Personalized Review Recommendation based on Users' Aspect Sentiment \- Temple CIS, otwierano: listopada 17, 2025, [https://cis.temple.edu/\~wu/research/publications/Publication\_files/wenjunjiang\_toit\_2020.pdf](https://cis.temple.edu/~wu/research/publications/Publication_files/wenjunjiang_toit_2020.pdf)  
26. Python program to find number of likes and dislikes? \- Tutorials Point, otwierano: listopada 17, 2025, [https://www.tutorialspoint.com/python-program-to-find-number-of-likes-and-dislikes](https://www.tutorialspoint.com/python-program-to-find-number-of-likes-and-dislikes)  
27. Algorithm for matching people together based on likes and dislikes \- Stack Overflow, otwierano: listopada 17, 2025, [https://stackoverflow.com/questions/57806866/algorithm-for-matching-people-together-based-on-likes-and-dislikes](https://stackoverflow.com/questions/57806866/algorithm-for-matching-people-together-based-on-likes-and-dislikes)  
28. A Comprehensive Overview of Recommender System and Sentiment Analysis \- arXiv, otwierano: listopada 17, 2025, [https://arxiv.org/pdf/2109.08794](https://arxiv.org/pdf/2109.08794)  
29. Neo4j GraphRAG Python Package \- Developer Guides, otwierano: listopada 17, 2025, [https://neo4j.com/developer/genai-ecosystem/graphrag-python/](https://neo4j.com/developer/genai-ecosystem/graphrag-python/)  
30. Creating Knowledge Graphs from Unstructured Data \- Developer Guides \- Neo4j, otwierano: listopada 17, 2025, [https://neo4j.com/developer/genai-ecosystem/importing-graph-from-unstructured-data/](https://neo4j.com/developer/genai-ecosystem/importing-graph-from-unstructured-data/)  
31. Enhancing RAG-based application accuracy by constructing and leveraging knowledge graphs \- LangChain Blog, otwierano: listopada 17, 2025, [https://blog.langchain.com/enhancing-rag-based-applications-accuracy-by-constructing-and-leveraging-knowledge-graphs/](https://blog.langchain.com/enhancing-rag-based-applications-accuracy-by-constructing-and-leveraging-knowledge-graphs/)  
32. Mastering Chunking Strategies for RAG: Best Practices & Code Examples \- Databricks Community, otwierano: listopada 17, 2025, [https://community.databricks.com/t5/technical-blog/the-ultimate-guide-to-chunking-strategies-for-rag-applications/ba-p/113089](https://community.databricks.com/t5/technical-blog/the-ultimate-guide-to-chunking-strategies-for-rag-applications/ba-p/113089)  
33. Implementing 'From Local to Global' GraphRAG With Neo4j and LangChain: Constructing the Graph, otwierano: listopada 17, 2025, [https://neo4j.com/blog/developer/global-graphrag-neo4j-langchain/](https://neo4j.com/blog/developer/global-graphrag-neo4j-langchain/)  
34. Chunking Strategies for RAG: Fixed, Recursive, Semantic, Language-Based, and Context-Aware Approaches \- Matheus Jericó, otwierano: listopada 17, 2025, [https://matheusjerico.medium.com/chunking-strategies-for-rag-fixed-recursive-semantic-language-based-and-context-aware-4ab476aea7d1](https://matheusjerico.medium.com/chunking-strategies-for-rag-fixed-recursive-semantic-language-based-and-context-aware-4ab476aea7d1)  
35. Effective Chunking Strategies for RAG \- Cohere Documentation, otwierano: listopada 17, 2025, [https://docs.cohere.com/page/chunking-strategies](https://docs.cohere.com/page/chunking-strategies)  
36. RAG Chunking | Langchain RecursiveCharacterTextSplitter | LLM | Gen AI \- YouTube, otwierano: listopada 17, 2025, [https://www.youtube.com/watch?v=0dJDQTdFSDM](https://www.youtube.com/watch?v=0dJDQTdFSDM)  
37. API Documentation — neo4j-graphrag-python documentation, otwierano: listopada 17, 2025, [https://neo4j.com/docs/neo4j-graphrag-python/current/api.html](https://neo4j.com/docs/neo4j-graphrag-python/current/api.html)  
38. Lexical Graph with Extracted Entities \- GraphRAG, otwierano: listopada 17, 2025, [https://graphrag.com/reference/knowledge-graph/lexical-graph-extracted-entities/](https://graphrag.com/reference/knowledge-graph/lexical-graph-extracted-entities/)  
39. Smart Chunking & Embeddings for RAG \- DEV Community, otwierano: listopada 17, 2025, [https://dev.to/ashokan/smart-chunking-embeddings-for-rag-4ok](https://dev.to/ashokan/smart-chunking-embeddings-for-rag-4ok)  
40. What Embedding Models Are You Using For RAG? : r/LocalLLaMA \- Reddit, otwierano: listopada 17, 2025, [https://www.reddit.com/r/LocalLLaMA/comments/18j39qt/what\_embedding\_models\_are\_you\_using\_for\_rag/](https://www.reddit.com/r/LocalLLaMA/comments/18j39qt/what_embedding_models_are_you_using_for_rag/)  
41. User Guide: RAG — neo4j-graphrag-python documentation, otwierano: listopada 17, 2025, [https://neo4j.com/docs/neo4j-graphrag-python/current/user\_guide\_rag.html](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)  
42. Setting Up and Running GraphRAG with Neo4j \- Analytics Vidhya, otwierano: listopada 17, 2025, [https://www.analyticsvidhya.com/blog/2024/11/graphrag-with-neo4j/](https://www.analyticsvidhya.com/blog/2024/11/graphrag-with-neo4j/)  
43. Graph RAG with Milvus, otwierano: listopada 17, 2025, [https://milvus.io/docs/graph\_rag\_with\_milvus.md](https://milvus.io/docs/graph_rag_with_milvus.md)  
44. From RAG to GraphRAG: Knowledge Graphs, Ontologies and Smarter AI | GoodData, otwierano: listopada 17, 2025, [https://www.gooddata.com/blog/from-rag-to-graphrag-knowledge-graphs-ontologies-and-smarter-ai/](https://www.gooddata.com/blog/from-rag-to-graphrag-knowledge-graphs-ontologies-and-smarter-ai/)  
45. GraphRAG with Qdrant and Neo4j, otwierano: listopada 17, 2025, [https://qdrant.tech/documentation/examples/graphrag-qdrant-neo4j/](https://qdrant.tech/documentation/examples/graphrag-qdrant-neo4j/)  
46. E2GraphRAG: Streamlining Graph-based RAG for High Efficiency and Effectiveness \- arXiv, otwierano: listopada 17, 2025, [https://arxiv.org/html/2505.24226v3](https://arxiv.org/html/2505.24226v3)  
47. Named Entity Recognition and Knowledge Graph for Natural Language Understanding | by Vincent Yuan | Medium, otwierano: listopada 17, 2025, [https://medium.com/@vincentyuan87/named-entity-recognition-and-knowledge-graph-for-natural-language-understanding-c36401fc25af](https://medium.com/@vincentyuan87/named-entity-recognition-and-knowledge-graph-for-natural-language-understanding-c36401fc25af)  
48. An idea for GraphRAG. | by Ryan Henning | Feb, 2025 \- Medium, otwierano: listopada 17, 2025, [https://medium.com/@acu192/an-idea-for-graphrag-f14d87fa532f](https://medium.com/@acu192/an-idea-for-graphrag-f14d87fa532f)  
49. LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation \- arXiv, otwierano: listopada 17, 2025, [https://arxiv.org/pdf/2002.02126](https://arxiv.org/pdf/2002.02126)  
50. A review of Recommender Systems approaches exploiting Graph Neural Networks | by Cristian Urbinati | Data Reply IT | DataTech | Medium, otwierano: listopada 17, 2025, [https://medium.com/data-reply-it-datatech/a-review-of-recommender-systems-approaches-exploiting-graph-neural-networks-7bfb7e481280](https://medium.com/data-reply-it-datatech/a-review-of-recommender-systems-approaches-exploiting-graph-neural-networks-7bfb7e481280)  
51. KLGCN: Knowledge graph-aware Light Graph Convolutional Network for recommender systems, otwierano: listopada 17, 2025, [https://skyearth.org/publication/papers/2022\_klgcn.pdf](https://skyearth.org/publication/papers/2022_klgcn.pdf)  
52. Relational Graph Convolutional Network — DGL 2.3.1 documentation, otwierano: listopada 17, 2025, [https://www.dgl.ai/dgl\_docs/en/2.3.x/tutorials/models/1\_gnn/4\_rgcn.html](https://www.dgl.ai/dgl_docs/en/2.3.x/tutorials/models/1_gnn/4_rgcn.html)  
53. Deep Graph Networks \- Amazon SageMaker AI \- AWS Documentation, otwierano: listopada 17, 2025, [https://docs.aws.amazon.com/sagemaker/latest/dg/deep-graph-library.html](https://docs.aws.amazon.com/sagemaker/latest/dg/deep-graph-library.html)  
54. Using edge features for GCN in DGL \- Stack Overflow, otwierano: listopada 17, 2025, [https://stackoverflow.com/questions/57779973/using-edge-features-for-gcn-in-dgl](https://stackoverflow.com/questions/57779973/using-edge-features-for-gcn-in-dgl)  
55. A novel recommender system using light graph convolutional network and personalized knowledge-aware attention sub-network \- PubMed Central, otwierano: listopada 17, 2025, [https://pmc.ncbi.nlm.nih.gov/articles/PMC12052977/](https://pmc.ncbi.nlm.nih.gov/articles/PMC12052977/)  
56. (PDF) A novel recommender system using light graph convolutional network and personalized knowledge-aware attention sub-network \- ResearchGate, otwierano: listopada 17, 2025, [https://www.researchgate.net/publication/391457565\_A\_novel\_recommender\_system\_using\_light\_graph\_convolutional\_network\_and\_personalized\_knowledge-aware\_attention\_sub-network](https://www.researchgate.net/publication/391457565_A_novel_recommender_system_using_light_graph_convolutional_network_and_personalized_knowledge-aware_attention_sub-network)  
57. PyTorch Geometric \- Read the Docs, otwierano: listopada 17, 2025, [https://pytorch-geometric.readthedocs.io/](https://pytorch-geometric.readthedocs.io/)  
58. Pytorch Geometric Tutorial \- Antonio Longa, otwierano: listopada 17, 2025, [https://antoniolonga.github.io/Pytorch\_geometric\_tutorials/](https://antoniolonga.github.io/Pytorch_geometric_tutorials/)  
59. PyTorch Geometric Tutorial \- Medium, otwierano: listopada 17, 2025, [https://medium.com/we-talk-data/pytorch-geometric-tutorial-94af3ae2b8cb](https://medium.com/we-talk-data/pytorch-geometric-tutorial-94af3ae2b8cb)  
60. dmlc/dgl: Python package built to ease deep learning on graph, on top of existing DL frameworks. \- GitHub, otwierano: listopada 17, 2025, [https://github.com/dmlc/dgl](https://github.com/dmlc/dgl)  
61. Deep Graph Library (DGL), otwierano: listopada 17, 2025, [https://www.dgl.ai/](https://www.dgl.ai/)  
62. Aligning Vision to Language: Text-Free Multimodal Knowledge Graph Construction for Enhanced LLMs Reasoning \- arXiv, otwierano: listopada 17, 2025, [https://arxiv.org/html/2503.12972v1](https://arxiv.org/html/2503.12972v1)  
63. GT2Vec: Large Language Models as Multi-Modal Encoders for Text and Graph-Structured Data \- arXiv, otwierano: listopada 17, 2025, [https://arxiv.org/html/2410.11235v2](https://arxiv.org/html/2410.11235v2)  
64. MDSEA: Knowledge Graph Entity Alignment Based on Multimodal Data Supervision \- MDPI, otwierano: listopada 17, 2025, [https://www.mdpi.com/2076-3417/14/9/3648](https://www.mdpi.com/2076-3417/14/9/3648)  
65. A Mutual Information Perspective on Knowledge Graph Embedding \- ACL Anthology, otwierano: listopada 17, 2025, [https://aclanthology.org/2025.acl-long.1077.pdf](https://aclanthology.org/2025.acl-long.1077.pdf)  
66. Mutual Information Maximization in Graph Neural Networks | Request PDF \- ResearchGate, otwierano: listopada 17, 2025, [https://www.researchgate.net/publication/347038408\_Mutual\_Information\_Maximization\_in\_Graph\_Neural\_Networks](https://www.researchgate.net/publication/347038408_Mutual_Information_Maximization_in_Graph_Neural_Networks)  
67. \[2012.05442\] Bipartite Graph Embedding via Mutual Information Maximization \- arXiv, otwierano: listopada 17, 2025, [https://arxiv.org/abs/2012.05442](https://arxiv.org/abs/2012.05442)  
68. Faiss: A library for efficient similarity search \- Engineering at Meta \- Facebook, otwierano: listopada 17, 2025, [https://engineering.fb.com/2017/03/29/data-infrastructure/faiss-a-library-for-efficient-similarity-search/](https://engineering.fb.com/2017/03/29/data-infrastructure/faiss-a-library-for-efficient-similarity-search/)  
69. FAISS: A quick tutorial to efficient similarity search | by Shayan Fazeli | Medium, otwierano: listopada 17, 2025, [https://shayan-fazeli.medium.com/faiss-a-quick-tutorial-to-efficient-similarity-search-595850e08473](https://shayan-fazeli.medium.com/faiss-a-quick-tutorial-to-efficient-similarity-search-595850e08473)  
70. What's the difference between FAISS, Annoy, and ScaNN? \- Milvus, otwierano: listopada 17, 2025, [https://milvus.io/ai-quick-reference/whats-the-difference-between-faiss-annoy-and-scann](https://milvus.io/ai-quick-reference/whats-the-difference-between-faiss-annoy-and-scann)  
71. Welcome to Faiss Documentation — Faiss documentation, otwierano: listopada 17, 2025, [https://faiss.ai/](https://faiss.ai/)  
72. First steps with Faiss for k-nearest neighbor search in large search spaces \- Davide Fiocco, otwierano: listopada 17, 2025, [https://davidefiocco.github.io/nearest-neighbor-search-with-faiss/](https://davidefiocco.github.io/nearest-neighbor-search-with-faiss/)  
73. Faiss vs ScaNN on Vector Search \- Zilliz blog, otwierano: listopada 17, 2025, [https://zilliz.com/blog/faiss-vs-scann-choosing-the-right-tool-for-vector-search](https://zilliz.com/blog/faiss-vs-scann-choosing-the-right-tool-for-vector-search)  
74. Fast and Scalable Gene Embedding Search: A Comparative Study of FAISS and ScaNN \- OpenReview, otwierano: listopada 17, 2025, [https://openreview.net/pdf?id=jRZLGpfvy8](https://openreview.net/pdf?id=jRZLGpfvy8)  
75. State-of-the-Art Approximate Nearest Neighbor Search with Google's ScaNN and Facebook's FAISS | by ANURAG DIXIT | Medium, otwierano: listopada 17, 2025, [https://medium.com/@DataPlayer/scalable-approximate-nearest-neighbour-search-using-googles-scann-and-facebook-s-faiss-3e84df25ba](https://medium.com/@DataPlayer/scalable-approximate-nearest-neighbour-search-using-googles-scann-and-facebook-s-faiss-3e84df25ba)  
76. criteo/autofaiss: Automatically create Faiss knn indices with the most optimal similarity search parameters. \- GitHub, otwierano: listopada 17, 2025, [https://github.com/criteo/autofaiss](https://github.com/criteo/autofaiss)  
77. Build a Recommendation Engine With Collaborative Filtering \- Real Python, otwierano: listopada 17, 2025, [https://realpython.com/build-recommendation-engine-collaborative-filtering/](https://realpython.com/build-recommendation-engine-collaborative-filtering/)