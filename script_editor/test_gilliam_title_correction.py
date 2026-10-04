"""Native byte boundaries, strict mapping guards, and existing-edit compatibility."""
import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path
from core import Corpus, EditProject, sha
from fixed_data import parse_fixed
from gilliam_title_correction import ENTRY, BEFORE, AFTER, fix_gilliam_title, validate_release_fix
from stage_title_correction import fix_english_stage_titles, fix_stage_titles
from title_cards import CardCatalog, CardProject
from vendor.psarc import Psarc

ROOT = Path(__file__).resolve().parents[1]


class GilliamTitleCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        arc = Psarc(ROOT/'work/poc/full_release_20260910_v12/Logic.psarc')
        cls.source = arc._read_file(next(e for e in arc.entries if e.name == ENTRY))

    def test_shared_title_slot_and_exact_byte_boundaries(self):
        result, review = fix_gilliam_title(self.source)
        self.assertEqual(len(review), 1)
        before, after = parse_fixed(self.source), parse_fixed(result)
        self.assertEqual(before.records, after.records)
        self.assertEqual(before.logical_indices, after.logical_indices)
        self.assertEqual(len(result), len(self.source))
        self.assertEqual(fix_gilliam_title(result), (result, []))
        row = before.records[before.logical_indices[21]]
        self.assertEqual(row[3], row[5])
        index = row[3]
        self.assertEqual(after.strings, [AFTER if i == index else text for i, text in enumerate(before.strings)])
        sp, ss = before.chunks[b'SOFS']; tp, _ = before.chunks[b'STRI']
        offset = struct.unpack_from(f'>{ss//4}I', self.source, sp+8)[index]
        start = tp+12+offset
        allowed = set(range(start+2, start+4)) | set(range(start+6, start+6+len(BEFORE)+1))
        self.assertTrue(all(i in allowed for i, (a,b) in enumerate(zip(self.source,result)) if a != b))
        bad = bytearray(self.source); rp, _ = before.chunks[b'DATA']; bad[rp+12+32*20+8] ^= 1
        with self.assertRaises(ValueError): fix_gilliam_title(bytes(bad))
        japanese = (ROOT/'work/extracted/ps3_logic/Dat/FixedData/StageData.dat').read_bytes()
        self.assertEqual(fix_english_stage_titles(japanese), (japanese, []))
        combined, all_review = fix_english_stage_titles(self.source)
        self.assertEqual(len(all_review), 3)
        self.assertEqual(fix_english_stage_titles(combined), (combined, []))
        self.assertEqual(combined, fix_gilliam_title(fix_stage_titles(self.source)[0])[0])

    def test_display_labels_preserve_saved_source_fingerprints(self):
        corpus = Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
        key = '01_Stages/Stage_21_Common_S021_GUILLIAM_S_UNDERTAKING'
        doc, digest = corpus.load(key)
        self.assertIn(AFTER, corpus.by_key[key]['title'])
        self.assertEqual(doc['metadata']['title_en'], AFTER)
        self.assertEqual(digest, sha((corpus.root/key/'script.json').read_bytes()))
        locations, location_digest = corpus.load('07_Location_banners/Locations')
        self.assertTrue(any(AFTER in r.get('label_en','') for r in locations['rows']))
        self.assertFalse(any(BEFORE in r.get('label_en','') for r in locations['rows']))
        with tempfile.TemporaryDirectory() as temp:
            project = EditProject(corpus, Path(temp)/'project.json')
            row = next(r for r in doc['rows'] if r.get('en'))
            project.set(key, row, 'en', 'A saved Gilliam-stage correction.'); project.save()
            self.assertEqual(EditProject(Corpus(corpus.root), project.path).values(key,row)['en'], 'A saved Gilliam-stage correction.')
            library = CardCatalog()
            original_identity = sha(__import__('zipfile').ZipFile(library.path).read('catalog.json'))
            self.assertEqual(library.identity, original_identity)
            self.assertIn(AFTER, library.card('st_021')['label'])
            CardProject(Path(temp)/'cards.json',library)
            self.assertEqual(sha(library.native('st_021',library.source_png('st_021','en'))), 'e20889d1861fed6a47788a67a15c65c2322f2747249525da815afd2e48636dd7')

    def test_release_validation(self):
        release = dict(gilliam_stage_title_correction=dict(entry=ENTRY,scenario=21,count=1,title=AFTER,table_sha256='a'*64))
        validate_release_fix(release)
        for key, value in [('scenario',40),('count',2),('title',BEFORE),('table_sha256','bad')]:
            invalid = copy.deepcopy(release);invalid['gilliam_stage_title_correction'][key]=value
            with self.assertRaises(ValueError): validate_release_fix(invalid)
