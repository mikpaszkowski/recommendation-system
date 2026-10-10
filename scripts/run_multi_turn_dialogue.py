"""
scripts/run_multi_turn_dialogue.py

Dedicated CLI harness demonstrating multi-turn conversational recommendation,
preference parsing, dialogue state accumulation, and canonical schema adherence.

Usage:
  # Automated demo mode (runs offline with mock parser if OPENAI_API_KEY is absent)
  python scripts/run_multi_turn_dialogue.py --demo

  # Interactive multi-turn CLI session
  python scripts/run_multi_turn_dialogue.py --interactive

  # Single utterance test
  python scripts/run_multi_turn_dialogue.py "I want a laptop under $1000"
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_preference_parser import main

if __name__ == "__main__":
    main()
