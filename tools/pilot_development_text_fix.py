"""Compatibility entry point for the conversion tools."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'script_editor'))
from pilot_development import DESCRIPTIONS, fix_descriptions
