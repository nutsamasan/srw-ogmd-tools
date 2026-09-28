$ErrorActionPreference = 'Stop'
$editorBuildName = 'OGMD Script Editor v3.14'
$editorBuildPath = $env:PATH
try {
    # Keep unrelated tools' ICU and other DLLs out of PyInstaller's dependency search.
    $env:PATH = "$PSScriptRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & "$PSScriptRoot\.venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onefile --windowed `
        --name $editorBuildName --distpath $PSScriptRoot --workpath "$PSScriptRoot\build" --specpath "$PSScriptRoot\build" `
        --add-data "$PSScriptRoot\assets\font.bin;assets" `
        --add-data "$PSScriptRoot\assets\font_atlas.png;assets" `
        --add-data "$PSScriptRoot\assets\tex_13.png;assets" `
        --add-data "$PSScriptRoot\assets\battle_speakers.json;assets" `
        --add-data "$PSScriptRoot\assets\runtime;assets/runtime" `
        --add-data "$PSScriptRoot\assets\provenance.json;assets" "$PSScriptRoot\app.py"
    if ($LASTEXITCODE -ne 0) { throw "Editor build failed: $LASTEXITCODE" }
} finally {
    $env:PATH = $editorBuildPath
}
