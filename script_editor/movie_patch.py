"""Verified same-size opening movie replacement for the full patcher."""
import json
import os
from pathlib import Path
from archive_patch import digest
from iso_image import canonical
from release_delta import apply_recipe

DISC_PATH='/PS3_GAME/USRDIR/PSARC/Movie.psarc'
BUILD_FILE='native/Movie.psarc'


def package_movie(data,release):
    movie=release.get('movie')
    if movie is None:
        if release.get('version')==2:raise ValueError('The release is missing its English intro.')
        return None
    if release.get('version')!=2:raise ValueError('The English intro requires release format 2.')
    if movie.get('recipe')!='Movie.recipe.json' or movie.get('blob')!='Movie.delta':
        raise ValueError('Invalid movie package filename.')
    for key in ('recipe','blob'):
        if digest(Path(data)/movie[key])!=movie[key+'_sha256']:raise ValueError('Movie payload checksum failed: '+movie[key])
    recipe=json.loads((Path(data)/movie['recipe']).read_text(encoding='utf8'))
    if recipe['source_sha256']!=movie['source_sha256'] or recipe['target_sha256']!=movie['target_sha256'] or recipe['size']!=movie['size']:
        raise ValueError('Movie recipe does not match its release.')
    return movie


def prepare_movie(data,release,game,iso,build,progress):
    movie=package_movie(data,release)
    if movie is None:return None
    build=Path(build);data=Path(data)
    original=build/'Movie.source.psarc' if iso else game/'USRDIR/PSARC/Movie.psarc'
    progress('Checking the original opening movie archive…')
    if iso:
        item=iso.file(DISC_PATH);iso.check_patch_files([item])
        stamp=iso.views['ISO9660'][canonical(item.path)].mtime_ns
        if stamp is None:raise ValueError('The ISO has no usable movie timestamp.')
        before=iso.extract(item,original)
    else:
        stamp=original.stat().st_mtime_ns;before=digest(original)
    if original.stat().st_size!=movie['size'] or before!=movie['source_sha256']:
        raise ValueError('Movie is not the supported vanilla revision.')
    recipe=json.loads((data/movie['recipe']).read_text(encoding='utf8'))
    progress('Adding and verifying the English intro; preserving the other movies…')
    output=build/BUILD_FILE
    apply_recipe(original,data/movie['blob'],recipe,output)
    if digest(original)!=before:raise ValueError('The source movie archive changed during the build.')
    os.utime(output,ns=(stamp,stamp))
    if iso:original.unlink()
    return dict(name='Movie',file=BUILD_FILE,before=before,after=movie['target_sha256'],size=movie['size'],mtime_ns=stamp)


def validate_movie(folder,doc):
    movie=doc.get('movie')
    if movie is None:
        if doc.get('version')==2:raise ValueError('The prepared English intro is missing.')
        return None
    if doc.get('profile')!='full-english' or doc.get('version')!=2 or movie.get('name')!='Movie' or movie.get('file')!=BUILD_FILE:
        raise ValueError('Invalid prepared movie record.')
    payload=Path(folder)/BUILD_FILE
    if payload.stat().st_size!=movie['size'] or digest(payload)!=movie['after']:
        raise ValueError('The prepared English movie archive changed.')
    return payload
