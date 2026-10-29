param(
    [switch]$AddPath,
    [switch]$RemovePath,
    [string]$Dir = (Join-Path $env:LOCALAPPDATA 'eNSP-MCP')
)

$ErrorActionPreference = 'Stop'

function Broadcast-EnvironmentChange {
    try {
        Add-Type -Namespace Win32 -Name NativeMethods -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
        $result = [UIntPtr]::Zero
        [Win32.NativeMethods]::SendMessageTimeout(
            [IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result
        ) | Out-Null
    } catch {
        Write-Host "[WARN] Could not broadcast the environment change: $($_.Exception.Message)"
    }
}

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
$parts = @($userPath -split ';' | Where-Object { $_ })

if ($AddPath) {
    if ($parts -notcontains $Dir) {
        [Environment]::SetEnvironmentVariable('Path', (($parts + $Dir) -join ';'), 'User')
        Broadcast-EnvironmentChange
        Write-Host "[OK] Added to user PATH: $Dir"
    } else {
        Write-Host "[INFO] Already in user PATH: $Dir"
    }
}

if ($RemovePath) {
    $newParts = @($parts | Where-Object { $_ -ne $Dir })
    [Environment]::SetEnvironmentVariable('Path', ($newParts -join ';'), 'User')
    Broadcast-EnvironmentChange
    Write-Host "[OK] Removed from user PATH: $Dir"
}
