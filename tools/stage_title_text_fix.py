"""Compatibility entry point for the original conversion tools."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'script_editor'))
from stage_title_correction import fix_stage_titles as fix_hagane_title
from gilliam_title_correction import fix_gilliam_title


def fix_stage_titles(source):
    result, review = fix_hagane_title(source)
    result, gilliam_review = fix_gilliam_title(result)
    return result, review + gilliam_review
