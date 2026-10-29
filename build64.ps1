# Build the 64-bit portable eNSP-MCP.exe.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File build64.ps1
# Uses the same src and requirements as build32, with a 64-bit Python 3.11.9
# embeddable runtime downloaded into toolchain\py311-64\.

$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyDir = Join-Path $base 'toolchain\py311-64'
$py = Join-Path $pyDir 'python.exe'
$ProgressPreference = 'SilentlyContinue'

if (-not (Test-Path $py)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $base 'toolchain') | Out-Null
    $zip = Join-Path $base 'toolchain\python-3.11.9-embed-amd64.zip'
    if (-not (Test-Path $zip)) {
        try {
            Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile $zip -TimeoutSec 120
        } catch {
            Write-Host '[WARN] python.org failed, trying Huawei Cloud mirror...'
            Invoke-WebRequest -Uri 'https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile $zip -TimeoutSec 300
        }
    }
    Expand-Archive -LiteralPath $zip -DestinationPath $pyDir -Force
    New-Item -ItemType Directory -Force -Path (Join-Path $pyDir 'Lib\site-packages') | Out-Null
    @('python311.zip', '.', 'Lib\site-packages', 'import site') |
        Set-Content -LiteralPath (Join-Path $pyDir 'python311._pth') -Encoding ASCII
    $getPip = Join-Path $base 'toolchain\get-pip.py'
    if (-not (Test-Path $getPip)) {
        Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip
    }
    & $py $getPip --no-warn-script-location
}

& $py -m pip install --only-binary=:all: --no-warn-script-location -r (Join-Path $base 'build32\requirements32.txt')

$src = Join-Path $base 'build32\src'
Push-Location $base
try {
    & $py -m PyInstaller --noconfirm --clean --onefile --console --name eNSP-MCP `
        --version-file (Join-Path $base 'build32\version_info.txt') `
        --add-data "$src\templates;templates" `
        --add-data "$src\static;static" `
        --hidden-import engineio.async_drivers.threading `
        --hidden-import simple_websocket `
        --hidden-import wsproto `
        --hidden-import mcp.server.lowlevel `
        --hidden-import mcp.shared.session `
        --hidden-import mcp.server.models `
        --distpath (Join-Path $base 'dist64') `
        --workpath (Join-Path $base 'build64\work') `
        --specpath (Join-Path $base 'build64') `
        (Join-Path $src 'main.py')
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Host "Built: $base\dist64\eNSP-MCP.exe"
