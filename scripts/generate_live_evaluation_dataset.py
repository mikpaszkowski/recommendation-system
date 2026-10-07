#!/usr/bin/env python3
"""
CLI Script to generate live Neo4j ground-truth evaluation datasets (Feature F5).
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.extract_live_eval_dataset import main

if __name__ == "__main__":
    main()
