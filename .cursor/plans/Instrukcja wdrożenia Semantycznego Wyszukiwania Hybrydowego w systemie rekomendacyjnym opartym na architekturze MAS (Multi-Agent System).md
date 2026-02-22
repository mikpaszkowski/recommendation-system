Oto kompleksowa instrukcja wdrożenia **Semantycznego Wyszukiwania Hybrydowego** w Twoim systemie rekomendacyjnym opartym na architekturze MAS (Multi-Agent System).

Plan ten integruje wszystkie dyskutowane elementy: rozszerzenie embeddingów (Brand, Category, Product), logikę "Smart Tool" oraz strategię decyzyjną Orkiestratora.

---

# **Plan Wdrożenia: Semantyczne Wyszukiwanie Hybrydowe w MAS**

**Cel:** Umożliwienie systemowi rozumienia intencji użytkownika (np. "laptop do montażu wideo") i łączenia tego ze ścisłymi filtrami (np. "marka Dell, cena \< 5000"), bez tworzenia osobnego agenta, a poprzez inteligentne narzędzie.

## **Faza 1: Warstwa Danych (Data Engineering)**

*Cel: Nasycenie grafu wiedzy wektorami dla kluczowych węzłów.*

### **1.1. Rozszerzenie Skryptu backfill\_embeddings.py**

Należy zmodyfikować istniejący skrypt (lub utworzyć nowy backfill\_full\_graph.py), aby generował embeddingi dla węzłów: Brand, Category oraz ParentProduct.

**Kluczowa zasada:** Nie embeduj samej nazwy. Twórz "Rich Context String".

#### **Logika generowania tekstów do embeddingu:**

* **Dla ParentProduct:**  
* Python

\# Wzór tekstu  
text\_to\_embed \= f"Product: {product.title}. Category: {category.name}. Features: {features\_summary}. Description: {product.description}"

*   
*   
* **Dla Brand:**  
* Python

\# Wzór tekstu (warto dodać ręcznie lub wygenerować LLM-em krótki opis domeny marki)  
text\_to\_embed \= f"Brand: {brand.name}. Domain: {brand.domain\_description}"   
\# np. "Brand: Asus. Domain: consumer electronics, laptops, gaming hardware, components"

*   
*   
* **Dla Category:**  
* Python

text\_to\_embed \= f"Category: {category.name}. Parent: {parent\_category.name}"

*   
* 

### **1.2. Utworzenie Indeksów w Neo4j**

Musisz utworzyć indeksy wektorowe, aby Neo4j mogło je przeszukiwać. Wykonaj poniższe zapytania w Neo4j Browser lub dodaj do skryptu migracyjnego.

Cypher

