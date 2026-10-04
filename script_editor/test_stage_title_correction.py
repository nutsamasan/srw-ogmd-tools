"""Native title correction guards and automatic English edit integration."""
import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path
from core import Corpus, EditProject
from fixed_data import parse_fixed
from stage_title_correction import (ENTRY, BEFORE, AFTER, fix_stage_titles,
    fix_english_stage_titles, validate_release_fix)
from vendor.psarc import Psarc
from vendor import sdat
from patcher import prepare_patch, patch_archive_names

ROOT = Path(__file__).resolve().parents[1]


class StageTitleCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arc = Psarc(ROOT/'work/poc/full_release_20260910_v12/Logic.psarc')
        cls.source = cls.arc._read_file(next(e for e in cls.arc.entries if e.name == ENTRY))

    def test_native_titles_only_idempotence_and_structure_rejection(self):
        result, review = fix_stage_titles(self.source)
        self.assertEqual(len(review), 2)
        before, after = parse_fixed(self.source), parse_fixed(result)
        self.assertEqual(before.records, after.records)
        self.assertEqual(before.logical_indices, after.logical_indices)
        self.assertEqual(len(self.source), len(result))
        self.assertEqual(fix_stage_titles(result), (result, []))
        changed = {r['string_index'] for r in review}
        for index, text in enumerate(before.strings):
            self.assertEqual(after.strings[index], AFTER if index in changed else text)
        bad = bytearray(self.source); rp, _ = before.chunks[b'DATA']; bad[rp+12+61*20+8] ^= 1
        with self.assertRaises(ValueError): fix_stage_titles(bytes(bad))
        japanese = (ROOT/'work/extracted/ps3_logic/Dat/FixedData/StageData.dat').read_bytes()
        self.assertEqual(fix_english_stage_titles(japanese), (japanese, []))

    def test_release_guard(self):
        release = dict(stage_title_corrections=dict(entry=ENTRY, scenario=40, count=2, title=AFTER, table_sha256='a'*64))
        self.assertEqual(validate_release_fix(release)['count'], 2)
        for key, value in (('title', BEFORE), ('count', 1), ('table_sha256', 'bad')):
            invalid = copy.deepcopy(release); invalid['stage_title_corrections'][key] = value
            with self.assertRaises(ValueError): validate_release_fix(invalid)

    def test_english_patch_applies_titles_without_manual_project_edits(self):
        corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); target = root/'game/USRDIR/PSARC'; target.mkdir(parents=True)
            (target.parent.parent/'PARAM.SFO').write_bytes(b'BLJS10335')
            template = ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat'
            sdat.encrypt(self.arc.path, target/'Logic.psarc.sdat', template, verbose=False)
            project = EditProject(corpus, root/'project.json')
            manifest = prepare_patch(project, 'en', [target], root/'patch', backlog=False, keep_plain=True)
            doc = json.loads(manifest.read_text(encoding='utf8'))
            self.assertEqual(len(doc['review']), 3)
            self.assertEqual(doc['archives'][0]['verification']['changed_entries'], 1)
            self.assertEqual(patch_archive_names({}, False, 'en'), ['Logic'])
            self.assertEqual(patch_archive_names({}, False, 'jp'), [])
            patched = Psarc(root/'patch/Logic.patched.psarc')
            data = patched._read_file(next(e for e in patched.entries if e.name == ENTRY))
            self.assertEqual(data, fix_english_stage_titles(self.source)[0])
