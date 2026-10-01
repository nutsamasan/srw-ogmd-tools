"""Reproduce S084's correction from original game glyphs without resampling."""
import io
from PIL import Image, ImageChops
from core import sha

ST084_PNG_SHA256 = '463feb6ac87ebc53482a88059660a5a24648bde54d01f4d24b6c635c487173c6'
ORIGINAL_PNG_SHA256 = '6f7d9695b48b63c37d5e787854da51830d6b5a36835a88e36f9312e8d9fe3230'


def correct_st084(pngs):
    if sha(pngs['st_084']) != ORIGINAL_PNG_SHA256:
        raise ValueError('S084 correction requires the verified original English sheet.')
    images = {key: Image.open(io.BytesIO(png)).convert('RGBA') for key, png in pngs.items()}
    alpha = Image.new('L', (1280, 1152), 0)
    glyphs = [('st_084', 312, 300, 364, 253), ('st_084', 549, 532, 608, 309),
              ('st_000', 767, 751, 820, 372), ('st_000', 702, 695, 758, 426),
              ('st_034', 345, 326, 395, 483), ('st_084', 474, 472, 534, 533)]
    for key, left, crop_left, crop_right, target_left in glyphs:
        placed = Image.new('L', alpha.size, 0)
        placed.paste(images[key].getchannel('A').crop((crop_left, 0, crop_right, 1152)),
                     (target_left + crop_left - left, 0))
        alpha = ImageChops.lighter(alpha, placed)
    alpha.paste(images['st_084'].getchannel('A').crop((549, 0, 984, 1152)), (608, 0))
    fixed = Image.new('RGBA', alpha.size, (255, 255, 255, 0)); fixed.putalpha(alpha)
    output = io.BytesIO(); fixed.save(output, format='PNG')
    if sha(output.getvalue()) != ST084_PNG_SHA256:
        raise ValueError('S084 donor pixels differ from the verified correction.')
    return output.getvalue()
