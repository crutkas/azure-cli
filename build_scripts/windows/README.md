Building the Windows MSI
========================

This document provides instructions on creating the MSI.

Prerequisites
-------------

1. Turn on the '.NET Framework 3.5' Windows Feature (required for WIX Toolset).

2. Install 'WIX Toolset build tools' if not already installed. (e.g. WiX v3.10.3)
    http://wixtoolset.org/releases/

3. Get Git for Windows (it has several tools used for the build).
    - https://github.com/git-for-windows/git/releases/download/v2.12.2.windows.1/Git-2.12.2-32-bit.exe
    - Choose the 'Use Git and optional Unix tools from the Windows Command Prompt' option.

4. Install 'Microsoft Build Tools 2015'.
    https://www.microsoft.com/download/details.aspx?id=48159

5. Clone the repository.
    - git clone https://github.com/azure/azure-cli

Note: The above can be done on a Windows 10 VM.

Building
--------

1. Set the `CLI_VERSION` environment variable.

2. Run `build_scripts\windows\scripts\build.cmd`.

3. The unsigned MSI will be in the `.\out` folder.

Windows ARM64 candidates (not a production release)
--------------------------------------------------

The implementation plan is [ARM64-plan.md](ARM64-plan.md). ARM64 is opt-in:
the default remains x86 MSI, and existing x86/x64 artifact names are unchanged.
No ARM64 package is connected to production signing or publication.

Use a **native Windows ARM64** build host with `curl.exe`, Windows PowerShell,
and 7-Zip at `C:\Program Files\7-Zip\7z.exe`. MSI additionally requires MSBuild
and the .NET Framework needed by WiX. Download/extraction uses PowerShell;
Git's `unzip.exe` is no longer required. The build executes the target Python,
so cross-building ARM64 on x64 is deliberately rejected.

From a developer Command Prompt at the repository root:

```bat
set CLI_VERSION=2.90.0
set ARCH=arm64
set TARGET=zip
build_scripts\windows\scripts\build.cmd --check
build_scripts\windows\scripts\build.cmd
```

Use the version in `src\azure-cli\azure\cli\__main__.py`, rather than copying the
example version after a release bump. `--check` validates architecture/target
selection and prints runtime/toolchain URLs without cleaning or downloading.
The build itself replaces the existing `build_scripts\windows\out` and staging
directories; do not run multiple architectures concurrently in one worktree.

The ZIP candidate is `build_scripts\windows\out\Microsoft Azure CLI arm64.zip`.
Extract it and invoke `bin\az.cmd`; do not add an unvalidated candidate to the
system PATH. To compile the unsigned MSI candidate, use `set TARGET=msi`.
Its name is `Microsoft Azure CLI arm64.msi`.
`az upgrade` is explicitly blocked for native ARM64 MSI/ZIP candidates. This is
an **interim safety limitation, not completed ARM64 upgrade support**: it must
not download an x64 MSI or direct users to an x64 ZIP. PIP and existing x86/x64
upgrade behavior is unchanged. Enabling ARM64 upgrades requires approved signed
ARM64 artifacts, architecture-specific production MSI/ZIP URLs, version metadata
and publishing/retention wiring, and native upgrade/rollback-policy validation.
Only then should the guard be replaced by explicit ARM64 URL selection and
end-to-end tests; do not reuse the x64 endpoints.

Runtime caches include Python version and target architecture. ARM64 uses the
official Python 3.14.7 embeddable runtime and a separate WiX 3.14.1 cache
(`wix3141rtm`), whose compiler and custom actions support ARM64. x86/x64 keep
the existing WiX 3.10 toolchain. Failed downloads or dependency resolution are
fatal; remove only the affected incomplete cache before retrying.

### Dependency and runtime gates

Shared Windows requirements remain unchanged. After verifying the target
interpreter, `prepare_arm64_requirements.py` selects bcrypt 5.0.0 and psutil 7.2.2
only for an explicit ARM64 build and retains the generated manifest in `out`.
It refuses changed or ambiguous baseline pins until the policy is reviewed.
Do not use `platform_machine` markers: x86/x64 Python under ARM64 emulation also
reports `ARM64`, which would break x86 wheel selection. This preserves the
existing non-ARM64 pins (notably the psutil x86 wheel). ARM64 native dependencies
must install from wheels; cryptography is **not** downgraded or replaced with an
unpublished version. See [dependency-audit.md](dependency-audit.md) for the dated,
complete requirements audit and outstanding wheel blockers.
Released-package metadata checked on 2026-09-23 identifies separate blockers:

| Dependency | Current requirement | Released-update status |
| --- | --- | --- |
| cryptography 48.0.1 | Official Windows ARM64 wheel required | None in any published 48.x-50.x release; latest is 50.0.1, with no published 51 release |
| MSAL 1.39.0 | `cryptography>=2.5,<51` | 1.39.0 is still the latest stable release; no 51-compatible update |
| pyOpenSSL 26.2.0 | `cryptography>=46.0.0,<49` | Newer 26.4.0 requires `>=49.0.0,<51`, so it still cannot enable cryptography 51 |

