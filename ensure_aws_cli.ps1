# Official MSI reference: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
[CmdletBinding()]
param([switch]$Install)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Find-AwsCli {
    $candidates = @()
    foreach ($entry in @(
        @($env:LOCALAPPDATA, 'Programs\Amazon\AWSCLIV2\aws.exe'),
        @($env:ProgramW6432, 'Amazon\AWSCLIV2\aws.exe'),
        @($env:ProgramFiles, 'Amazon\AWSCLIV2\aws.exe'),
        @(${env:ProgramFiles(x86)}, 'Amazon\AWSCLIV2\aws.exe'),
        @($env:ProgramFiles, 'Amazon\AWSCLI\bin\aws.exe')
    )) {
        if ($entry[0]) { $candidates += Join-Path $entry[0] $entry[1] }
    }
    $command = Get-Command aws.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $process = New-Object System.Diagnostics.Process
        try {
            $process.StartInfo.FileName = $candidate
            $process.StartInfo.Arguments = '--version'
            $process.StartInfo.UseShellExecute = $false
            $process.StartInfo.CreateNoWindow = $true
            $process.StartInfo.RedirectStandardOutput = $true
            $process.StartInfo.RedirectStandardError = $true
            [void]$process.Start()
            $output = $process.StandardOutput.ReadToEndAsync()
            $errors = $process.StandardError.ReadToEndAsync()
            if (-not $process.WaitForExit(10000)) { $process.Kill(); continue }
            if ($process.ExitCode -eq 0 -and (($output.Result + $errors.Result).Trim() -match '^aws-cli/')) {
                return $candidate
            }
        } catch { Write-Verbose "AWS probe failed: $_" }
        finally { $process.Dispose() }
    }
    return $null
}

try {
    $existing = Find-AwsCli
    if ($existing) { Write-Output $existing; exit 0 }
    if (-not $Install) { throw 'AWS CLI not found; installation requires explicit -Install consent.' }
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'AWS CLI requires 64-bit Windows.' }
    # This current-user MSI does not require elevation. Never evaluate downloaded scripts.
    $tempDir = Join-Path ([IO.Path]::GetTempPath()) ('SyncAgent-AWS-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tempDir | Out-Null
    try {
        $msi = Join-Path $tempDir 'AWSCLIV2-User.msi'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri 'https://awscli.amazonaws.com/AWSCLIV2-User.msi' -OutFile $msi -MaximumRedirection 0 -TimeoutSec 180
        $signature = Get-AuthenticodeSignature -LiteralPath $msi
        if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate -or
            $signature.SignerCertificate.Subject -notmatch '(?:^|,\s*)O="?(?:Amazon\.com Services LLC|Amazon Web Services, Inc\.|Amazon\.com, Inc\.)"?(?=,\s*[A-Za-z][A-Za-z0-9.]*=|$)') {
            throw 'AWS installer signature is not Valid with an Amazon publisher; refusing installation.'
        }
        $msiexec = Join-Path $env:SystemRoot 'System32\msiexec.exe'
        $process = Start-Process -FilePath $msiexec -ArgumentList @('/i', ('"' + $msi + '"'), '/qn', '/norestart') -PassThru
        if (-not $process.WaitForExit(600000)) { throw 'AWS MSI timed out; Windows Installer may still be running. Do not retry until it completes.' }
        if ($process.ExitCode -notin @(0, 3010, 1641)) { throw "AWS MSI failed with exit code $($process.ExitCode)." }
        if ($process.ExitCode -in @(3010, 1641)) { Write-Warning 'AWS installer reports a restart is required.' }
        $installed = Find-AwsCli
        if (-not $installed) { throw 'AWS MSI completed, but aws --version still fails. A restart may be required.' }
        Write-Output $installed
    } finally {
        if (Test-Path -LiteralPath $tempDir) { Remove-Item -LiteralPath $tempDir -Recurse -Force }
    }
} catch { Write-Error $_; exit 1 }
