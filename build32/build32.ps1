# Build the 32-bit portable eNSP-MCP.exe.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File build32.ps1
# First run downloads a 32-bit Python 3.11.9 embeddable runtime into toolchain\.
# The toolchain and PyInstaller work directories can be deleted after a build.

$ErrorActionPreference = 'Stop'
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyDir = Join-Path $base 'toolchain\py311-32'
$py = Join-Path $pyDir 'python.exe'
$ProgressPreference = 'SilentlyContinue'

if (-not (Test-Path $py)) {
    New-Item -ItemType Directory -Force -Path (Join-Path $base 'toolchain') | Out-Null
    $zip = Join-Path $base 'toolchain\python-3.11.9-embed-win32.zip'
    if (-not (Test-Path $zip)) {
        Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-win32.zip' -OutFile $zip
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

& $py -m pip install --only-binary=:all: --no-warn-script-location -r (Join-Path $base 'requirements32.txt')

Push-Location $base
try {
    & $py -m PyInstaller --noconfirm --clean --onefile --console --name eNSP-MCP `
        --version-file version_info.txt `
        --add-data "src\templates;templates" `
        --add-data "src\static;static" `
        --hidden-import engineio.async_drivers.threading `
        --hidden-import simple_websocket `
        --hidden-import wsproto `
        --hidden-import mcp.server.lowlevel `
        --hidden-import mcp.shared.session `
        --hidden-import mcp.server.models `
        --hidden-import PIL `
        --hidden-import PIL.Image `
        --hidden-import PIL.ImageDraw `
        --hidden-import PIL.ImageFont `
        src\main.py
} finally {
    Pop-Location
}

Write-Host "Built: $base\dist\eNSP-MCP.exe"