Cryptography 51 alone is therefore insufficient. A supported release needs
coordinated, tested dependency upgrades satisfying all constraints, not
`--no-deps` or resolver bypasses. The 143-distribution wheel/metadata inventory
is not a successful full transitive resolution; the candidate build must still
resolve dependencies normally and pass `pip check`.

The build checks `pip check`, real native dependency regressions, and PE machine
types before producing an ARM64 artifact. `verify_runtime.py` checks `.exe`,
`.dll`, and `.pyd` files, not just Python's reported bitness. pip's six bundled
distlib launcher templates and setuptools' eight launcher templates are checked
against their individual declared architectures because they are data used to
generate entry points.

The official Python ZIP also includes an **incidental ARM64EC CRT companion**,
not a required classic-ARM64 dependency. Native Python and tested stdlib imports
succeed without loading it. The verifier recognizes only its exact upstream
hash at the runtime root and reports it separately; it does not accept arbitrary
x64/ARM64EC dependencies. See [runtime-arm64.md](runtime-arm64.md) for artifact
provenance, PE/hybrid metadata, upstream context, and actual load evidence.
This is not classified as a Python runtime blocker, and no CRT is deleted,
replaced, or installed system-wide.

No experimental cryptography artifact is selected automatically. Introducing
one requires explicit opt-in, a pinned upstream commit, artifact SHA-256 and
provenance, and separate non-production labeling. Upstream dev builds must not
silently replace the production pin.

### Validation and CI

Run dependency tests and binary verification with the **packaged** interpreter:

```bat
build_scripts\windows\artifacts\cli\python.exe -I build_scripts\windows\tests\test_windows_packaging.py
build_scripts\windows\artifacts\cli\python.exe -I build_scripts\windows\tests\test_msi_architecture.py
build_scripts\windows\artifacts\cli\python.exe -I build_scripts\windows\tests\test_upgrade_architecture.py
build_scripts\windows\artifacts\cli\python.exe -I build_scripts\windows\tests\test_native_dependencies.py
build_scripts\windows\artifacts\cli\python.exe -I build_scripts\windows\scripts\verify_runtime.py --root build_scripts\windows\artifacts\cli --arch arm64 --all
```

`test_zip_installation.ps1 -Architecture arm64` expects the ZIP under
`$env:SYSTEM_ARTIFACTSDIRECTORY\zip` and the CLI version under `metadata\version`.
It checks the extracted runtime, version, native dependencies, local cloud
listing, extension installation, and `az self-test`. Extension/configuration
writes are isolated under the artifact directory. Extension installation needs
network access but not Azure credentials.

The manual pipeline `.azure-pipelines\windows-arm64-validation.yml` requires an
explicitly supplied, approved **native ARM64** pool. None is invented in the
shared pool variables. It has no automatic trigger, fails on missing wheels or
wrong-architecture binaries, and retains only successfully validated, unsigned
candidates. Its optional MSI lane compiles but does not install an MSI on a
shared agent. Main Windows CI runs architecture-policy tests while retaining
the existing x86/x64 build matrices.

See [msi-arm64.md](msi-arm64.md) for installer policy and disposable-host
lifecycle validation. Cross-architecture MSI installation is refused, not
silently migrated or allowed to overwrite a shared install directory.
Release-owner approval of that policy remains required.
MSI fixture compilation and MSI-table inspection are not a full CLI MSI build
or installation result. WiX's minimal UI still includes an x86 EULA-print
helper; its emulated interactive behavior also needs native-host validation.

Before production support, validate x86/x64 package regressions; native ARM64
ZIP and MSI lifecycle; broker, browser, and service-principal authentication;
and extension/native-helper compatibility. Credentials and Azure resource
creation are not needed for the offline suite and require separate approval
for integration tests. Internal pool provisioning, signing/SBOM/publication
jobs, external installation docs, and package-manager manifests also remain
release-owner prerequisites. This repository does not contain the Windows
production signing/publishing definition.

### Optional downloaded tools and extensions

Native core packaging does not make every externally downloaded tool native.
The current source already selects `win-arm64` for Bicep and AKS Desktop.
However, `acs.custom.k8s_install_kubelogin` selects `windows_amd64` on Windows,
and `storage.azcopy.util` selects Windows x64/x86 downloads by bitness.
Those helpers are downloaded on demand, not bundled in the core ZIP/MSI; their
ARM64 distribution and integration tests need separate validation. Do not claim
native coverage based on successful execution through Windows emulation.

The extension index currently selects universal wheels
(`core.extension._resolve._is_not_platform_specific`). Those extensions can
still depend on native packages or download executable helpers. The `account`
extension smoke test verifies bundled pip, not compatibility of every extension.
