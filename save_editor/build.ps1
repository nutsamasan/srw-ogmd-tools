param([string]$OutputName = 'OGMD Save Editor')
$ErrorActionPreference = 'Stop'
$saveEditorPython = Join-Path $PSScriptRoot '..\script_editor\.venv\Scripts\python.exe'
$saveEditorOldPath = $env:PATH
try {
    $env:PATH = "$(Split-Path $saveEditorPython);$env:SystemRoot\System32;$env:SystemRoot"
    & $saveEditorPython -m PyInstaller --noconfirm --onefile --windowed `
        --name $OutputName --distpath $PSScriptRoot `
        --workpath "$PSScriptRoot\build" --specpath "$PSScriptRoot\build" `
        --add-data "$PSScriptRoot\weapon_editor\catalog.json;weapon_editor" `
        --add-data "$PSScriptRoot\pilot_status.json;." --add-data "$PSScriptRoot\names.json;." --add-data "$PSScriptRoot\skills.json;." --add-data "$PSScriptRoot\mechs.json;." "$PSScriptRoot\save_editor.py"
    if ($LASTEXITCODE -ne 0) { throw "Save editor build failed: $LASTEXITCODE" }
} finally {
    $env:PATH = $saveEditorOldPath
}
