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
    parser=argparse.ArgumentParser();parser.add_argument('--self-check',type=Path);parser.add_argument('--data',type=Path);args=parser.parse_args()
    home=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]/'full_patcher'
    if args.self_check:os.environ['QT_QPA_PLATFORM']='offscreen'
    app=QApplication(sys.argv[:1]);load_ui_fonts();app.setStyle('Fusion');app.setStyleSheet(STYLE)
    window=FullPatchDialog(home)
    if args.data:window.data.setText(str(args.data))
    if args.self_check:
        from runtime_check import check_runtime_package
        runtime_check=check_runtime_package(window.data.text())
        doc=package_info(window.data.text());window.show();app.processEvents()
        args.self_check.parent.mkdir(parents=True,exist_ok=True);window.grab().save(str(args.self_check.with_suffix('.png')))
        window.font_only.setChecked(True);assert not window.edits.isEnabled()
        assert doc.get('backlog_margin_width')==720 and doc.get('backlog_user_confirmed')
        assert doc.get('battle_text_right_edge')==1136
        assert doc.get('battle_caption_limits')==BATTLE_CAPTION_LIMITS
        assert doc.get('battle_fit_visual_tested') and doc.get('diagnostic_recorder') is False
        assert 'The reported Azuki battle line was also confirmed in game' in window.details.toPlainText()
        atomic_json(args.self_check,dict(status='passed',version='1.6.2',backlog_margin_width=720,battle_text_right_edge=1136,battle_caption_limits=BATTLE_CAPTION_LIMITS,battle_fit_user_confirmed=True,diagnostic_recorder=False,frozen=bool(getattr(sys,'frozen',False)),archives=len(doc['archives']),edited_rows=doc['edited_rows'],english_intro=bool(doc.get('movie')),custom_notice=bool(doc.get('custom_notice')),editor_corrections_supported=True,font_only_upgrade_available=True,font_mode=doc.get('font_mode'),runtime_workflow=runtime_check))
        window.close();return 0
    window.show();return app.exec()


if __name__=='__main__':sys.exit(main())
