<#
.SYNOPSIS
    One-command Windows acceptance test for SyncAgentSetup.exe (Windows 10 or 11).

.DESCRIPTION
    Installs, configures, starts, stops, upgrades and uninstalls the real application in
    throwaway folders, then prints PASS/FAIL per check and writes acceptance-result.txt.

    Safe to run on a normal PC:
      * LOCALAPPDATA and APPDATA point to a temporary folder, so your real installation,
        settings and Start Menu are untouched;
      * no AWS request is made (fake credentials, unreachable endpoint);
      * the two per-user registry entries that cannot be redirected (start at login and
        Installed apps) are backed up first and restored exactly at the end, so an
        existing installation keeps working;
      * everything it created is removed at the end.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\acceptance-test.ps1 -Installer .\SyncAgentSetup.exe
#>
[CmdletBinding()]
param([string]$Installer = '')
Set-StrictMode -Version Latest
# $PSScriptRoot is not available in parameter defaults on Windows PowerShell 5.1.
if (-not $Installer) { $Installer = Join-Path $PSScriptRoot 'SyncAgentSetup.exe' }
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\SyncAgent'
$results = New-Object System.Collections.Generic.List[object]

function Get-RegistryValue([string]$Key, [string]$Name) {
    try { return Get-ItemPropertyValue -LiteralPath $Key -Name $Name -ErrorAction Stop }
    catch [System.Management.Automation.PSArgumentException], [System.Management.Automation.ItemNotFoundException] { return $null }
}

function Record([string]$Check, [bool]$Passed, [string]$Detail = '') {
    $results.Add([pscustomobject]@{ Check = $Check; Result = $(if ($Passed) { 'PASS' } else { 'FAIL' }); Detail = $Detail })
    $colour = if ($Passed) { 'Green' } else { 'Red' }
    Write-Host ('  [{0}] {1}{2}' -f $(if ($Passed) { 'PASS' } else { 'FAIL' }), $Check, $(if ($Detail) { " - $Detail" } else { '' })) -ForegroundColor $colour
}

function Invoke-Exe([string]$Exe, [string[]]$Arguments) {
    # Windows PowerShell 5.1 turns any stderr line into a terminating error under 'Stop';
    # programs legitimately report on stderr, so judge them by exit code instead.
    $ErrorActionPreference = 'Continue'
    $output = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" } | Out-String
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = $output }
}

function Wait-Status([string]$Exe, [string[]]$Patterns, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        $status = (Invoke-Exe $Exe @('--status')).Output
        foreach ($pattern in $Patterns) { if ($status -match $pattern) { return $status } }
        Start-Sleep -Milliseconds 700
    } while ((Get-Date) -lt $deadline)
    return $status
}

if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) { Write-Error "Installer not found: $Installer"; exit 2 }
$Installer = (Resolve-Path -LiteralPath $Installer).Path

