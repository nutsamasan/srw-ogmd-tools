import copy,json,os,shutil,struct,tempfile,unittest
from pathlib import Path
from archive_patch import digest
from core import atomic_json
from full_patch import write_full_game
from iso_patcher import write_patched_iso
from iso_image import DiscImage
from movie_patch import package_movie,prepare_movie,validate_movie,DISC_PATH
from test_import_iso import mini_iso
from test_full_release import FullReleaseTests


class StartupAssetsTests(unittest.TestCase):
    def test_movie_recipe_source_guards_and_prepared_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=root/'data';data.mkdir();game=root/'PS3_GAME';archive=game/'USRDIR/PSARC';archive.mkdir(parents=True)
            source=archive/'Movie.psarc';source.write_bytes(b'unchanged-FIRST-original-LAST-unchanged')
            before=source.read_bytes();replacement=b'ENGLISH!';start=before.index(b'original');new=before[:start]+replacement+before[start+8:]
            blob=data/'Movie.delta';blob.write_bytes(replacement)
            target=root/'target';target.write_bytes(new)
            recipe=dict(source_sha256=digest(source),target_sha256=digest(target),size=len(before),blob_sha256=digest(blob),blob_size=8,
                        ops=[['copy',0,start],['data',0,8],['copy',start+8,len(before)-start-8]])
            atomic_json(data/'Movie.recipe.json',recipe)
            movie=dict(recipe='Movie.recipe.json',blob='Movie.delta',recipe_sha256=digest(data/'Movie.recipe.json'),blob_sha256=digest(blob),
                       size=len(before),source_sha256=digest(source),target_sha256=digest(target))
            release=dict(version=2,movie=movie);self.assertEqual(package_movie(data,release),movie)
            build=root/'build';(build/'native').mkdir(parents=True)
            record=prepare_movie(data,release,game,None,build,lambda _:None)
            self.assertEqual((build/record['file']).read_bytes(),new);self.assertEqual(source.read_bytes(),before)
            doc=dict(version=2,profile='full-english',movie=record);validate_movie(build,doc)
            with self.assertRaises(ValueError):package_movie(data,dict(version=2))
            with self.assertRaises(ValueError):package_movie(data,dict(version=1,movie=movie))
            with self.assertRaises(ValueError):validate_movie(build,dict(version=2,profile='full-english'))
            with self.assertRaises(ValueError):validate_movie(build,{**doc,'profile':'font-only'})
            (build/record['file']).write_bytes(b'X'*len(new))
            with self.assertRaises(ValueError):validate_movie(build,doc)
            source.write_bytes(b'X'*len(before));bad=root/'bad';(bad/'native').mkdir(parents=True)
            with self.assertRaises(ValueError):prepare_movie(data,release,game,None,bad,lambda _:None)
            self.assertFalse((bad/'native/Movie.psarc').exists())

    def test_folder_output_adds_movie_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);helper=FullReleaseTests();runtime,game,manifest=helper.fixture(root)
            source=root/'source';shutil.copytree(game,source/'PS3_GAME')
            original=source/'PS3_GAME/USRDIR/PSARC/Movie.psarc';original.write_bytes(b'original intro')
            payload=manifest.parent/'native/Movie.psarc';payload.write_bytes(b'English intro!')
            doc=json.loads(manifest.read_text());doc.update(version=2,kind='ogmd-full-folder',source=str(source),game_root=str(source/'PS3_GAME'))
            for a in doc['archives']:a['mtime_ns']=100000000000
            doc['movie']=dict(name='Movie',file='native/Movie.psarc',size=payload.stat().st_size,before=digest(original),after=digest(payload),mtime_ns=original.stat().st_mtime_ns)
            atomic_json(manifest,doc);before=helper.snapshot(source);output=root/'output'
            result=write_full_game(manifest,output)
            self.assertEqual(result['status'],'verified');self.assertEqual(before,helper.snapshot(source))
            self.assertEqual((output/'PS3_GAME/USRDIR/PSARC/Movie.psarc').read_bytes(),payload.read_bytes())

    def test_iso_movie_multi_extents_and_unrelated_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.iso';mini_iso(source);raw=bytearray(source.read_bytes())
            def record(name,sector,size,multi=False):
                name=(name+';1').encode();n=33+len(name)+(len(name)%2==0);r=bytearray(n);r[0]=n
                struct.pack_into('<I',r,2,sector);struct.pack_into('>I',r,6,sector);struct.pack_into('<I',r,10,size);struct.pack_into('>I',r,14,size)
                r[25]=128 if multi else 0;r[28:32]=b'\1\0\0\1';r[32]=len(name);r[33:33+len(name)]=name;return r
            names=['Logic','Common','General2d','Battle','General3d'];directory=bytearray()
            for i,name in enumerate(names):
                sector=110+i;directory+=record(name+'.psarc.sdat',sector,64);raw[sector*2048:sector*2048+64]=b'NPD\0'+bytes([i])*60
            directory+=record('Movie.psarc',130,2048,True)+record('Movie.psarc',140,256)
            raw[27*2048:28*2048]=directory.ljust(2048,b'\0');raw[130*2048:131*2048]=b'A'*2048;raw[140*2048:140*2048+256]=b'B'*256
            source.write_bytes(raw);build=root/'build';(build/'native').mkdir(parents=True);archives=[]
            with DiscImage(source) as iso:
                for i,name in enumerate(names):
                    item=iso.file('/PS3_GAME/USRDIR/PSARC/'+name+'.psarc.sdat');payload=build/'native'/(name+'.psarc.sdat');payload.write_bytes(b'NPD\0'+bytes([i+50])*60)
                    archives.append(dict(name=name,file='native/'+payload.name,size=64,before=iso.checksum(item),after=digest(payload)))
                item=iso.file(DISC_PATH);extents=item.extents;payload=build/'native/Movie.psarc';payload.write_bytes(b'C'*2304)
                movie=dict(name='Movie',file='native/Movie.psarc',size=2304,before=iso.checksum(item),after=digest(payload))
            doc=dict(version=2,kind='ogmd-iso',profile='full-english',status='ready',source=str(source),source_corpus=str(root/'corpus'),
                     source_size=len(raw),source_mtime_ns=source.stat().st_mtime_ns,source_sha256=digest(source),views=['ISO9660'],archives=archives,movie=movie)
            manifest=build/'iso_patch.json';atomic_json(manifest,doc);output=root/'english.iso';result=write_patched_iso(manifest,output)
            self.assertEqual(source.read_bytes(),bytes(raw));self.assertEqual(result['movie']['after'],movie['after'])
            expected=bytearray(raw)
            for i in range(5):expected[(110+i)*2048:(110+i)*2048+64]=b'NPD\0'+bytes([i+50])*60
            for start,size in extents:expected[start:start+size]=b'C'*size
            self.assertEqual(output.read_bytes(),bytes(expected))
            (build/'native/Movie.psarc').write_bytes(b'D'*2304)
            with self.assertRaises(ValueError):write_patched_iso(manifest,root/'bad.iso')
            self.assertFalse((root/'bad.iso').exists())


if __name__=='__main__':unittest.main()
