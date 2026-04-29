#!/usr/bin/env python3
"""Entry point for the proof pipeline. See pipeline/orchestrator.py for implementation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.orchestrator import main

if __name__ == "__main__":
    main()