$os = Get-CimInstance Win32_OperatingSystem
$root = Join-Path ([IO.Path]::GetTempPath()) ('SyncAgent-acceptance-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
# Back up the real per-user entries; the test installation overwrites or removes them.
$savedRun = Get-RegistryValue $runKey 'SyncAgent'
$uninstallBackup = Join-Path ([IO.Path]::GetTempPath()) ('SyncAgent-acceptance-uninstall-' + [guid]::NewGuid().ToString('N') + '.reg')
$regPath = 'HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\SyncAgent'
$reg = Join-Path $env:SystemRoot 'System32\reg.exe'
if (Test-Path -LiteralPath $uninstallKey) {
    if ((Invoke-Exe $reg @('export', $regPath, $uninstallBackup, '/y')).Code -ne 0) { Write-Error 'Could not back up the Installed apps entry; nothing was changed.'; exit 2 }
}
$saved = @{}
foreach ($name in 'LOCALAPPDATA', 'APPDATA', 'AWS_CONFIG_FILE', 'AWS_SHARED_CREDENTIALS_FILE', 'AWS_ACCESS_KEY_ID',
                  'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_PROFILE', 'AWS_ENDPOINT_URL', 'AWS_EC2_METADATA_DISABLED') {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
$app = Join-Path $root 'Local\Programs\SyncAgent'
$exe = Join-Path $app 'SyncAgent.exe'
$data = Join-Path $root 'Local\SyncAgent'
$shortcut = Join-Path $root 'Roaming\Microsoft\Windows\Start Menu\Programs\Sync Agent.lnk'

Write-Host ''
Write-Host "Sync Agent acceptance test on $($os.Caption) $($os.Version) (build $($os.BuildNumber))" -ForegroundColor Cyan
Write-Host "Installer: $Installer"
Write-Host "Temporary profile: $root"
Write-Host ''
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'Local'), (Join-Path $root 'Roaming'), (Join-Path $root 'files') | Out-Null
    Set-Content -LiteralPath (Join-Path $root 'aws-empty') -Value '' -Encoding ASCII
    $env:LOCALAPPDATA = Join-Path $root 'Local'
    $env:APPDATA = Join-Path $root 'Roaming'
    # Never contact AWS: empty profile files, fake keys, unreachable endpoint.
    $env:AWS_CONFIG_FILE = Join-Path $root 'aws-empty'
    $env:AWS_SHARED_CREDENTIALS_FILE = Join-Path $root 'aws-empty'
    $env:AWS_ACCESS_KEY_ID = 'AKIAACCEPTANCETEST00'
    $env:AWS_SECRET_ACCESS_KEY = 'acceptance-test-not-a-real-secret'
    $env:AWS_SESSION_TOKEN = $null
    $env:AWS_PROFILE = $null
    $env:AWS_ENDPOINT_URL = 'http://127.0.0.1:9'
    $env:AWS_EC2_METADATA_DISABLED = 'true'

    $signature = Get-AuthenticodeSignature -LiteralPath $Installer
    Record 'Installer signature' $true $(if ($signature.SignerCertificate) { "$($signature.Status), $($signature.SignerCertificate.Subject)" } else { 'not signed (SmartScreen will warn)' })

    $r = Invoke-Exe $Installer @('--help')
    Record 'Installer starts' ($r.Code -eq 0) "exit $($r.Code)"

    $r = Invoke-Exe $Installer @('--yes', '--no-configure')
    $installed = ($r.Code -eq 0) -and (Test-Path -LiteralPath $exe) -and (Test-Path -LiteralPath (Join-Path $app 'SyncAgent.install.json'))
    Record 'Install (per user, no admin)' $installed "exit $($r.Code)"
    if (-not $installed) { throw "Installation failed; installer output:`n$($r.Output)" }
    Record 'Start Menu shortcut created' (Test-Path -LiteralPath $shortcut)
    $entry = Get-RegistryValue $uninstallKey 'UninstallString'
    Record 'Installed apps entry created' ([bool]$entry -and $entry -like "*$app*") "$entry"
    Record 'No login startup without opting in' (-not (Get-RegistryValue $runKey 'SyncAgent'))

    $r = Invoke-Exe $exe @('--version')
    Record 'Installed app runs' ($r.Code -eq 0 -and $r.Output -match 'SyncAgent \d') $r.Output.Trim()
    $r = Invoke-Exe $exe @('--status')
    Record 'Status without settings' ($r.Code -eq 0 -and $r.Output -match 'not configured') "exit $($r.Code)"
    $r = Invoke-Exe $exe @('--background')
    Record 'Background refuses without settings' ($r.Code -eq 1) "exit $($r.Code)"

    $settings = [ordered]@{ workstation_id = 'acceptance'; local_path = (Join-Path $root 'files'); s3_bucket = 'example-acceptance-bucket'
                            s3_prefix = 'acceptance/test'; region = 'eu-central-1'; auth_method = 'workload_role'; poll_interval = 3600 }
    Set-Content -LiteralPath (Join-Path $root 'files\keep-me.txt') -Value 'user data must survive uninstall' -Encoding UTF8
    New-Item -ItemType Directory -Force -Path $data | Out-Null
    [IO.File]::WriteAllText((Join-Path $data 'config.json'), ($settings | ConvertTo-Json))
    $r = Invoke-Exe $exe @('--status')
    Record 'Status shows saved settings' ($r.Code -eq 0 -and $r.Output -match 'example-acceptance-bucket') "exit $($r.Code)"

    # Launch exactly like the login entry / Start Menu do: no captured output, own window.
    $launcher = Start-Process -FilePath $exe -ArgumentList '--background' -PassThru -WindowStyle Minimized
    $null = $launcher.Handle
    $returned = $launcher.WaitForExit(20000)
    Record 'Agent start command returns at once (moves itself to the tray)' ($returned -and $launcher.ExitCode -eq 0) $(if ($returned) { "exit $($launcher.ExitCode)" } else { 'still running after 20 s' })
    $status = Wait-Status $exe @('RUNNING', 'Startup failed') 25
    if ($status -match 'Startup failed: AWS CLI') {
        Record 'Agent start' $true 'AWS CLI not installed: startup correctly refused and reported by --status'
    } elseif ($status -match 'RUNNING') {
        Record 'Agent runs in the background' $true 'tray agent started without a console window'
        $r = Invoke-Exe $exe @('--stop')
        Record 'Cooperative stop' ($r.Code -eq 0) "exit $($r.Code)"
        $status = Wait-Status $exe @('STOPPED') 15
        Record 'Agent stopped' ($status -match 'STOPPED')
    } else {
        Record 'Agent start' $false 'neither RUNNING nor a reported startup failure'
    }
    $leftover = @(Get-Process -Name SyncAgent -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($app, [StringComparison]::OrdinalIgnoreCase) })
    Record 'No agent process left running' ($leftover.Count -eq 0)

    $before = [IO.File]::ReadAllBytes((Join-Path $data 'config.json'))
    $r = Invoke-Exe $Installer @('--yes', '--no-configure')
    $after = [IO.File]::ReadAllBytes((Join-Path $data 'config.json'))
    Record 'Upgrade over existing installation' ($r.Code -eq 0 -and (Test-Path -LiteralPath $exe)) "exit $($r.Code)"
    Record 'Upgrade keeps settings' ([Convert]::ToBase64String($before) -eq [Convert]::ToBase64String($after))
    $status = Wait-Status $exe @('RUNNING', 'Startup failed') 10
    if ($status -match 'RUNNING') { [void](Invoke-Exe $exe @('--stop')) }

    $uninstaller = Join-Path $root 'uninstall-copy.ps1'
    Copy-Item -LiteralPath (Join-Path $app 'uninstall.ps1') -Destination $uninstaller
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $code = (Invoke-Exe $ps @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $uninstaller, '-Yes')).Code
    Record 'Uninstall' ($code -eq 0 -and -not (Test-Path -LiteralPath $app)) "exit $code"
    Record 'Uninstall removes shortcut and Installed apps entry' (-not (Test-Path -LiteralPath $shortcut) -and -not (Test-Path -LiteralPath $uninstallKey))
    Record 'Uninstall keeps settings and synced files' ((Test-Path -LiteralPath (Join-Path $data 'config.json')) -and (Test-Path -LiteralPath (Join-Path $root 'files\keep-me.txt')))
} catch {
    Record 'Test run completed' $false $_.ToString()
} finally {
    if (Test-Path -LiteralPath $exe) { try { [void](Invoke-Exe $exe @('--stop')) } catch { } }
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    # Restore the real per-user entries exactly as they were.
    if ((Get-RegistryValue $uninstallKey 'InstallLocation') -like "$root*") { Remove-Item -LiteralPath $uninstallKey -Recurse -Force }
    if (Test-Path -LiteralPath $uninstallBackup) {
        if (Test-Path -LiteralPath $uninstallKey) { Remove-Item -LiteralPath $uninstallKey -Recurse -Force }
        if ((Invoke-Exe $reg @('import', $uninstallBackup)).Code -ne 0) { Write-Warning "Restore the Installed apps entry manually: reg import `"$uninstallBackup`"" }
        else { Remove-Item -LiteralPath $uninstallBackup -Force }
    }
    if ($null -ne $savedRun) { Set-ItemProperty -LiteralPath $runKey -Name 'SyncAgent' -Value $savedRun }
    elseif ((Get-RegistryValue $runKey 'SyncAgent') -like "*$root*") { Remove-ItemProperty -LiteralPath $runKey -Name 'SyncAgent' }
    Start-Sleep -Milliseconds 500
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

$failed = @($results | Where-Object Result -eq 'FAIL').Count
$summary = if ($failed) { "FAILED: $failed of $($results.Count) checks" } else { "PASSED: all $($results.Count) checks" }
$report = @("Sync Agent acceptance test - $(Get-Date -Format 'yyyy-MM-dd HH:mm')",
            "OS: $($os.Caption) $($os.Version) (build $($os.BuildNumber)), $($os.OSArchitecture)",
            "Installer: $Installer", '', ($results | Format-Table -AutoSize -Wrap | Out-String).Trim(), '', $summary, '',
            'Manual checks (please confirm by eye):',
            '  1. Run SyncAgentSetup.exe normally: the setup wizard opens, prompts show [Y/n] / [y/N] hints.',
            '  2. After setup, the tray icon appears; right-click > Show status opens a readable window.',
            '  3. Right-click > Reconfigure: the confirmation box can be clicked.',
            '  4. Sign out and in with "Start at login" on: the tray icon returns, no console window stays open.')
$resultFile = Join-Path (Split-Path -Parent $Installer) 'acceptance-result.txt'
$report | Set-Content -LiteralPath $resultFile -Encoding UTF8
Write-Host ''
Write-Host $summary -ForegroundColor $(if ($failed) { 'Red' } else { 'Green' })
Write-Host "Results saved to $resultFile"
exit $(if ($failed) { 1 } else { 0 })
