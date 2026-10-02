$ErrorActionPreference = 'Stop'
$fullEditorRoot = Join-Path $PSScriptRoot '..\script_editor'
$fullBuildOldPath = $env:PATH
try {
    $env:PATH = "$fullEditorRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & "$fullEditorRoot\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onefile --windowed `
        --name 'OGMD Full English Patcher v1.6.4' --distpath $PSScriptRoot --workpath "$PSScriptRoot\build" --specpath "$PSScriptRoot\build" `
        --add-data "$fullEditorRoot\assets\title_cards.zip;assets" `
        --paths $fullEditorRoot "$fullEditorRoot\full_app.py"
    if ($LASTEXITCODE -ne 0) { throw "Full patcher build failed: $LASTEXITCODE" }
} finally {
    $env:PATH = $fullBuildOldPath
}