// 1\. Indeks dla Produktów (kluczowy dla rekomendacji)  
CREATE VECTOR INDEX product\_embedding\_index IF NOT EXISTS  
FOR (p:ParentProduct) ON (p.embedding)  
OPTIONS {indexConfig: {  
 \`vector.dimensions\`: 384, // Zależy od modelu (np. all-MiniLM-L6-v2 ma 384\)  
 \`vector.similarity\_function\`: 'cosine'  
}}

// 2\. Indeks dla Marek (dla groundingu/disambiguation)  
CREATE VECTOR INDEX brand\_embedding\_index IF NOT EXISTS  
FOR (b:Brand) ON (b.embedding)  
OPTIONS {indexConfig: {  
 \`vector.dimensions\`: 384,  
 \`vector.similarity\_function\`: 'cosine'  
}}

// 3\. Indeks dla Kategorii  
CREATE VECTOR INDEX category\_embedding\_index IF NOT EXISTS  
FOR (c:Category) ON (c.embedding)  
OPTIONS {indexConfig: {  
 \`vector.dimensions\`: 384,  
 \`vector.similarity\_function\`: 'cosine'  
}}

---

## **Faza 2: Warstwa Narzędzi (Tool Layer)**

*Cel: Stworzenie "Smart Toola", który ukrywa złożoność wyboru między wektorami a filtrami.*

### **2.1. Aktualizacja GraphSearchTool**

Zmodyfikuj plik src/tools/graph\_search\_tool.py. Narzędzie to musi przyjmować dwa opcjonalne parametry i na ich podstawie budować zapytanie.

**Struktura metody run:**

Python

from typing import Optional, Dict, Any

class GraphSearchTool:  
    def \_\_init\_\_(self, db\_connector, embedding\_service):  
        self.db \= db\_connector  
        self.embedder \= embedding\_service

    def search(self,   
               semantic\_query: Optional\[str\] \= None,   
               structured\_filters: Optional\[Dict\[str, Any\]\] \= None,  
               limit: int \= 5):  
        """  
        Wybiera strategię wyszukiwania:  
        1\. Hybrid (Semantic \+ Filters) \- NAJWAŻNIEJSZE  
        2\. Vector Only (Semantic)  
        3\. Filter Only (Cypher)  
        """  
          
        \# STRATEGIA 1: HYBRYDA (Najczęstsza i najbardziej pożądana)  
        if semantic\_query and structured\_filters:  
            return self.\_execute\_hybrid\_search(semantic\_query, structured\_filters, limit)  
              
        \# STRATEGIA 2: TYLKO WEKTORY (Gdy brak konkretnych filtrów)  
        if semantic\_query and not structured\_filters:  
            return self.\_execute\_vector\_search(semantic\_query, limit)

        \# STRATEGIA 3: TYLKO FILTRY (Gdy zapytanie jest czysto parametryczne)  
        if structured\_filters and not semantic\_query:  
            return self.\_execute\_cypher\_search(structured\_filters, limit)  
              
        return "Błąd: Nie podano żadnych kryteriów wyszukiwania."

    def \_execute\_hybrid\_search(self, text, filters, limit):  
        \# 1\. Zamień tekst na wektor  
        query\_vector \= self.embedder.encode(text)  
          
        \# 2\. Buduj dynamiczny WHERE z filtrów  
        where\_clauses \= \[\]  
        params \= {"vector": query\_vector}  
          
        for key, value in filters.items():  
            \# Prosta obsługa typów \- w produkcji użyj bardziej zaawansowanego mappingu  
            if key \== "price\_max":  
                where\_clauses.append("node.price \<= $price\_max")  
                params\["price\_max"\] \= value  
            elif key \== "brand":  
                where\_clauses.append("node.brandName \= $brand") \# Zakładając denormalizację lub JOIN  
                params\["brand"\] \= value  
            \# ... inne filtry  
              
        where\_str \= " AND ".join(where\_clauses)  
          
        \# 3\. Zapytanie Hybrydowe Neo4j 5.x  
        cypher \= f"""  
        CALL db.index.vector.queryNodes('product\_embedding\_index', {limit \* 2}, $vector)  
        YIELD node, score  
        WHERE {where\_str}  
        RETURN node.title as title, node.price as price, score  
        ORDER BY score DESC  
        LIMIT {limit}  
        """  
          
        return self.db.execute(cypher, params)

---

## **Faza 3: Warstwa Agenta (Agent Layer)**

*Cel: Nauczenie Orkiestratora (LLM), jak przygotować dane dla narzędzia.*

### **3.1. Prompt Systemowy (Orchestrator / Intent Parser)**

W pliku src/agents/orchestrator.py (lub tam, gdzie definiujesz prompt startowy), dodaj sekcję instrukcji dotyczącą **Synthetic Query Generation**.

**Fragment Promptu:**

Plaintext

YOUR GOAL: Help the user find the perfect product.

WHEN ANALYZING USER INPUT:  
1\. Extract HARD CONSTRAINTS (numbers, brands, specific attributes) into a JSON object \`structured\_filters\`.  
   \- E.g., "cheap" \-\> {"price\_tier": "low"} (if schema supports it) or map to explicit price range.  
   \- E.g., "Samsung" \-\> {"brand": "Samsung"}.  
   \- E.g., "not Lenovo" \-\> {"exclude\_brand": "Lenovo"}.

2\. Extract SOFT INTENT (usage context, abstract features, "vibe") into a string \`semantic\_query\`.  
   \- Transform the user's raw text into a descriptive search phrase aimed at technical specs.  
   \- Remove negations from this string (vectors handle negations poorly).  
   \- E.g., User: "I want a beast for gaming" \-\> Semantic Query: "high performance gaming laptop powerful GPU dedicated graphics cooling system"

OUTPUT FORMAT (JSON):  
{  
  "thought": "User wants a gaming laptop but excludes Lenovo. I will use hybrid search.",  
  "tool\_call": "graph\_search",  
  "tool\_arguments": {  
      "structured\_filters": {"exclude\_brand": "Lenovo", "category": "Laptop"},  
      "semantic\_query": "gaming high performance dedicated gpu high refresh rate screen"  
  }  
}

---

## **Faza 4: Weryfikacja i Testy**

*Cel: Upewnienie się, że system działa zgodnie z założeniami.*

### **4.1. Lista kontrolna wdrożenia**

1. \[ \] **Baza Danych:** Czy węzły ParentProduct mają właściwość embedding (tablica floatów)?  
2. \[ \] **Indeksy:** Czy polecenie SHOW INDEXES w Neo4j pokazuje 3 nowe indeksy wektorowe ze statusem ONLINE?  
3. \[ \] **Unit Test:** Czy wywołanie GraphSearchTool.search(semantic\_query="gaming", structured\_filters={"brand": "Asus"}) zwraca wyniki, które są *jednocześnie* marki Asus i są gamingowe?  
4. \[ \] **Edge Case:** Sprawdź negację. Zapytaj: "Laptop do gier, ale nie HP".  
   * Oczekiwane zachowanie: semantic\_query zawiera "gaming laptop", structured\_filters zawiera exclude\_brand: HP. Wyniki NIE zawierają HP.

### **4.2. Przykładowy scenariusz testowy (End-to-End)**

**Użytkownik:** "Szukam czegoś do oglądania Netflixa w podróży, tak do 2000 zł."

**Oczekiwane zachowanie systemu:**

1. **Orkiestrator:**  
   * structured\_filters: {"price\_max": 2000}  
   * semantic\_query: "tablet or lightweight laptop long battery life high resolution screen media consumption"  
2. **GraphSearchTool:**  
   * Wykonuje CALL db.index.vector... używając stringa semantycznego.  
   * Filtruje wyniki klauzulą WHERE node.price \<= 2000.  
3. **Wynik:** Lista tabletów lub lekkich laptopów w budżecie, które w opisie mają "długa bateria" lub "dobry ekran".

