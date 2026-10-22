<#
.SYNOPSIS
    Authenticode-sign Sync Agent executables (SHA-256, RFC 3161 timestamp).

.DESCRIPTION
    Used by build.bat when a certificate is configured, and by CI. Choose one source:
      -PfxPath  (+ password in the SYNC_AGENT_SIGN_PASSWORD environment variable, never on the command line)
      -Thumbprint of a certificate already in Cert:\CurrentUser\My (hardware tokens / EV certificates)
    The timestamp keeps signatures valid after the certificate expires.

.EXAMPLE
    $env:SYNC_AGENT_SIGN_PASSWORD = '...'; .\scripts\sign.ps1 -PfxPath C:\certs\company.pfx -Path dist\SyncAgentSetup.exe
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string[]]$Path,
    [string]$PfxPath = '',
    [string]$Thumbprint = '',
    [string]$TimestampServer = 'http://timestamp.digicert.com',
    # Only for testing the pipeline with a self-signed certificate.
    [switch]$AllowUntrustedRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try {
    if ($PfxPath) {
        $password = $env:SYNC_AGENT_SIGN_PASSWORD
        $flags = [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet
        $certificate = New-Object Security.Cryptography.X509Certificates.X509Certificate2((Resolve-Path -LiteralPath $PfxPath).Path, $password, $flags)
    } elseif ($Thumbprint) {
        $certificate = Get-Item -LiteralPath ('Cert:\CurrentUser\My\' + $Thumbprint.Replace(' ', ''))
    } else {
        throw 'Provide -PfxPath or -Thumbprint.'
    }
    if (-not $certificate.HasPrivateKey) { throw 'The certificate has no private key.' }
    $codeSigning = '1.3.6.1.5.5.7.3.3'
    $usages = @($certificate.Extensions | Where-Object { $_ -is [Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension] } |
        ForEach-Object { $_.EnhancedKeyUsages } | ForEach-Object { $_.Value })
    if ($usages -notcontains $codeSigning) { throw 'The certificate is not valid for code signing.' }

    foreach ($file in $Path) {
        $target = (Resolve-Path -LiteralPath $file).Path
        $result = Set-AuthenticodeSignature -LiteralPath $target -Certificate $certificate -HashAlgorithm SHA256 `
            -TimestampServer $TimestampServer -IncludeChain NotRoot
        $check = Get-AuthenticodeSignature -LiteralPath $target
        $acceptable = @('Valid') + $(if ($AllowUntrustedRoot) { @('UnknownError', 'NotTrusted') } else { @() })
        if (-not $check.SignerCertificate -or $check.SignerCertificate.Thumbprint -ne $certificate.Thumbprint -or $check.Status -notin $acceptable) {
            throw "Signature verification failed for $target ($($check.Status): $($check.StatusMessage))"
        }
        $stamp = if ($check.TimeStamperCertificate) { 'timestamped' } else { 'NOT timestamped' }
        Write-Host "Signed $target ($($check.Status), $stamp)"
    }
    exit 0
} catch { Write-Error $_; exit 1 }
