$ErrorActionPreference = 'Stop'
$patcherPython = Join-Path $PSScriptRoot '..\script_editor\.venv\Scripts\python.exe'
$patcherOldPath = $env:PATH
try {
    $env:PATH = "$(Split-Path $patcherPython);$env:SystemRoot\System32;$env:SystemRoot"
    & $patcherPython -m PyInstaller --noconfirm --onefile --windowed `
        --name 'OGMD Mech Skill Patcher' --distpath $PSScriptRoot `
        --workpath "$PSScriptRoot\build" --specpath "$PSScriptRoot\build" `
        --add-data "$PSScriptRoot\catalog.json;." "$PSScriptRoot\app.py"
    if ($LASTEXITCODE -ne 0) { throw "Patcher build failed: $LASTEXITCODE" }
} finally {
    $env:PATH = $patcherOldPath
}
