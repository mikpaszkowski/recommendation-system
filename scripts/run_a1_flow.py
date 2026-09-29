import argparse
import json
import logging
import sys
from pathlib import Path

# Set up path so we can import src
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.llm_interface.preference_parser import LLMPreferenceParser
from src.tools.graph_search_tool import GraphSearchTool
from src.dialog_manager.session_adapter import extract_semantic_query, hard_constraints_to_structured_filters

def main():
    parser = argparse.ArgumentParser(description="Test A1 hybrid search flow end-to-end")
    parser.add_argument("query", type=str, help="User query to process (e.g., 'I want a powerful laptop for gaming under $2000')")
    parser.add_argument("--debug", action="store_true", help="Enable verbose DEBUG logging for all internal services")
    args = parser.parse_args()

    # Configure logging based on flag
    log_level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    logger = logging.getLogger("A1_FLOW_TEST")
    logger.info("Starting A1 Flow Test...")

    # 1. Parse Preferences
    print(f"\n==============================================")
    print(f"--- 1. Parsing Query: '{args.query}' ---")
    print(f"==============================================")
    pref_parser = LLMPreferenceParser()
    try:
        session_context = pref_parser.extract_preferences(args.query)
        print("✅ Extracted SessionContext payload:")
        
        # Handle both Pydantic models and fallback dictionaries
        if hasattr(session_context, "model_dump_json"):
            print(session_context.model_dump_json(indent=2))
        else:
            print(json.dumps(session_context, indent=2))
            
    except Exception as e:
        print(f"❌ Failed to parse preferences: {e}")
        return

    # 2. Convert to Filters
    print(f"\n==============================================")
    print("--- 2. Building Payload for Search Engine ---")
    print(f"==============================================")
    logger.debug("Calling extract_semantic_query()...")
    semantic_query = extract_semantic_query(session_context)
    
    logger.debug("Calling hard_constraints_to_structured_filters()...")
    structured_filters = hard_constraints_to_structured_filters(session_context)
    
    if not semantic_query and not structured_filters:
        print("⚠️ Warning: Empty extraction payload. Ensure your OPENAI_API_KEY is valid.")
        
    print(f"📝 Semantic Query (Vector): '{semantic_query}'")
    print(f"🎯 Structured Filters (Cypher): {json.dumps(structured_filters, indent=2)}")

    # Extract soft preferences for Additive Scoring
    soft_preferences = []
    try:
        if hasattr(session_context, 'soft_preferences'):
            soft_preferences = session_context.soft_preferences
        else:
            extracted = session_context.get("current_session_context", {}).get("extracted_parameters", {})
            soft_preferences = extracted.get("soft_preferences", [])
            # Convert to dicts if they are objects
            if soft_preferences and hasattr(soft_preferences[0], 'model_dump'):
                soft_preferences = [sp.model_dump() for sp in soft_preferences]
    except Exception as e:
        logger.warning(f"Could not extract soft preferences: {e}")

    # 3. Execute Search
    print(f"\n==============================================")
    print("--- 3. Executing Multi-Index Hybrid Search ---")
    print(f"==============================================")
    try:
        gst = GraphSearchTool()
        logger.debug(f"Calling GraphSearchTool.search() with semantic_query='{semantic_query}' and filters={structured_filters}")
        result = gst.search(semantic_query, structured_filters, limit=5, soft_preferences=soft_preferences)
        
        count = result.get('count', 0)
        print(f"\n✅ Search successful! Found {count} items.")
        
        for i, item in enumerate(result.get("items", [])):
            print(f"\n[{i+1}] {item.get('title')}")
            print(f"    Brand: {item.get('brand')}")
            print(f"    Price: ${item.get('price')}")
            print(f"    Category: {item.get('category')}")
            print(f"    Hybrid Score: {item.get('score'):.4f}")
            
            reasons = item.get("match_reasons")
            if reasons:
                print(f"    Match Reasons:")
                for r in reasons:
                    print(f"      - {r}")

        # 4. Fetch Attributes
        asins = [item.get("asin") for item in result.get("items", []) if item.get("asin")]
        if asins:
            print(f"\n==============================================")
            print("--- 4. Fetching Detailed Attributes ---")
            print(f"==============================================")
            attrs = gst.fetch_product_attributes(asins)
            
            for i, item in enumerate(result.get("items", [])):
                asin = item.get("asin")
                print(f"\n[{i+1}] {item.get('title')} (ASIN: {asin})")
                item_attrs = attrs.get(asin, [])
                
                # Group by source (attribute vs review)
                technical = [a for a in item_attrs if a.get('source') != 'user_review']
                reviews = [a for a in item_attrs if a.get('source') == 'user_review']
                
                print(f"  Technical Specs ({len(technical)}):")
                for tech in technical[:5]: # Show top 5 specs
                    print(f"    - {tech.get('name')}: {tech.get('value')}")
                if len(technical) > 5:
                    print(f"    - ... and {len(technical)-5} more.")
                    
                print(f"  User Reviews ({len(reviews)}):")
                for rev in reviews[:3]: # Show top 3 reviews
                    print(f"    - {rev.get('name')}")
    except Exception as e:
        print(f"❌ Graph Search Failed: {e}")
        logger.exception("GraphSearchTool execution threw an exception:")

if __name__ == "__main__":
    main()
