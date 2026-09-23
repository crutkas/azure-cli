# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
param(
    [ValidateSet('x86', 'x64', 'arm64')]
    [string]$Architecture = $(if ($env:PLATFORM) { $env:PLATFORM } else { 'x64' })
)

$ErrorActionPreference = 'Stop'
$Architecture = $Architecture.ToLowerInvariant()

if (-not $env:SYSTEM_ARTIFACTSDIRECTORY) {
    throw 'SYSTEM_ARTIFACTSDIRECTORY must identify the downloaded artifacts.'
}
$previousConfig = $env:AZURE_CONFIG_DIR
$previousExtensions = $env:AZURE_EXTENSION_DIR
try {
    $env:AZURE_CONFIG_DIR = "$env:SYSTEM_ARTIFACTSDIRECTORY\zip\smoke-config"
    $env:AZURE_EXTENSION_DIR = "$env:SYSTEM_ARTIFACTSDIRECTORY\zip\smoke-extensions"
    $root = "$env:SYSTEM_ARTIFACTSDIRECTORY\zip\Azure CLI"
    if (Test-Path $root) {
        throw "Use a fresh artifact directory; refusing to test over a stale extraction: $root"
    }
    Write-Output "Extracting zip to $root"
    $zipName = if ($Architecture -eq 'arm64') { 'Microsoft Azure CLI arm64.zip' } else { 'Microsoft Azure CLI.zip' }
    & "C:\Program Files\7-Zip\7z.exe" x -y "-o$root" "$env:SYSTEM_ARTIFACTSDIRECTORY\zip\$zipName"
    if ($LASTEXITCODE -ne 0) { throw "ZIP extraction failed: $LASTEXITCODE" }
    $az_full_path = "$root\bin\az.cmd"

    & "$root\python.exe" -I "$PSScriptRoot\verify_runtime.py" --root $root --arch $Architecture --all
    if ($LASTEXITCODE -ne 0) { throw "Packaged runtime architecture check failed: $LASTEXITCODE" }
    & $az_full_path --version
    if ($LASTEXITCODE -ne 0) { throw "CLI startup failed: $LASTEXITCODE" }
    $installed_version = & $az_full_path version --query '\"azure-cli\"' -o tsv
    if ($LASTEXITCODE -ne 0) { throw "CLI version query failed: $LASTEXITCODE" }
    $artifact_version = Get-Content "$env:SYSTEM_ARTIFACTSDIRECTORY\metadata\version"
    Write-Output "Installed version: $installed_version; artifact version: $artifact_version"
    if ($installed_version -ne $artifact_version) {
        throw "The installed version doesn't match the artifact version."
    }

    if ($Architecture -eq 'arm64') {
        & "$root\python.exe" -I "$PSScriptRoot\..\tests\test_native_dependencies.py"
        if ($LASTEXITCODE -ne 0) { throw "Native dependency regression tests failed: $LASTEXITCODE" }
    }
    & $az_full_path cloud list --query '[].name' -o tsv
    if ($LASTEXITCODE -ne 0) { throw "Local cloud query failed: $LASTEXITCODE" }
    & $az_full_path extension add -n account --yes
    if ($LASTEXITCODE -ne 0) { throw "Extension installation failed: $LASTEXITCODE" }
    & $az_full_path self-test
    if ($LASTEXITCODE -ne 0) { throw "CLI self-test failed: $LASTEXITCODE" }
} finally {
    $env:AZURE_CONFIG_DIR = $previousConfig
    $env:AZURE_EXTENSION_DIR = $previousExtensions
}
