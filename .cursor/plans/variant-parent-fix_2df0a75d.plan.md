---
name: variant-parent-fix
overview: Refactor ingestion to build ParentProduct nodes from metadata, Products from reviews, and correct variant/review linkage.
todos:
  - id: schema-doc-update
    content: Update schema to parent-from-metadata, product-from-reviews, IS_VARIANT_OF, ABOUT_PRODUCT to parent fallback.
    status: completed
  - id: ingest-refactor
    content: Refactor sample_ingest to build ParentProduct from metadata, Products from reviews, IS_VARIANT_OF edges, review->parent fallback.
    status: completed
  - id: constraints-validations
    content: Adjust constraints and validation queries for parent/product split and IS_VARIANT_OF.
    status: completed
  - id: doc-note
    content: Note parent/variant ingestion change in pipeline doc.
    status: completed
---

# Parent/Variant Refactor Plan

- **schema-doc-update**: Align schema to create `ParentProduct` nodes from metadata, `Product` nodes from reviews, rename `VARIANT_OF` to `IS_VARIANT_OF`, and allow `ABOUT_PRODUCT` to target `ParentProduct` when no distinct variant exists.
- **ingest-refactor**: Change `sample_ingest.py` to:
- keep metadata `parent_asin` separate; create `ParentProduct` nodes with metadata, not `Product`.
- create `Product` nodes only from review ASINs.
- link `Product` → `ParentProduct` via `IS_VARIANT_OF` when `asin != parent_asin`; otherwise link review directly `ABOUT_PRODUCT` → `ParentProduct`.
- attach categories/brand/attributes to `ParentProduct`; optionally propagate to child `Product` if needed.
- **constraints-validations**: Update constraints for `ParentProduct` uniqueness; adjust validation queries to check `IS_VARIANT_OF` and `ABOUT_PRODUCT` -> `ParentProduct` cases.