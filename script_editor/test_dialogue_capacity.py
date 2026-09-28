"""Regression for a full dialogue pool with shared and unknown index users."""
import struct
import unittest
from native_formats import patch_ldbi,parse_ldbi_table,read_cstring,_dialogue_pool,align

class DialogueCapacityTests(unittest.TestCase):
    def test_full_pool_keeps_all_text_and_command_offsets(self):
        texts=['日本語'*17+' END','語 END','old'];boundary=640;start=768
        source=bytearray(1280);source[:4]=b'LDBI'
        payload,offsets=_dialogue_pool(texts);table=align(128+len(payload))
        for offset,value in [(4,1000),(12,3),(20,table),(28,boundary),(32,2),(36,start)]:struct.pack_into('>I',source,offset,value)
        source[128:128+len(payload)]=payload;struct.pack_into('>3I',source,table,*offsets)
        # An unknown/control reference and an unedited dialogue both use slot 2.
        struct.pack_into('>I',source,boundary+4,2)
        for command in range(2):
            struct.pack_into('>II',source,start+command*196+12,1,2)
        replacement='A'*140+texts[0]
        unshared,_=_dialogue_pool(texts+[replacement])
        self.assertGreater(align(128+len(unshared))+4*4,boundary)
        result=patch_ldbi(bytes(source),[(0,'text',replacement)])
        self.assertEqual(len(source),len(result));self.assertEqual(result[28:128],source[28:128])
        self.assertEqual(result[boundary:start],source[boundary:start])
        self.assertEqual(result[start+196:],source[start+196:])
        new=parse_ldbi_table(result)[2];values=[read_cstring(result,p) for p in new]
        self.assertEqual(values,texts+[replacement])
        self.assertEqual(values[struct.unpack_from('>I',result,start+16)[0]],replacement)
        # These original UTF-8 strings now point to suffixes inside the new one.
        self.assertGreater(new[0],new[3]);self.assertGreater(new[1],new[0])
        again=patch_ldbi(result,[(1,'text','More '+replacement)])
        offsets=parse_ldbi_table(again)[2]
        self.assertEqual(read_cstring(again,offsets[struct.unpack_from('>I',again,start+16)[0]]),replacement)
        self.assertEqual(read_cstring(again,offsets[struct.unpack_from('>I',again,start+196+16)[0]]),'More '+replacement)
        self.assertEqual(read_cstring(again,offsets[2]),'old')
        with self.assertRaisesRegex(ValueError,'Dialogue text needs'):
            patch_ldbi(bytes(source),[(0,'text','Z'*2000)])

    def test_unicode_suffix_empty_strings_and_nul_rejection(self):
        texts=['日本語 ending','ending',''];payload,pointers=_dialogue_pool(texts,True)
        self.assertEqual([read_cstring(b'\0'*128+payload,p) for p in pointers],texts)
        with self.assertRaisesRegex(ValueError,'NUL'):_dialogue_pool(['bad\0text'],True)

if __name__=='__main__':unittest.main()
