

# **Architectural Design: Knowledge Graph Pipeline for an E-commerce Conversational Recommender System**

## **I. Introduction: Establishing the Knowledge Graph Strategy**

Current recommender systems are evolving from standard, single-shot interactions (based on entity ID exchange) toward holistic conversational recommender systems (CRS).1 A holistic CRS engages in multi-turn, natural language dialogue, seeking to understand complex and even unexpected user intentions to deliver relevant recommendations.1

However, relying solely on Large Language Models (LLMs) as the recommendation engine introduces two critical challenges 1:

1. **Item Space Discrepancy:** LLMs, trained on general web data, often recommend products that are not in the target e-commerce catalog, leading to user frustration.1  
2. **Item Information Negligence:** LLMs lack access to information about interdependencies (e.g., collaborative patterns, purchase sequences) or specific item attributes. They operate primarily based on processing the dialogue context.1

To address these challenges, we propose an architecture in which a Knowledge Graph (KG) serves as the central "domain expert" 1 and "memory" for the CRS. This KG will ground the LLM in domain-specific data, ensuring that recommendations are accurate, relevant to the catalog, and, most importantly, explainable.

This document presents the design of the foundational pipeline for building and implementing such a Knowledge Graph, utilizing the Amazon Reviews '23 dataset. A key assumption of this design is strategic planning for future expansion with advanced AI modules, including GNN (Graph Neural Networks) embeddings.1 KG-LLM modality fusion 1, and GraphRAG (Retrieval-Augmented Generation)-style path reasoning.1

## **II. Input Data Analysis (Amazon Reviews '23)**

The foundation of our KG consists of two distinct but related data sources from the Amazon Reviews '23 dataset.

### **Source 1: Review Data (reviews.json)**

These files represent user *events* and *behaviors*. They provide transactional data and, crucially, the text data necessary to understand *implicit preferences*.1 Key fields include 2:

* user\_id: The reviewer's identifier.  
* asin: The identifier of the reviewed product.  
* rating: The rating (1.0-5.0), an explicit preference signal.  
* text: The review text, the primary source of implicit preferences (e.g., "battery life is short").  
* timestamp: When the event occurred.  
* verified\_purchase: An indicator confirming an actual purchase.  
* helpful\_votes: A metric for the quality/impact of the review.  
* images: A list of user-uploaded images; this represents a future data modality for analysis (e.g., visual defect recognition).

### **Source 2: Product Metadata (metadata.json)**

These files represent the product *catalog*. They provide structured attributes for the Product entity. Key fields include 3:

* asin: The primary product identifier (primary key).  
* title: The product name.  
* price: The product price.  
* brand: The brand (an important attribute for filtering).  
* categories: A list of category hierarchies (e.g., \[\['Electronics', 'Computers & Accessories', 'Laptops'\]\]). This requires normalization.  
* features: A list of bulleted features (e.g., "16GB RAM"). This requires normalization.  
* details: A dictionary (JSON) of key/value attributes (e.g., "Screen Size": "15.6 Inches"). This requires normalization.  
* bought\_together: A list of asins for products frequently bought together; this is a pre-calculated collaborative relationship.

## **III. Knowledge Graph Schema Design (Data Model)**

The schema strategy is the most critical architectural decision. The proposed model is intentionally more complex than a simple (User)--\>(Product) graph to strategically support future AI goals.

### **Strategic Design Rationale**

A key design decision is to treat the **Review (Review) as a central event node** rather than just a property of a relationship.1 Instead of a simple bipartite model, we implement a (User)--\>(Review)--\>(Product) model. This approach, combined with the normalization of attributes (Feature) and categories (Category) as distinct nodes, directly enables our advanced objectives:

