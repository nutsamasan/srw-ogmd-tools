"""Entry point for the portable full-game patcher."""
import argparse,json,os,sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from app import STYLE,load_ui_fonts
from full_dialog import FullPatchDialog
from full_patch import package_info
from core import atomic_json
from native_eboot import BATTLE_CAPTION_LIMITS


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--self-check',type=Path);parser.add_argument('--data',type=Path)
    parser.add_argument('--startup-check',type=Path);args=parser.parse_args()
    home=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]/'full_patcher'
    if args.self_check or args.startup_check:os.environ['QT_QPA_PLATFORM']='offscreen'
    app=QApplication(sys.argv[:1]);load_ui_fonts();app.setStyle('Fusion');app.setStyleSheet(STYLE)
    window=FullPatchDialog(home)
    if args.data:window.data.setText(str(args.data))
    if args.startup_check:
        window.show();app.processEvents()
        window.grab().save(str(args.startup_check.with_suffix('.png')))
        atomic_json(args.startup_check,dict(ok=True,gui_constructed=True,local_data_required=not (Path(window.data.text())/'release.json').is_file(),frozen=bool(getattr(sys,'frozen',False))))
        window.close();return 0
    if args.self_check:
        from runtime_check import check_runtime_package
        runtime_check=check_runtime_package(window.data.text())
        doc=package_info(window.data.text());window.show();app.processEvents()
        from pilot_development import validate_release_fix
        pilot_fix=validate_release_fix(doc)
        from stage_title_correction import validate_release_fix as validate_stage_titles
        stage_fix=validate_stage_titles(doc)
        from gilliam_title_correction import validate_release_fix as validate_gilliam
        gilliam_fix=validate_gilliam(doc)
        from title_card_correction import ST084_PNG_SHA256
        from title_cards import catalog
        from core import sha
        assert sha(catalog().source_png('st_084','en'))==ST084_PNG_SHA256
        correction=next(c for c in doc['title_card_corrections'] if c['id']=='st_084')
        assert correction['png_sha256']==ST084_PNG_SHA256
        assert correction['native_sha256']==catalog().card('st_084')['sources']['en']
        args.self_check.parent.mkdir(parents=True,exist_ok=True);window.grab().save(str(args.self_check.with_suffix('.png')))
        window.font_only.setChecked(True);assert not window.edits.isEnabled()
        assert doc.get('backlog_margin_width')==720 and doc.get('backlog_user_confirmed')
        assert doc.get('battle_text_right_edge')==1136
        assert doc.get('battle_caption_limits')==BATTLE_CAPTION_LIMITS
        assert doc.get('battle_fit_visual_tested') and doc.get('diagnostic_recorder') is False
        assert 'The reported Azuki battle line was also confirmed in game' in window.details.toPlainText()
        atomic_json(args.self_check,dict(status='passed',version='1.6.6',backlog_margin_width=720,battle_text_right_edge=1136,battle_caption_limits=BATTLE_CAPTION_LIMITS,battle_fit_user_confirmed=True,diagnostic_recorder=False,frozen=bool(getattr(sys,'frozen',False)),archives=len(doc['archives']),edited_rows=doc['edited_rows'],english_intro=bool(doc.get('movie')),custom_notice=bool(doc.get('custom_notice')),editor_corrections_supported=True,font_only_upgrade_available=True,font_mode=doc.get('font_mode'),runtime_workflow=runtime_check))
        report=json.loads(args.self_check.read_text(encoding='utf8'))
        report.update(corrected_st084_png_sha256=ST084_PNG_SHA256,title_card_corrections_supported=True)
        report.update(pilot_development_descriptions_corrected=pilot_fix['count'],
                      pilot_development_user_confirmed=pilot_fix['user_confirmed_in_game'])
        report.update(stage_titles_corrected=stage_fix['count'],stage_title=stage_fix['title'])
        report.update(gilliam_stage_title=gilliam_fix['title'],gilliam_title_fields_corrected=2,gilliam_shared_title_strings_corrected=1)
        atomic_json(args.self_check,report)
        window.close();return 0
    window.show();return app.exec()


if __name__=='__main__':sys.exit(main())
