# Research Report: F1/F2 Graph State & Curated Subset

**Date**: 2026-07-11
**Requested by**: /implement pipeline
**Status**: Completed

## Executive Summary
This report covers Phase F1 (Live Graph Introspection) and Phase F2 (Amazon Dataset Curated Selection) from the Foundation Implementation Plan. The current Neo4j database was queried to understand the true distribution of data, and a script (`scripts/extract_curated_subset.py`) was developed and executed to identify a high-value subset of users and products.

## F1. Graph State Assessment
The Neo4j database (`amazon_electronics`) currently contains:
- **ParentProduct**: 51,876 nodes (all with embeddings)
- **Brand**: 16,004 nodes (all with embeddings)
- **Category**: 877 nodes (all with embeddings)
- **Attribute**: 527,063 nodes (all with embeddings)
- **Review**: 149,828 nodes
- **User**: 41,040 nodes

This scale is too large for rapid iteration and testing. 

## F2. Dataset Selection
A curated subset of exactly 30 users and 30 products was successfully extracted and saved to `datasets/curated/subset_selection.json`. 

**Selection Criteria Met:**
- **Top 25 Users**: Selected by highest review count (e.g. `AFTZWAK3ZHAPCNSOT5GCKQDECBTQ` with 819 reviews).
- **Bottom 5 Users**: Selected by lowest review count (1 review).
- **Top 25 Products**: Selected by highest review count (e.g. `B01G8JO5F2` with 3209 reviews).
- **Bottom 5 Products**: Selected explicitly as products with 0 reviews.

## Next Steps (F3)
The next phase is to write a targeted ingestion script (`scripts/ingest_curated_subset.py`) that reads the raw Amazon JSONL/CSV files but **only** ingests nodes and relationships that belong to the `subset_selection.json` list. This will yield a lightweight, lightning-fast graph DB (`kg_curated`) for Phase 1-3 testing.