1. **For GNN Embeddings (Goal \#1):** It creates a rich, heterogeneous graph (multiple node and relation types), which is ideal for R-GCN (Relational Graph Convolutional Networks) models that learn different weights for different relationship types.1  
2. **For Bridging the Modality Gap (MIM, Goal \#2):** The Review node becomes the ideal "anchor" for fusion. It allows the MIM (Mutual Information Maximization) process 1 to learn the semantic alignment between the graph embedding of the Review node (from R-GCN) and the text embedding of its text property (from an LLM).  
3. **For the COMPASS Alternative (GraphRAG, Goal \#3):** It enables path reasoning 1 that returns rich subgraphs (e.g., product \-\> review \-\> feature \-\> another product) as context for RAG 1, rather than just a list of product IDs.

### **Table 1: Knowledge Graph Schema Definition**

The following table constitutes the formal specification for implementing the data model in Neo4j.1

| Node Label | Key Properties | Data Source (Data Source) | Description |
| :---- | :---- | :---- | :---- |
| **User** | user\_id (String, UNIQUE) | Reviews 2 | Represents the customer / reviewer. |
| **Product** | asin (String, UNIQUE), parent\_asin (String), title (String), price (Float), brand (String), description (String), avg\_rating (Float, *calculated*) | Metadata 3 | Represents a product (Amazon Standard ID). |
| **Review** | review\_id (String, UNIQUE \- *generated*), rating (Float), text (String), timestamp (Datetime), verified\_purchase (Boolean), helpful\_votes (Integer), image\_urls (List) | Reviews 2 | The central event node, modeling the act of reviewing. |
| **Category** | category\_name (String, UNIQUE) | Metadata (categories) 3 | A node for product category hierarchies. |
| **Feature** | feature\_name (String, UNIQUE) | Metadata (details, features) 3, Reviews (text) \[1, 1\] | A normalized attribute node (e.g., "Brand:Apple", "battery life"). |

| Relationship Type (Edge Type) | Start Node | End Node | Properties | Data Source | Description |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **WROTE** | User | Review |  | Reviews 2 | Connects a user to the review they wrote. |
| **REVIEWS** | Review | Product |  | Reviews 2 | Connects a review to the product it is about. |
| **MENTIONS\_FEATURE** | Review | Feature | sentiment (Float, *calculated*) | NLP on Review.text \[1, 1\] | Connects a review to attributes it mentions (implicit preferences). |
| **HAS\_FEATURE** | Product | Feature | value (String) | Metadata (details, features) 3 | Connects a product to its explicit attributes (specs). |
| **PART\_OF** | Product | Category |  | Metadata (categories) 3 | Assigns a product to its category. |
| **SUB\_CATEGORY\_OF** | Category | Category |  | Metadata (categories) 7 | Models the category hierarchy (e.g., 'Laptop' SUB\_CATEGORY\_OF 'Electronics'). |
| **BOUGHT\_TOGETHER** | Product | Product |  | Metadata (bought\_together) 3 | Pre-computed co-purchase relationship. |
| **PURCHASED** | User | Product | timestamp (Datetime) | Reviews (verified\_purchase) 2 | (Optional) A direct purchase relationship for easier queries. |

## **IV. Data Ingestion Pipeline Architecture (ETL)**

We propose a dual-modal architecture (similar to RAG 1) capable of (1) a one-time, massive Batch Ingestion for the historical '23 dataset and (2) a Stream Ingestion pipeline to handle new, incoming reviews and catalog updates in real-time.

### **Core Technologies**

* **Graph Database:** Neo4j AuraDB.1 Choosing a managed cloud service eliminates the operational burden of cluster management, allowing the team to focus on the data model and application logic.  
* **Batch Processing:** Apache Spark (running on a platform like Databricks or AWS EMR) for massive parallel processing of JSON files.  
* **Stream Processing:** Apache Kafka (for "new review" events) and Spark Streaming or Flink (for micro-batch processing) to keep the graph "alive."  
* **Feature Extraction (NLP):** Use of LLM models (via API or hosted open-source models) for entity extraction and sentiment analysis from Review.text, following methods described in CRS research \[1, 1\].

### **Process 1: Batch Ingestion (Initial '23 Backfill)**

This is a one-time process to load the historical dataset.

**Step 1\. Load Metadata (Products, Categories, Attributes)**

1. **Load Data:** Load the metadata.json files 3 into a Spark DataFrame.  
2. **Create Product Nodes:** Extract asin, title, price, brand, etc. Load this data into Neo4j as (:Product) nodes. For large volumes, using the neo4j-admin database import tool (requires instance access) or LOAD CSV 10 is recommended for optimal performance.1  
3. **Create Feature Nodes:** Apply a Spark UDF (User-Defined Function) to the details (dictionary) and features (list) fields.3 Normalize these attributes (e.g., "Brand:Apple", "Screen Size:6.1 inches", "16GB RAM") into unique entities.12 Create (:Feature) nodes and (Product)--\>(Feature) relationships.  
4. **Create Category Hierarchy:** Apply a UDF to the categories (list of lists) field.3 Process these lists to build a unique set of (:Category) nodes, (Product)--\>(Category) relationships, and, crucially, (Category)--\>(Category) relationships to model the hierarchy.7  
5. **Create BOUGHT\_TOGETHER Relationships:** Process the bought\_together field.3 For each asin in the list, create a (Product {asin: src\_asin})--\>(Product {asin: target\_asin}) relationship.14

**Step 2\. Load Reviews (Users, Reviews, Implicit Features)**

1. **Load Data:** Load the review JSON files 2 into a Spark DataFrame.  
2. **Create User and Review Nodes:** Extract user\_id, asin, rating, text, timestamp, images, etc. Create (or MERGE) (:User) nodes. Create (:Review) nodes (with a unique ID generated from a hash of text and timestamp, for example).  
3. **Create Core Relationships:** Create (User)--\>(Review) and (Review)--\>(Product {asin: row.asin}) relationships.  
4. NLP/LLM Step (Key for CRS): In parallel, apply an NLP/LLM model 1 to the Review.text column. This model must perform two tasks:  
   a. Aspect Extraction: Extract key features/aspects (e.g., "battery life," "screen quality," "size").1  
   b. Sentiment Analysis: Determine the sentiment (e.g., $score \\in \[-1.0, 1.0\]$) for each extracted aspect.  
5. **Create Implicit Relationships:** For each (aspect, sentiment) pair, MERGE with the existing (:Feature {feature\_name: "battery life"}) node and create a (Review)--\>(Feature {sentiment: \-0.8}) relationship.

### **Process 2: Stream Ingestion (Maintaining a "Living" Graph)**

The goal is to enable the CRS to recommend based on the latest trends and reviews (e.g., "this phone just started having battery issues").

1. **Event Source:** E-commerce front-end systems should publish events (e.g., new\_review\_created, product\_metadata\_updated) to an Apache Kafka topic.  
2. **Stream Processing:** A Spark Streaming or Flink job listens to this topic.  
3. **Processing Logic:**  
   * For new\_review\_created: The application performs the *same* NLP Step 2 as in the batch process, but for a single record. It then uses a Cypher MERGE transaction 1 to safely add the new (:Review) node and its associated relationships (WROTE, REVIEWS, MENTIONS\_FEATURE) to the graph.  
   * For product\_metadata\_updated: The application sends a MERGE transaction to update properties (e.g., price) on the existing (:Product) node.

### **Database Management (Critical for Performance)**

CRS query performance depends on quickly finding starting points in the graph.15 The following indexes and uniqueness constraints must be created immediately 18:

Cypher

// Uniqueness constraints automatically create B-tree indexes  
CREATE CONSTRAINT user\_id\_unique IF NOT EXISTS FOR (u:User) REQUIRE u.user\_id IS UNIQUE;  
CREATE CONSTRAINT asin\_unique IF NOT EXISTS FOR (p:Product) REQUIRE p.asin IS UNIQUE;  
CREATE CONSTRAINT category\_name\_unique IF NOT EXISTS FOR (c:Category) REQUIRE c.category\_name IS UNIQUE;  
CREATE CONSTRAINT feature\_name\_unique IF NOT EXISTS FOR (f:Feature) REQUIRE f.feature\_name IS UNIQUE;

// Range indexes for frequently filtered properties  
CREATE INDEX review\_timestamp IF NOT EXISTS FOR (r:Review) ON (r.timestamp);  
CREATE INDEX product\_price IF NOT EXISTS FOR (p:Product) ON (p.price);  
CREATE INDEX product\_brand IF NOT EXISTS FOR (p:Product) ON (p.brand);

## **V. Designing for the Future: Integrating Advanced AI Modules**

The schema from Section III was designed specifically to facilitate the implementation of the three advanced AI modules requested by the user.

### **Goal \#1: Generating Graph Embeddings (GNN \- R-GCN / FastRP)**

* **Problem:** Standard collaborative filtering fails with sparse data (cold start). GNN Embeddings 1 learn vector representations of nodes based on their neighborhood and graph structure, capturing complex patterns.  
* **Implementation Strategy:**  
  1. **Schema Fit:** Our rich, heterogeneous schema is ideal for **Relational-GCN (R-GCN)** 1, which learns distinct weight matrices for each relationship type (e.g., WROTE is treated differently than BOUGHT\_TOGETHER). Alternatively, algorithms like **FastRP** 21 can be used for rapid embedding generation on large graphs.22  
  2. GNN Pipeline: Using the Neo4j Graph Data Science (GDS) library, a pipeline can be defined that periodically (e.g., nightly):  
     a. Projects an in-memory graph.  
     b. Runs an embedding algorithm (e.g., FastRP or R-GCN).  
     c. Writes the generated embeddings (vectors) back to the graph as new properties: User.embedding\_gnn and Product.embedding\_gnn.  
  3. **Use in CRS:** The CRS can now perform ultra-fast similarity queries (k-Nearest Neighbors) on these embedded vectors to find similar users or products, serving as a powerful candidate generation engine.

### **Goal \#2: Bridging the Modality Gap (KG-LLM Fusion via MIM)**

* **Problem:** The "semantic gap" \[1, 1\]. A user's query in a CRS is in *natural language* (LLM embeddings), while the database is a *graph* (GNN embeddings). The system must understand that the query "I'm looking for something durable" corresponds to the (:Feature {feature\_name: "durability"}) node in the graph.  
* Implementation Strategy (based on KECR 1):  
  1. Key Schema Element: Our (:Review) node is the perfect "anchor" for modality fusion. It possesses both:  
     a. Structural context (links to User and Product).  
     b. Textual context (the Review.text property).  
  2. Alignment Process: We use the Mutual Information Maximization (MIM) technique \[1, 1\]. We train a model that maximizes the mutual information (MI) between:  
     a. The GNN embedding of the Review node (structural representation).  
     b. The LLM/BERT embedding of its text property (textual representation).  
  3. **Use in CRS:** The result is a *shared embedding space*. When a user in dialogue says "I want a phone with a good camera," we embed this query using the LLM and find the nearest neighbor in this shared space. The result might be a Feature or Review node that *semantically* corresponds to "good camera," allowing the CRS to understand implicit intent.1

### **Goal \#3: COMPASS Alternative / Graph-to-Text Adapter (GraphRAG)**

* **Problem:** LLMs in CRS suffer from "item information negligence" 1 and hallucinate. Regular RAG (Retrieval-Augmented Generation) retrieves text "chunks," which is insufficient. We need **GraphRAG** 1 to provide the LLM with structured, rich context.  
* **Implementation Strategy:**  
  1. **Graph as RAG Index:** We use the KG as an intelligent, structured index 1, replacing flat vector databases.  
  2. Process (Path Reasoning 1):  
     a. A CRS user says: "I liked Product X, but I need something cheaper with better battery."  
     b. Cypher Query (Multi-hop): The Dialogue Management module 1 translates this into a complex Cypher query that performs path reasoning 1:  
     \`\`\`cypher  
     // Identify the base product  
     MATCH (p1:Product {asin: "X"})  
     // Find candidates:  
     // 1\. Bought together OR 2\. Share key features  
     CALL {  
         MATCH (p1)--\>(p2:Product) RETURN p2  
         UNION  
         MATCH (p1)--(f:Feature)--(p2:Product) RETURN p2  
     }  
     // Apply attribute filter (explicit preference)  
     WHERE p2.price \< p1.price

     // Infer from reviews (implicit preference)  
     // Find products with positive reviews for "battery"  
     MATCH (p2)\<--(r:Review)--\>(f\_batt:Feature)  
     WHERE f\_batt.feature\_name CONTAINS 'battery'  
       AND r.rating \>= 4.0   
       AND m.sentiment \> 0.5

     // Return subgraph as context  
     RETURN p2.title AS recommended\_product,   
            r.text AS supporting\_review,   
            f\_batt.feature\_name AS matched\_feature  
     LIMIT 5  
     \`\`\`

  3. Graph-to-Text Adapter \[1, 1\]: Instead of just returning p2.title, we retrieve this rich subgraph. An "adapter" (a serialization module) turns this subgraph into concise text:  
     "Product: 'Product Y' is often bought together with 'Product X' and is cheaper. It also has the feature 'battery life'. One review (Rating: 5.0) confirms: '...amazing battery life, lasts all day...'. "  
  4. **Use in CRS:** This generated text is injected as RAG context into the LLM.1 The LLM then generates a fluent, conversational response that is *grounded* in the graph data, *explainable*, and *contextual*. This solves the "item space discrepancy" 1 because the LLM is only talking about items retrieved from *our* KG.

## **VI. Conclusion and Architectural Recommendations**

### **Summary of Decisions**

This design emphasizes a strategic knowledge graph schema that treats **reviews** and **features** as first-class entities. This departure from simple (User)--\>(Product) e-commerce models is a key architectural decision that directly unlocks the required advanced conversational AI capabilities. The proposed ETL pipeline is robust, blending the performance of Spark batch processing with the reactivity of Kafka stream processing.

### **Implementation Recommendations**

It is recommended to implement this architecture in three strategic phases:

1. **Phase 1 (Foundation):** Immediately begin implementation of the **batch pipeline** (Section IV, Process 1\) and the **graph schema** (Section III) in a Neo4j AuraDB instance.1 In parallel, the **NLP/LLM module** for feature and sentiment extraction from Review.text must be developed and tested.1  
2. **Phase 2 (Maintenance & Basic CRS):** Deploy the **stream pipeline** (Section IV, Process 2\) to ensure data freshness. Integrate a basic CRS 1 that uses simple, rule-based Cypher queries (e.g., BOUGHT\_TOGETHER, PART\_OF) for candidate generation.  
3. **Phase 3 (Advanced AI):** Begin R\&D on the advanced modules (Section V). Start with **GNN Embedding Generation (Goal \#1)**, as the resulting embeddings (e.g., Product.embedding\_gnn) are a necessary input for the MIM modules (Goal \#2) and improve queries in GraphRAG (Goal \#3).

The proposed architecture is not just a data store; it is a flexible, AI-ready reasoning system that will evolve with the growing capabilities of our conversational recommender system.

#### **Cytowane prace**

1. \[Survey\] Holistic Conversational Rec Sys.pdf  
2. Amazon reviews 2023 \- Kaggle, otwierano: listopada 9, 2025, [https://www.kaggle.com/datasets/ravirajbabasomane/amazon-reviews-2023](https://www.kaggle.com/datasets/ravirajbabasomane/amazon-reviews-2023)  
3. Amazon Reviews 2023, otwierano: listopada 9, 2025, [https://amazon-reviews-2023.github.io/](https://amazon-reviews-2023.github.io/)  
4. Amazon review data, otwierano: listopada 9, 2025, [https://jmcauley.ucsd.edu/data/amazon/](https://jmcauley.ucsd.edu/data/amazon/)  
5. Amazon Review Data (2018) \- Jianmo Ni, otwierano: listopada 9, 2025, [https://nijianmo.github.io/amazon/](https://nijianmo.github.io/amazon/)  
6. Graphs to Graph Neural Networks: From Fundamentals to Applications — Part 2b: Knowledge Graphs | by Isaac Kargar, otwierano: listopada 9, 2025, [https://kargarisaac.medium.com/graphs-to-graph-neural-networks-from-fundamentals-to-applications-part-2b-knowledge-graphs-841f21dca7c3](https://kargarisaac.medium.com/graphs-to-graph-neural-networks-from-fundamentals-to-applications-part-2b-knowledge-graphs-841f21dca7c3)  
7. Modeling Categories in a Graph Database \- Neo4j, otwierano: listopada 9, 2025, [https://neo4j.com/blog/developer/modeling-categories-in-a-graph-database/](https://neo4j.com/blog/developer/modeling-categories-in-a-graph-database/)  
8. otwierano: listopada 9, 2025, [https://neo4j.com/docs/aura/classic/auradb/getting-started/create-database/](https://neo4j.com/docs/aura/classic/auradb/getting-started/create-database/)  
9. Create an instance \- Neo4j Aura, otwierano: listopada 9, 2025, [https://neo4j.com/docs/aura/getting-started/create-instance/](https://neo4j.com/docs/aura/getting-started/create-instance/)  
10. Importing data \- Operations Manual \- Neo4j, otwierano: listopada 9, 2025, [https://neo4j.com/docs/operations-manual/current/tutorial/neo4j-admin-import/](https://neo4j.com/docs/operations-manual/current/tutorial/neo4j-admin-import/)  
11. Tutorial: Import data \- Getting Started \- Neo4j, otwierano: listopada 9, 2025, [https://neo4j.com/docs/getting-started/cypher-intro/load-csv/](https://neo4j.com/docs/getting-started/cypher-intro/load-csv/)  
12. Product attributes db structure for e-commerce \- sql \- Stack Overflow, otwierano: listopada 9, 2025, [https://stackoverflow.com/questions/60384704/product-attributes-db-structure-for-e-commerce](https://stackoverflow.com/questions/60384704/product-attributes-db-structure-for-e-commerce)  
13. Working with Hierarchical Trees in Neo4j \- graphgists, otwierano: listopada 9, 2025, [https://neo4j.com/graphgists/my-bea/](https://neo4j.com/graphgists/my-bea/)  
14. Mapping \- Neo4j Data Importer, otwierano: listopada 9, 2025, [https://neo4j.com/docs/data-importer/current/mapping/](https://neo4j.com/docs/data-importer/current/mapping/)  
15. Search-performance indexes \- Cypher Manual \- Neo4j, otwierano: listopada 9, 2025, [https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/](https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/)  
16. The impact of indexes on query performance \- Cypher Manual \- Neo4j, otwierano: listopada 9, 2025, [https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/using-indexes/](https://neo4j.com/docs/cypher-manual/current/indexes/search-performance-indexes/using-indexes/)  
17. Why graph indexing is important \- Newbie Questions \- Neo4j Online Community, otwierano: listopada 9, 2025, [https://community.neo4j.com/t/why-graph-indexing-is-important/10604](https://community.neo4j.com/t/why-graph-indexing-is-important/10604)  
18. Indexes \- Cypher Manual \- Neo4j, otwierano: listopada 9, 2025, [https://neo4j.com/docs/cypher-manual/3.5/schema/indexes/](https://neo4j.com/docs/cypher-manual/3.5/schema/indexes/)  
19. Using Indexes \- Using Indexes and Query Best Practices in Neo4j 4.x, otwierano: listopada 9, 2025, [https://neo4j.com/graphacademy/training-best-practices-40/02-best-practices40-using-indexes/](https://neo4j.com/graphacademy/training-best-practices-40/02-best-practices40-using-indexes/)  
20. \# Neo4j Tutorial: Comprehensive Guide to Neo4j Indexing \- DEV Community, otwierano: listopada 9, 2025, [https://dev.to/mangesh28/-comprehensive-guide-to-neo4j-indexing-current-best-practices-2b48](https://dev.to/mangesh28/-comprehensive-guide-to-neo4j-indexing-current-best-practices-2b48)  
21. Fast Random Projection \- Neo4j Graph Data Science, otwierano: listopada 9, 2025, [https://neo4j.com/docs/graph-data-science/current/machine-learning/node-embeddings/fastrp/](https://neo4j.com/docs/graph-data-science/current/machine-learning/node-embeddings/fastrp/)  
22. Getting Started with Graph Embeddings | Towards Data Science, otwierano: listopada 9, 2025, [https://towardsdatascience.com/getting-started-with-graph-embeddings-2f06030e97ae/](https://towardsdatascience.com/getting-started-with-graph-embeddings-2f06030e97ae/)  
23. The Complete Cypher Cheat Sheet \- Memgraph, otwierano: listopada 9, 2025, [https://memgraph.com/blog/cypher-cheat-sheet](https://memgraph.com/blog/cypher-cheat-sheet)  
24. Neo4j query multiple hops \- Stack Overflow, otwierano: listopada 9, 2025, [https://stackoverflow.com/questions/48892383/neo4j-query-multiple-hops](https://stackoverflow.com/questions/48892383/neo4j-query-multiple-hops)