"""Execute both native measurement and drawing paths for the corrected words."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'script_editor'), str(ROOT/'work/analysis_pydeps')]
from core import NativeMetrics
from build_apostrophe_text_fix import normalize
import verify_ogmd_line_measurement as measure
from build_ogmd_apostrophe_patch import compile_hooks
from trace_battle_glyphs import trace


def verify():
    out = ROOT/'work/poc/apostrophe_text_fix_20260922'
    metrics = NativeMetrics(ROOT/'script_editor/assets/font.bin')
    compiled = compile_hooks()
    measure.compile_hooks = lambda: compiled
    elf = (ROOT/'work/poc/battle_caption_path_fix_20260920_v2/EBOOT.elf').read_bytes()
    rows = []
    for name, text in [('reported', 'I\u2019ve'), ('same_stage', 'isn\u2019t'),
                       ('battle_24', 'it\u2018s'), ('battle_40', 'I\u2018ll')]:
        fixed = normalize(text)
        for cell in (24, 32):
            values = {}
            for title, value in [('before', text), ('after', fixed)]:
                widths = [measure.measure(value, entry, 'v3', cell=cell, maximum=0xffffffff)
                          for entry in (0xb7f808, 0xb7fc20)]
                assert widths == [metrics.width(value, cell)]*2
                glyphs = [trace(value, cell=cell, maximum=-1, cached=0, elf=elf,
                                unbounded=unbounded, x=0, y=0) for unbounded in (False, True)]
                assert all(abs(g['advance']-widths[0]) < 0.001 for g in glyphs)
                values[title] = dict(text=value, measurements=widths,
                                     draw_advances=[g['advance'] for g in glyphs],
                                     glyph_x=[g['quads'] for g in glyphs])
            assert abs(values['before']['measurements'][0]-values['after']['measurements'][0]-cell*19/32) < 0.001
            rows.append(dict(case=name, cell=cell, **values))
            print(name, cell, 'width', values['before']['measurements'][0],
                  '->', values['after']['measurements'][0], flush=True)
    for text in ['\u2018word\u2019', '\u300c\u65e5\u672c\u8a9e\u300d', "don't", 'A\u2019 B', 'A \u2019B']:
        assert normalize(text) == text
    result = dict(status='passed', measurement_executions=32, glyph_loop_executions=32,
                  cases=rows, real_game_visual_test=False,
                  text_changed_only_between_ASCII_letters=True)
    (out/'native_spacing_verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')


if __name__ == '__main__':
    verify()
