[CmdletBinding()]
param([string]$SourceDir = '', [switch]$Yes, [switch]$NoStartup)
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

function Assert-PlainTree([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "Missing directory: $Path" }
    $item = Get-Item -LiteralPath $Path -Force
    while ($item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing reparse point: $($item.FullName)" }
        $item = $item.Parent
    }
    foreach ($child in (Get-ChildItem -LiteralPath $Path -Recurse -Force)) {
        if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing reparse point: $($child.FullName)" }
    }
}
function Invoke-Agent([string]$Exe, [string]$Argument) {
    $process = Start-Process -FilePath $Exe -ArgumentList $Argument -PassThru -NoNewWindow
    if (-not $process.WaitForExit(45000)) { throw "Sync Agent $Argument timed out; installation aborted without force-killing processes." }
    if ($process.ExitCode -ne 0) { throw "Sync Agent $Argument failed ($($process.ExitCode))." }
}

try {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not defined.' }
    $app = Join-Path $env:LOCALAPPDATA 'Programs\SyncAgent'
    $data = Join-Path $env:LOCALAPPDATA 'SyncAgent'
    Assert-NoSyncOverlap $app $data
    if (-not $SourceDir) {
        if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'SyncAgent.exe')) { $SourceDir = $PSScriptRoot }
        else { $SourceDir = Join-Path $PSScriptRoot 'dist\SyncAgent' }
    }
    $source = [IO.Path]::GetFullPath($SourceDir).TrimEnd('\')
    Assert-PlainTree $source
    foreach ($required in @('SyncAgent.exe', 'install.ps1', 'uninstall.ps1', 'ensure_aws_cli.ps1')) {
        if (-not (Test-Path -LiteralPath (Join-Path $source $required) -PathType Leaf)) { throw "Invalid source bundle: missing $required" }
    }
    if ($source -eq $app -or $source.StartsWith($app + '\', [StringComparison]::OrdinalIgnoreCase) -or $app.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Source and destination must be separate directory trees.'
    }
    if (-not $Yes -and (Read-Host "Install Sync Agent to $app ? [y/N]") -notmatch '^(y|yes)$') {
        Write-Host 'Installation cancelled; no changes made.'; exit 2
    }
    $parent = Split-Path -Parent $app
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    # Inspect ancestors before staging; never write through a redirected app directory.
    $ancestor = Get-Item -LiteralPath $parent
    while ($ancestor) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Install path contains a reparse point.' }
        $ancestor = $ancestor.Parent
    }
    if (Test-Path -LiteralPath $app) { Assert-PlainTree $app; Assert-OwnedInstallation $app }
    $startupCommand = '"' + (Join-Path $app 'SyncAgent.exe') + '" --background'
    if (-not $NoStartup -and $startupCommand.Length -gt 260) {
        throw 'Startup command exceeds the 260-character Run-key limit; use -NoStartup or a shorter profile path.'
    }
    $staging = Join-Path $parent ('SyncAgent-staging-' + [guid]::NewGuid().ToString('N'))
    $backup = Join-Path $parent ('SyncAgent-backup-' + [guid]::NewGuid().ToString('N'))
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $oldRun = Get-ItemPropertyValue -LiteralPath $runKey -Name 'SyncAgent' -ErrorAction SilentlyContinue
    $movedOld = $false
    $movedNew = $false
    $registryChanged = $false
    try {
        New-Item -ItemType Directory -Path $staging | Out-Null
        Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $staging -Recurse -Force
        '{"product":"SyncAgent","schema":1}' | Set-Content -LiteralPath (Join-Path $staging 'SyncAgent.install.json') -Encoding UTF8
        Assert-OwnedInstallation $staging
        # Check staged application before disturbing the previous installation.
        Invoke-Agent (Join-Path $staging 'SyncAgent.exe') '--status'
        if (Test-Path -LiteralPath (Join-Path $app 'SyncAgent.exe')) { Invoke-Agent (Join-Path $app 'SyncAgent.exe') '--stop' }
        if (Test-Path -LiteralPath $app) { Move-Item -LiteralPath $app -Destination $backup; $movedOld = $true }
        Move-Item -LiteralPath $staging -Destination $app
        $movedNew = $true
        Invoke-Agent (Join-Path $app 'SyncAgent.exe') '--status'
        New-Item -Path $runKey -Force | Out-Null
        $registryChanged = $true
        if ($NoStartup) { Remove-ItemProperty -LiteralPath $runKey -Name 'SyncAgent' -ErrorAction SilentlyContinue }
        else { Set-ItemProperty -LiteralPath $runKey -Name 'SyncAgent' -Value ('"' + (Join-Path $app 'SyncAgent.exe') + '" --background') }
        $actual = Get-ItemPropertyValue -LiteralPath $runKey -Name 'SyncAgent' -ErrorAction SilentlyContinue
        if (-not $NoStartup -and $actual -ne ('"' + (Join-Path $app 'SyncAgent.exe') + '" --background')) { throw 'Startup registration read-back failed.' }
        if ($NoStartup -and $actual) { throw 'Startup removal read-back failed.' }
    } catch {
        $failure = $_
        # Rollback components are independent: a registry error must not strand the old bundle.
        if ($registryChanged) {
            try {
                if ($null -ne $oldRun) { Set-ItemProperty -LiteralPath $runKey -Name 'SyncAgent' -Value $oldRun }
                else { Remove-ItemProperty -LiteralPath $runKey -Name 'SyncAgent' -ErrorAction SilentlyContinue }
            } catch { Write-Warning "Startup rollback failed; repair manually: $_" }
        }
        try {
            if ($movedNew -and (Test-Path -LiteralPath $app)) { Remove-Item -LiteralPath $app -Recurse -Force }
        } catch { Write-Warning "New bundle cleanup failed: $_" }
        try {
            if ($movedOld -and (Test-Path -LiteralPath $backup)) {
                if (Test-Path -LiteralPath $app) { throw "Destination still exists; original preserved at $backup" }
                Move-Item -LiteralPath $backup -Destination $app
            }
        } catch { Write-Warning "Original bundle restoration failed; original preserved at $backup : $_" }
        throw $failure
    } finally {
        if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    }
    if (Test-Path -LiteralPath $backup) {
        try { Remove-Item -LiteralPath $backup -Recurse -Force }
        catch { Write-Warning "Installed successfully, but old bundle remains at $backup : $_" }
    }
    Write-Host "Installed Sync Agent in $app. User data remains at $data."
    Write-Host ('Run "' + (Join-Path $app 'SyncAgent.exe') + '" --setup to configure; installation does not contact AWS.')
    exit 0
} catch { Write-Error $_; exit 1 }
