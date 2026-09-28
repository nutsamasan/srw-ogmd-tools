"""Offline packaged check of RPCS3 installation and exact restoration."""
import json
import tempfile
from pathlib import Path
from runtime_setup import setup_runtime,restore_setup


def check_runtime_package(assets):
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);runtime=root/'rpcs3';runtime.mkdir()
        assets=Path(assets)
        native=False
        if not (assets/'assets.json').exists():
            release=json.loads((assets/'release.json').read_text(encoding='utf8'))
            support=root/'support';support.mkdir()
            native=release.get('font_mode')=='embedded-eboot'
            for name in (('install_icon.png',) if native else ('spacing.yml','install_icon.png')):(support/name).write_bytes((assets/name).read_bytes())
            info={key:release[key] for key in ('spacing_sha256','install_icon_sha256','font_mode') if key in release}
            (support/'assets.json').write_text(json.dumps(info),encoding='utf8')
            if native:
                from native_eboot import load_asset
                meta,raw=load_asset(assets/'native_eboot');(root/'native').mkdir();(root/'native/EBOOT.BIN').write_bytes(raw)
            assets=support
        (runtime/'rpcs3.exe').write_bytes(b'offline fixture')
        (runtime/'config').mkdir()
        (runtime/'config/config.yml').write_text('Video:\n  Resolution Scale: 150\n',encoding='utf8')
        manifest=root/'game.json'
        doc=dict(status='ready',profile='script-only',archives=[])
        if native:
            doc.update(font_mode='embedded-eboot',eboot=dict(file='native/EBOOT.BIN',mode='embedded-eboot',after=meta['sha256'],
                size=meta['size'],elf_sha256=meta['elf_sha256'],ppu=meta['ppu']))
        manifest.write_text(json.dumps(doc),encoding='utf8')
        before={p.relative_to(runtime).as_posix():p.read_bytes() for p in runtime.rglob('*') if p.is_file()}
        result=setup_runtime(runtime,manifest,assets,closed_check=lambda _:None)
        embedded=doc.get('font_mode')=='embedded-eboot'
        if embedded:
            assert result['patch_path'] is None and not result['patch_enabled']
            assert not list((runtime/'patches').glob('*.yml'))
        else:
            assert Path(result['patch_path'])==runtime/'patches/BLJS10335_patch.yml'
            assert result['patch_enabled']
        assert result['compatibility_settings_verified']
        restore_setup(result['setup_plan'],closed_check=lambda _:None)
        after={p.relative_to(runtime).as_posix():p.read_bytes() for p in runtime.rglob('*') if p.is_file()}
        assert before==after
        return dict(font_mode=doc.get('font_mode','yaml'),font_yaml_required=not embedded,installation=True,enabled=not embedded,restore=True)
