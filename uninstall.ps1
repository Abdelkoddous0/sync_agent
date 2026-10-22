[CmdletBinding()]
param([switch]$Yes)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Assert-NoSyncOverlap([string]$AppPath, [string]$DataPath) {
    $settings = Join-Path $DataPath 'config.json'
    if (-not (Test-Path -LiteralPath $settings)) { return }
    try {
        $config = Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json
        if (-not [IO.Path]::IsPathRooted($config.local_path)) { throw 'Invalid sync path' }
        $local = [IO.Path]::GetFullPath($config.local_path).TrimEnd([char[]]@('\','/'))
    } catch {
        throw 'Cannot verify sync-folder overlap because settings are unreadable or invalid; repair the retained configuration before retrying.'
    }
    $target = [IO.Path]::GetFullPath($AppPath).TrimEnd([char[]]@('\','/'))
    $separator = [IO.Path]::DirectorySeparatorChar
    if ($local -eq $target -or
        $local.StartsWith($target + $separator, [StringComparison]::OrdinalIgnoreCase) -or
        $target.StartsWith($local + $separator, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Application destination and configured sync folder overlap; refusing to modify synced data.'
    }
}

function Assert-OwnedInstallation([string]$Path) {
    $markerPath = Join-Path $Path 'SyncAgent.install.json'
    try {
        $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
        if ($marker.product -ne 'SyncAgent' -or $marker.schema -ne 1) { throw 'Wrong marker' }
        if (-not (Test-Path -LiteralPath (Join-Path $Path 'SyncAgent.exe') -PathType Leaf)) { throw 'Missing executable' }
    } catch { throw "Unrecognized installation directory; refusing to modify $Path. Preserve it and choose a clean destination." }
}

try {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not defined.' }
    $app = Join-Path $env:LOCALAPPDATA 'Programs\SyncAgent'
    $data = Join-Path $env:LOCALAPPDATA 'SyncAgent'
    Assert-NoSyncOverlap $app $data
    if (-not $Yes -and (Read-Host "Remove Sync Agent application only? Data at $data will be preserved. [y/N]") -notmatch '^(y|yes)$') {
        Write-Host 'Uninstall cancelled; no changes made.'; exit 2
    }
    if (Test-Path -LiteralPath $app) {
        $ancestor = Get-Item -LiteralPath $app -Force
        while ($ancestor) {
            if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing an install path containing a reparse point.' }
            $ancestor = $ancestor.Parent
        }
        foreach ($child in (Get-ChildItem -LiteralPath $app -Recurse -Force)) {
            if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing an application tree containing a reparse point.' }
        }
        Assert-OwnedInstallation $app
        $exe = Join-Path $app 'SyncAgent.exe'
        if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Invalid application directory; refusing automatic removal.' }
        $process = Start-Process -FilePath $exe -ArgumentList '--stop' -PassThru -NoNewWindow
        if (-not $process.WaitForExit(45000)) { throw 'Stop timed out; nothing deleted. Resolve the running application and retry.' }
        if ($process.ExitCode -ne 0) { throw "Stop failed ($($process.ExitCode)); nothing deleted." }
    }
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $oldRun = Get-ItemPropertyValue -LiteralPath $runKey -Name 'SyncAgent' -ErrorAction SilentlyContinue
    $removed = Join-Path (Split-Path -Parent $app) ('SyncAgent-removing-' + [guid]::NewGuid().ToString('N'))
    $moved = $false
    try {
        if (Test-Path -LiteralPath $app) { Move-Item -LiteralPath $app -Destination $removed; $moved = $true }
        Remove-ItemProperty -LiteralPath $runKey -Name 'SyncAgent' -ErrorAction SilentlyContinue
        if (Get-ItemPropertyValue -LiteralPath $runKey -Name 'SyncAgent' -ErrorAction SilentlyContinue) { throw 'Startup removal read-back failed.' }
    } catch {
        if ($moved) { Move-Item -LiteralPath $removed -Destination $app }
        if ($null -ne $oldRun) { Set-ItemProperty -LiteralPath $runKey -Name 'SyncAgent' -Value $oldRun }
        throw
    }
    if ($moved) { Remove-Item -LiteralPath $removed -Recurse -Force }
    if (Test-Path -LiteralPath $app) { throw 'Application directory still exists; uninstall incomplete.' }
    Write-Host "Sync Agent application removed. Config, logs and state at $data are preserved."
    Write-Host 'Synced folders, AWS credentials and AWS CLI are always preserved.'
    exit 0
} catch { Write-Error $_; exit 1 }
