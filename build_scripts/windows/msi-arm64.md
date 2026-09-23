# ARM64 MSI: bounded support and release gates

The installer remains a **WiX 3** project. ARM64 builds use WiX **3.14.1**
(`wix3141rtm`, compiler 3.14.1.8722) from the separate
`artifacts\wix-arm64-3.14.1` cache. x86/x64 retain the existing WiX 3.10 cache
(`artifacts\wix`). Do not replace either toolset with WiX 4 or reuse the x86/x64
cache for ARM64. Use `Platform=arm64`, which also supplies Candle's architecture
default to the Heat-generated components. A successful compile alone is not a
native installation qualification.
The ARM64 output is `Microsoft Azure CLI arm64.msi`; x86/x64 keep the existing
`Microsoft Azure CLI.msi` name.

## Conservative architecture policy — release-owner approval required

ARM64 and x64 both install under
`ProgramFiles64Folder\Microsoft SDKs\Azure\CLI2`; PATH and registry state also
overlap. **ARM64 is not a side-by-side installation or an automatic architecture
migration.** The release owner must approve this policy before distribution:

* ARM64 installation detects any version of the x86 and x64 MSI families and
  fails with an explicit instruction to uninstall them manually.
* Newly built x86/x64 installers similarly reject an existing ARM64 MSI.
* Cross-architecture detection is `OnlyDetect`; it never schedules removal.
  Existing x86-to-x64 migration behavior is unchanged when ARM64 is absent.
* Maintenance of an installed product remains possible. ARM64 upgrades remove
  only older ARM64 products; downgrades remain blocked. Equal-version packages
  are not a supported major-upgrade mechanism; use repair of the installed MSI.
* Already published x86/x64 MSI binaries do **not** acquire the new reverse
  guard. Do not install those packages over ARM64. Deployment systems must
  enforce the same manual-uninstall policy, including rollback to older releases.
* ZIP/manual installations are outside MSI Upgrade-table detection. Remove any
  conflicting manually managed installation/PATH entry before installation.

ARM64 has a stable, separate UpgradeCode
`A26A9A9E-7E9A-4A41-BF5A-54CD57A028F8`, five separate authored component GUIDs,
and a separate directory GUID-generation seed for harvested components. Never
regenerate these per release. x86/x64 UpgradeCodes and component identities are
unchanged. ARM64 uses Windows Installer 5.0, 64-bit components and registry view,
and the native `WixBroadcastEnvironmentChange_A64` action. WiX 3.14.1's standard
minimal UI retains the x86 EULA-print helper; validate that UI path on the target
Windows ARM64 version rather than assuming every bundled helper is native.

## Validation

Source-contract tests need only Python's standard library:

```powershell
python -m unittest discover -s build_scripts\windows\tests -p test_msi_architecture.py -v
```

Before distribution, retain build evidence for all three architectures:

* ARM64 MSI summary platform `Arm64`, schema version `500`; x86/x64 remain
  `Intel`/`x64` and `200`.
* All ARM64 authored and harvested components carry the 64-bit attribute.
  Harvested component GUIDs differ from x64 for the same relative file.
* Upgrade/LaunchCondition tables contain the unbounded-above, detect-only
  architecture guards, in both UI and silent execution paths.
* `WixBroadcastEnvironmentChange_A64` resolves to the `WixCA_A64` binary with
  PE machine `0xAA64`. Validate the native Python and native extension payload,
  not just MSI metadata.
* Run the normal full installer build and ICE validation in the release build
  environment. A tiny fixture linked with `light -sval` does not cover those.

### Destructive native-host qualification

**Never run this on a shared/developer machine.** Use an explicitly disposable,
clean Windows ARM64 VM/host, elevated **native ARM64 PowerShell 7.2+**, and four
locally built packages: two strictly increasing ARM64 versions and x86/x64
packages that include the new reverse guard.

```powershell
.\build_scripts\windows\scripts\test_arm64_msi.ps1 `
  -DisposableHost `
  -MsiPath 'C:\packages\azure-cli-arm64-old.msi' `
  -UpgradeMsiPath 'C:\packages\azure-cli-arm64-new.msi' `
  -X86MsiPath 'C:\packages\azure-cli-x86.msi' `
  -X64MsiPath 'C:\packages\azure-cli-x64.msi'
```

The script refuses pre-existing MSI, directory, registry, or PATH installations.
It tests fresh install, native Python and CLI execution, all payload PE files
via `verify_runtime.py` using the installed interpreter, repair, ARM64 upgrade,
both cross-architecture blocking directions, uninstall, and PATH/registry/file
cleanup. It uninstalls only validated supplied product codes after a clean
baseline, never arbitrary existing installations. Logs stay in the repository's
`build_scripts\windows\artifacts\arm64-msi-lifecycle` directory.

Success requires exit `0` from successful MSI operations. A blocked installation
must return exactly `1603` and log the intended manual-uninstall launch condition;
an arbitrary MSI failure is not proof of a guard. Exit `3010` means installation
succeeded but reboot is required: the qualification is incomplete, and the
script stops without rebooting. Any other unexpected exit, including `1641`,
fails the gate. Reset/reboot the disposable host and rerun as appropriate.

Also qualify interactive install (including EULA print), maintenance, downgrade
rejection, PATH propagation to a fresh terminal, reboot-required behavior, and
upgrade/repair/uninstall of the actual signed release payload. Preserve logs and
obtain release-owner sign-off; static tests and fixture compilation do not
substitute for these native lifecycle gates.
