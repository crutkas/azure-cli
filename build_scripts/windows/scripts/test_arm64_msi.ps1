#requires -Version 7.2
<#
.SYNOPSIS
Destructive MSI release gate, ONLY for an explicitly disposable, elevated native ARM64 host.
.DESCRIPTION
Requires two increasing ARM64 releases and newly built x86/x64 packages containing the
ARM64 collision guard. Refuses pre-existing CLI installations. Never reboots the host.
Uninstalls only product codes read from the supplied, validated packages after a clean baseline.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$MsiPath,
    [Parameter(Mandatory)][string]$UpgradeMsiPath,
    [Parameter(Mandatory)][string]$X86MsiPath,
    [Parameter(Mandatory)][string]$X64MsiPath,
    [switch]$DisposableHost
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $DisposableHost) { throw 'Refusing installation: specify -DisposableHost only on a disposable test host.' }
if (-not $IsWindows -or
    [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'Arm64' -or
    [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'Arm64') {
    throw 'Run native ARM64 PowerShell 7.2+ on native ARM64 Windows.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'An elevated disposable host is required.'
}

$upgradeCodes = @{
    x86 = '{DFF82AF0-3F95-4AC9-8EFD-948604FDB028}'
    x64 = '{90762FEC-9554-4729-A107-C6A8EA316698}'
    arm64 = '{A26A9A9E-7E9A-4A41-BF5A-54CD57A028F8}'
}
$installer = New-Object -ComObject WindowsInstaller.Installer
$runtimeVerifier = Join-Path $PSScriptRoot 'verify_runtime.py'
if (-not (Test-Path -LiteralPath $runtimeVerifier -PathType Leaf)) {
    throw 'The repository runtime architecture verifier is required.'
}

function Read-MsiValue($Database, [string]$Query) {
    $view = $Database.OpenView($Query)
    try {
        $view.Execute()
        $record = $view.Fetch()
        if ($null -eq $record) { throw "Missing MSI data: $Query" }
        return $record.StringData(1)
    } finally {
        $view.Close()
    }
}

function Read-Package([string]$Path, [string]$Architecture) {
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ([IO.Path]::GetExtension($resolved) -ne '.msi' -or $resolved.Contains('"')) {
        throw "Expected an MSI file: $resolved"
    }
    $database = $installer.OpenDatabase($resolved, 0)
    $summary = $database.SummaryInformation(0)
    $template = ($summary.Property(7) -split ';')[0]
    $expectedTemplate = @{ x86 = 'Intel'; x64 = 'x64'; arm64 = 'Arm64' }[$Architecture]
    if ($template -ne $expectedTemplate) { throw "Wrong architecture in $resolved`: $template" }
    $code = Read-MsiValue $database 'SELECT `Value` FROM `Property` WHERE `Property` = ''ProductCode'''
    $upgrade = Read-MsiValue $database 'SELECT `Value` FROM `Property` WHERE `Property` = ''UpgradeCode'''
    $name = Read-MsiValue $database 'SELECT `Value` FROM `Property` WHERE `Property` = ''ProductName'''
    $version = Read-MsiValue $database 'SELECT `Value` FROM `Property` WHERE `Property` = ''ProductVersion'''
    if ($upgrade -ne $upgradeCodes[$Architecture] -or $name -notlike 'Microsoft Azure CLI (*') {
        throw "Not the expected Azure CLI $Architecture product: $resolved"
    }
    [void][guid]::Parse($code)
    if ($Architecture -eq 'arm64' -and [int]$summary.Property(14) -lt 500) {
        throw 'ARM64 requires Windows Installer 5.0.'
    }
    $others = if ($Architecture -eq 'arm64') { @('x86', 'x64') } else { @('arm64') }
    foreach ($other in $others) {
        $property = 'AZURECLI_' + $other.ToUpperInvariant() + '_INSTALLED'
        $attributes = Read-MsiValue $database (
            'SELECT `Attributes` FROM `Upgrade` WHERE `ActionProperty` = ''' + $property + '''')
        if (([int]$attributes -band 2) -eq 0) { throw "Unsafe cross-architecture removal in $resolved" }
        $message = if ($Architecture -eq 'arm64') {
            'Uninstall the existing x86 or x64 Microsoft Azure CLI manually before installing the ARM64 edition.'
        } else {
            'Uninstall the existing ARM64 Microsoft Azure CLI manually before installing another architecture.'
        }
        $condition = Read-MsiValue $database (
            'SELECT `Condition` FROM `LaunchCondition` WHERE `Description` = ''' + $message + '''')
        if (-not $condition.Contains($property)) { throw "Missing collision guard in $resolved" }
    }
    return [pscustomobject]@{
        Path = $resolved; Code = $code; Version = [version]$version; Architecture = $Architecture
    }
}

function Get-CliProducts {
    foreach ($upgradeCode in $upgradeCodes.Values) {
        foreach ($product in $installer.RelatedProducts($upgradeCode)) { $product }
    }
}

function Assert-Installed($Package) {
    if ($Package.Code -notin @(Get-CliProducts)) { throw "Product not installed: $($Package.Code)" }
}

$packages = @(
    (Read-Package $MsiPath 'arm64'),
    (Read-Package $UpgradeMsiPath 'arm64'),
    (Read-Package $X86MsiPath 'x86'),
    (Read-Package $X64MsiPath 'x64')
)
$initial, $upgrade, $x86, $x64 = $packages
if ($upgrade.Version -le $initial.Version) { throw 'UpgradeMsiPath must have a strictly newer ProductVersion.' }
if (@($packages.Code | Select-Object -Unique).Count -ne 4) { throw 'Each package must have a distinct ProductCode.' }
if (@(Get-CliProducts).Count) { throw 'Existing Azure CLI MSI found. No installation or uninstallation was attempted.' }

# Detect legacy/unmanaged installations as well; never remove them to prepare a test machine.
$roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ } | Select-Object -Unique
$cliDirectories = @($roots | ForEach-Object { Join-Path $_ 'Microsoft SDKs\Azure\CLI2' })
foreach ($directory in $cliDirectories) {
    if (Test-Path -LiteralPath $directory) { throw "Pre-existing CLI directory: $directory" }
}
foreach ($view in [Microsoft.Win32.RegistryView]::Registry32, [Microsoft.Win32.RegistryView]::Registry64) {
    foreach ($hive in [Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryHive]::CurrentUser) {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
        try {
            $key = $base.OpenSubKey('Software\Microsoft\Microsoft Azure CLI')
            if ($null -ne $key) { $key.Dispose(); throw 'Pre-existing CLI registry state.' }
            $uninstall = $base.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall')
            if ($null -ne $uninstall) {
                try {
                    foreach ($subkey in $uninstall.GetSubKeyNames()) {
                        $entry = $uninstall.OpenSubKey($subkey)
                        try {
                            if ($entry.GetValue('DisplayName', '') -like '*Azure CLI*') {
                                throw 'Pre-existing Azure CLI uninstall registration.'
                            }
                        } finally { $entry.Dispose() }
                    }
                } finally { $uninstall.Dispose() }
            }
        } finally { $base.Dispose() }
    }
}
$baselinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($baselinePath -match '(?i)Microsoft SDKs\\Azure\\CLI2') { throw 'Pre-existing CLI machine PATH entry.' }
if (Get-Command az -ErrorAction SilentlyContinue) { throw 'An existing az command is on PATH.' }

$logs = Join-Path $PSScriptRoot ('..\artifacts\arm64-msi-lifecycle\' + [guid]::NewGuid())
[void](New-Item -ItemType Directory -Path $logs)
$logs = (Resolve-Path $logs).Path
$script:sequence = 0
$ownedCodes = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)

function Invoke-Msi([string[]]$Arguments, [string]$Label, [int]$ExpectedExitCode = 0) {
    $script:sequence++
    $log = Join-Path $logs ('{0:D2}-{1}.log' -f $script:sequence, $Label)
    $process = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -Wait -PassThru -ArgumentList (
        $Arguments + @('/qn', '/norestart', 'REBOOT=ReallySuppress', '/l*v', "`"$log`""))
    if ($process.ExitCode -eq 3010) {
        throw "MSI succeeded but requires reboot (3010); lifecycle gate is incomplete. Reboot/reset the disposable host. Log: $log"
    }
    if ($process.ExitCode -ne $ExpectedExitCode) {
        throw "$Label returned $($process.ExitCode), expected $ExpectedExitCode. Log: $log"
    }
    if ($ExpectedExitCode -eq 1603 -and
        -not (Select-String -LiteralPath $log -SimpleMatch 'Uninstall the existing' -Quiet)) {
        throw "1603 was not the intended cross-architecture launch-condition failure: $log"
    }
}

function Install-Owned($Package, [string]$Label) {
    # Mark only our validated product codes before invoking MSI, so partial failures can be cleaned up.
    [void]$ownedCodes.Add($Package.Code)
    Invoke-Msi @('/i', "`"$($Package.Path)`"") $Label
    Assert-Installed $Package
}

function Remove-Owned($Package, [string]$Label) {
    if (-not $ownedCodes.Contains($Package.Code)) { throw 'Refusing to uninstall an unowned product.' }
    Invoke-Msi @('/x', $Package.Code) $Label
    if ($Package.Code -in @(Get-CliProducts)) { throw 'Uninstall left the product registered.' }
}

function Assert-NativeCli($Package) {
    $directory = Join-Path $env:ProgramFiles 'Microsoft SDKs\Azure\CLI2'
    $python = Join-Path $directory 'python.exe'
    $bytes = [IO.File]::ReadAllBytes($python)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ([BitConverter]::ToUInt16($bytes, $peOffset + 4) -ne 0xaa64) { throw 'Installed Python is not ARM64.' }
    & $python -I -c "import platform, struct; assert platform.machine().upper() == 'ARM64'; assert struct.calcsize('P') == 8"
    if ($LASTEXITCODE -ne 0) { throw "Native Python validation returned $LASTEXITCODE" }
    & $python -I $runtimeVerifier --root $directory --arch arm64 --all
    if ($LASTEXITCODE -ne 0) { throw "Runtime architecture verification returned $LASTEXITCODE" }
    $az = Join-Path $directory 'wbin\az.cmd'
    & $az --version
    if ($LASTEXITCODE -ne 0) { throw "az --version returned $LASTEXITCODE" }
    & $az --help
    if ($LASTEXITCODE -ne 0) { throw "az --help returned $LASTEXITCODE" }
    $pathEntry = Join-Path $directory 'wbin'
    $entries = @(([Environment]::GetEnvironmentVariable('Path', 'Machine') -split ';') |
        Where-Object { $_.TrimEnd('\') -eq $pathEntry })
    if ($entries.Count -ne 1) { throw 'Expected exactly one ARM64 CLI machine PATH entry.' }
    $version = Get-ItemPropertyValue 'HKLM:\Software\Microsoft\Microsoft Azure CLI' -Name version
    if ([version]$version -ne $Package.Version) { throw "Unexpected registry version: $version" }
}

try {
    Install-Owned $initial 'arm64-install'
    Assert-NativeCli $initial
    Invoke-Msi @('/fa', $initial.Code) 'arm64-repair'
    Assert-NativeCli $initial
    Install-Owned $upgrade 'arm64-upgrade'
    if ($initial.Code -in @(Get-CliProducts)) { throw 'Upgrade left the old ARM64 product registered.' }
    Assert-NativeCli $upgrade
    foreach ($other in @($x86, $x64)) {
        [void]$ownedCodes.Add($other.Code)
        Invoke-Msi @('/i', "`"$($other.Path)`"") "$($other.Architecture)-over-arm64-blocked" 1603
        if ($other.Code -in @(Get-CliProducts)) { throw 'Blocked product was installed.' }
        Assert-Installed $upgrade
        Assert-NativeCli $upgrade
    }
    Remove-Owned $upgrade 'arm64-uninstall'
    foreach ($other in @($x86, $x64)) {
        Install-Owned $other "$($other.Architecture)-install"
        $before = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        Invoke-Msi @('/i', "`"$($initial.Path)`"") "arm64-over-$($other.Architecture)-blocked" 1603
        Assert-Installed $other
        if ($initial.Code -in @(Get-CliProducts)) { throw 'Blocked ARM64 product was installed.' }
        if ([Environment]::GetEnvironmentVariable('Path', 'Machine') -ne $before) {
            throw 'Blocked ARM64 install changed PATH.'
        }
        Remove-Owned $other "$($other.Architecture)-uninstall"
    }
} finally {
    # Never enumerate-and-uninstall arbitrary products, even on a disposable machine.
    foreach ($code in $ownedCodes) {
        if ($code -in @(Get-CliProducts)) {
            Invoke-Msi @('/x', $code) 'cleanup-owned-product'
        }
    }
}
if (@(Get-CliProducts).Count) { throw 'CLI products remain after lifecycle test.' }
if ([Environment]::GetEnvironmentVariable('Path', 'Machine') -ne $baselinePath) {
    throw 'Uninstall did not restore machine PATH.'
}
foreach ($directory in $cliDirectories) {
    if (Test-Path -LiteralPath $directory) { throw "Uninstall left files: $directory" }
}
foreach ($view in [Microsoft.Win32.RegistryView]::Registry32, [Microsoft.Win32.RegistryView]::Registry64) {
    foreach ($hive in [Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryHive]::CurrentUser) {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
        try {
            $key = $base.OpenSubKey('Software\Microsoft\Microsoft Azure CLI')
            if ($null -ne $key) {
                try {
                    if (@($key.GetValueNames()).Count) { throw 'Uninstall left CLI registry values.' }
                } finally { $key.Dispose() }
            }
        } finally { $base.Dispose() }
    }
}
Write-Host "ARM64 MSI lifecycle gates passed. Logs: $logs"
