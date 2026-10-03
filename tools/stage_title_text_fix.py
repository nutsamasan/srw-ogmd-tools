"""Compatibility entry point for the original conversion tools."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'script_editor'))
from stage_title_correction import fix_stage_titles
