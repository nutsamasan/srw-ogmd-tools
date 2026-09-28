$ErrorActionPreference = 'Stop'
$pilotPython = Join-Path $PSScriptRoot '..\script_editor\.venv\Scripts\python.exe'
$pilotOldPath = $env:PATH
try {
    $env:PATH = "$(Split-Path $pilotPython);$env:SystemRoot\System32;$env:SystemRoot"
    & $pilotPython -m PyInstaller --noconfirm --onefile --windowed `
        --name 'OGMD Pilot Editor v1.1' --distpath $PSScriptRoot `
        --workpath "$PSScriptRoot\build" --specpath "$PSScriptRoot\build" `
        --add-data "$PSScriptRoot\catalog.json;." `
        --add-data "$PSScriptRoot\names.json;." "$PSScriptRoot\app.py"
    if ($LASTEXITCODE -ne 0) { throw "Pilot editor build failed: $LASTEXITCODE" }
} finally {
    $env:PATH = $pilotOldPath
}
