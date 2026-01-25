"""
Quick harness to exercise the preference parser agent.

Usage:
  OPENAI_API_KEY=... python scripts/run_preference_parser.py
"""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so `src` imports resolve
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    # from src.llm_interface.prompts import preference_extract_prompt
    from src.llm_interface.preference_parser import LLMPreferenceParser

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set. Please export it before running.")
        sys.exit(1)

    # default_text = "I am looking for a new laptop with 14' screen size, at least 16GB of RAM and a price range of $1000 - $1500."
    default_text = """
                    - User: I want to buy a new laptop with 14' screen size, at least 16GB of RAM and a price range of $1000 - $1500.
                    - Assistant: Are you looking for a specific type of laptop?
                    - User: Yes, I am looking for a laptop with 14' screen size, at least 16GB of RAM and a price range of $1000 - $1500.
                    - Assistant: Sure, I will find you the best laptop with 14' screen size, at least 16GB of RAM and a price range of $1000 - $1500.
    """
    parser_agent = LLMPreferenceParser()
    preferences = parser_agent.extract_preferences(default_text)
    print("=== Input ===")
    print(default_text)
    print("=== Extracted Preferences ===")
    print(preferences)


if __name__ == "__main__":
    main()

