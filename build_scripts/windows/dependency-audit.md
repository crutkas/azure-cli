# Windows ARM64 dependency gate

## Policy

The Windows requirement file retains default x86/x64 pins. ARM64 packaging
explicitly selects these bounded overrides using the verified interpreter target:

| Package | Windows x86/x64 (unchanged) | Native Windows ARM64 |
| --- | --- | --- |
| bcrypt | 3.2.0 | 5.0.0 |
| psutil | 6.1.0 | 7.2.2 |
| cryptography | 48.0.1 | 48.0.1 — **no published compatible wheel** |

Do **not** use `platform_machine == "ARM64"` requirement markers for this
selection. Real emulation testing on the native ARM64 host found:

| Official embedded CPython 3.14.7 | `platform.machine()` | `sysconfig.get_platform()` | Pointer bits |
| --- | --- | --- | --- |
| ARM64 | `ARM64` | `win-arm64` | 64 |
| x64 under emulation | `ARM64` | `win-amd64` | 64 |
| x86 under emulation | `ARM64` | `win32` | 32 |

Such markers incorrectly select psutil 7.2.2 for emulated x86, which has no
matching wheel. The initial marker proposal was therefore removed. Pip marker
syntax supports architecture comparisons, but `platform_machine` is not proof
of the interpreter architecture on this host.

For `ARCH=arm64`, `build_scripts\windows\scripts\build.cmd` invokes
`scripts\prepare_arm64_requirements.py` (relative to `build_scripts\windows`)
only after the embedded interpreter passes PE architecture validation. The
selector also requires `sysconfig.get_platform() == "win-arm64"` and fails
unless it finds exactly the expected original bcrypt 3.2.0 and psutil 6.1.0 pins.
It replaces only those two pins, leaves all shared pins unchanged, and writes
generated scratch requirements used by the build. A copy is retained at
`out\requirements.arm64.txt`.

This uses the explicit build target and verified interpreter, not the native OS
architecture. Passing conflicting overrides alongside the original pins is not
a valid pip constraint strategy. Direct installation of the default file on
ARM64 remains unsupported.

Linux and Darwin requirement files are unchanged. Do not globally upgrade psutil,
downgrade cryptography to obtain an ARM64 wheel, float a Git branch, substitute
an x64 binary, or disable broker authentication.

**An ARM64 release remains blocked on cryptography.** A separately approved,
reproducible native build of the exact secure pin, or a reviewed published release
with compatible wheels and dependency constraints, is required. The requirement
file does not itself supply that artifact or authorize an unreviewed source build.
The packaging wheel gate must fail closed in its absence.

## PyPI audit, 2026-09-23

Queried `https://pypi.org/pypi/<name>/<version>/json` for every entry in the original
Windows requirement file: 143 distinct distributions, comprising 142 exact pins
and `azure-mgmt-redhatopenshift~=3.0.0`. The latter had only release 3.0.0 in the
compatible range at audit time. Counted non-yanked wheel filenames accepting the
ordinary GIL-enabled CPython 3.14 interpreter: `py3` universal wheels, exact
`cp314-cp314` platform wheels, and older CPython `abi3` wheels. Free-threaded
`cp314t` and PyPy wheels do not satisfy this target.

All 143 original entries had matching x86 and x64 wheel tags. Of these, 140 also
had matching ARM64 tags; the **only** ARM64 tag gaps were bcrypt 3.2.0, psutil
6.1.0, and cryptography 48.0.1. The ARM64-specific replacements reduce that to
one gap. The CLI, core, and telemetry packages are built from this repository
for packaging; their PyPI entries were included in this availability inventory,
not used as substitutes for the local build.

Precisely, the **baseline** audit covers those 143 distributions at their
checked-in versions. The **proposed ARM64 selection** still contains 143
distributions: bcrypt 5.0.0 replaces 3.2.0 and psutil 7.2.2 replaces 6.1.0;
the other 141 entries are unchanged. These two matrices require checking 145
distinct name/version combinations, not 145 installed distributions. Results
describe compatible, non-yanked wheel availability and file-level
`Requires-Python` compatibility for CPython 3.14.7, not a successfully resolved
and installed full transitive dependency closure.

| Native distribution | CPython 3.14 x86 | CPython 3.14 x64 | CPython 3.14 ARM64 |
| --- | --- | --- | --- |
| bcrypt 3.2.0 | `cp36-abi3-win32` | `cp36-abi3-win_amd64` | absent |
| bcrypt 5.0.0 | `cp39-abi3-win32` | `cp39-abi3-win_amd64` | `cp39-abi3-win_arm64` |
| psutil 6.1.0 | `cp37-abi3-win32` | `cp37-abi3-win_amd64` | absent |
| psutil 7.2.2 | absent | `cp37-abi3-win_amd64` | `cp37-abi3-win_arm64` |
| cryptography 48.0.1 | `cp39-abi3-win32` | `cp39-abi3-win_amd64` | absent |
| cffi 2.0.0 | `cp314-cp314-win32` | `cp314-cp314-win_amd64` | `cp314-cp314-win_arm64` |
| pymsalruntime 0.20.6 | `cp314-cp314-win32` | `cp314-cp314-win_amd64` | `cp314-cp314-win_arm64` |
| PyNaCl 1.6.2 | `cp38-abi3-win32` | `cp38-abi3-win_amd64` | `cp38-abi3-win_arm64` |
| pywin32 311 | `cp314-cp314-win32` | `cp314-cp314-win_amd64` | `cp314-cp314-win_arm64` |

The same release-JSON endpoints provide reproducible filenames, upload dates,
SHA-256 hashes, yanked status, and `Requires-Python` metadata. This inventory is
an availability snapshot, not a full transitive lock or a successful pip resolve:
installation must additionally validate metadata, transitive requirements and
`pip check`. In particular, the repository's requirements file is not a complete
hash-locked dependency closure (for example, cffi also requires pycparser).

The [cryptography 51.0.0 endpoint](https://pypi.org/pypi/cryptography/51.0.0/json)
returned HTTP 404; no 51.x releases were listed. The latest release was 50.0.1.
Do not treat an expected future release as installable. Even after publication,
a cryptography 51 upgrade cannot be made in isolation:

* **ARM64 artifact blocker:** the pinned cryptography 48.0.1 has no compatible
  release wheel; see its [release metadata](https://pypi.org/pypi/cryptography/48.0.1/json).
  Expected cryptography 51 is not published at this audit date.
* **MSAL compatibility blocker:** `msal[broker]==1.39.0`, also the latest stable
  MSAL at this audit date, requires `cryptography>=2.5,<51`.
  Sources: [1.39.0 metadata](https://pypi.org/pypi/msal/1.39.0/json) and
  [current release metadata](https://pypi.org/pypi/msal/json).
* **Pinned pyOpenSSL compatibility blocker:** `pyOpenSSL==26.2.0` requires
  `cryptography>=46.0.0,<49`; see
  [26.2.0 metadata](https://pypi.org/pypi/pyOpenSSL/26.2.0/json).
* **Latest pyOpenSSL is not a cryptography 51 solution:** the available stable
  `pyOpenSSL==26.4.0` requires `cryptography>=49,<51`; see
  [26.4.0 metadata](https://pypi.org/pypi/pyOpenSSL/26.4.0/json).
  Updating only that pin would still reject cryptography 51 and would also reject
  the existing cryptography 48.0.1 pin. No unrelated pyOpenSSL/MSAL upgrade is made.
* MSAL's Windows broker extra requires `pymsalruntime>=0.20,<0.21`; the existing
  0.20.6 pin already supplies a CPython 3.14 ARM64 wheel.
* Paramiko 5.0.0 permits `bcrypt>=3.2`, `cryptography>=3.3`, and `pynacl>=1.5`.
  Azure CLI core permits `psutil>=5.9` outside Cygwin. The scoped replacements
  satisfy these declared constraints.

Thus publication of cryptography 51 with an ARM64 wheel alone would not unblock
this dependency set. A coordinated, reviewed compatible set and a successful
full resolver/`pip check` run remain necessary; wheel presence is insufficient.

### Official upstream development artifact (not a release dependency)

[Upstream PR 15350](https://github.com/pyca/cryptography/pull/15350) promoted
Windows ARM64 support and wheel uploads, merged on 2026-09-02 as
`6ed4d3aa10454aba1cc844f3441f84cec039805a`. That source declares
`51.0.0-dev1`, not the CLI's 48.0.1 pin.

A concrete, non-expired experimental candidate existed on 2026-09-23:

* Official repository: `pyca/cryptography`.
* [Wheel Builder run 35586786589](https://github.com/pyca/cryptography/actions/runs/35586786589),
  successful on 2026-09-21; source head
  `cba0825bd536a0fe9d214fb043d9102e61e0dfbe`.
* That head belongs to upstream PR 15674, merged as
  `b80aa3226bd2cf2e50858af3e1e056bb07f0aeec`.
* Artifact ID `10633815237`, name `cryptography--arm64-3.14-abi3-py311`,
  size 3,331,142 bytes.
* GitHub-reported artifact archive SHA-256:
  `66de75562985f217638d198d41b1e34fea0a77c9c0bd11a6b02b8737dd2a4119`.
* [Immutable artifact endpoint](https://api.github.com/repos/pyca/cryptography/actions/artifacts/10633815237/zip);
  authenticated HEAD access succeeded. GitHub artifact retention still applies.

This is evidence that an upstream experimental ARM64 wheel exists, not approval
to use it in a package. The archive digest above is GitHub metadata, not an
independently verified wheel-file digest. Before any separately authorized
experiment, verify the downloaded archive hash, wheel metadata/version, individual
wheel hash and PE architecture. The development version does not satisfy
`cryptography==48.0.1`, and a newer version still conflicts with the declared
pyOpenSSL constraint. No alternate artifact input, production override, or
unbounded source reference is implemented here.

## Requirement tooling and consistency

`build_scripts\windows\scripts\build.cmd` uses the generated requirement file
for ARM64 and retains the default file for x86/x64. The implemented
`build_scripts\windows\scripts\prepare_arm64_requirements.py` selector is not a
full dependency lock generator; keep its expected original pins and two ARM64
replacement pins synchronized with the table above during reviewed updates.
`scripts\install_full.bat` still passes the default file directly to pip.
`scripts\ci\dependency_check.bat` installs via `install_full.bat` and runs
`pip check`; its `pip freeze` is only an uninstall baseline, not a generator for
the checked-in file. Pip supports PEP 508 markers syntactically but cannot fix
the emulation ambiguity above.

The package-version replacement in `scripts\regression_test\regression_test.yml`
uses `sed` to replace entire matching lines. It would erase markers if split
requirements were introduced. With explicit ARM64 selection it updates only the
default pin, not the target selector, so it does not exercise an ARM64 replacement
unless that selector is also deliberately updated.

Pip's cross-download
`--platform` does not generally override the marker environment; an x64 host
can still select its x64 pins for an ARM64 download, and an emulated interpreter
can report its native ARM64 host instead of its own architecture. A wheel
audit must select pins by explicit target. Native packaging must check
interpreter/module architecture separately, including emulated-host cases.
Neither successful marker parsing nor a wheel filename proves native execution.

## Behavioral regression gate

Run the new standalone unittest file using **each package's embedded Python**,
from a checkout whose `build_scripts\windows\artifacts` directory is writable:

```powershell
& '<package>\python.exe' -I '<repo>\build_scripts\windows\tests\test_native_dependencies.py' -v
```

It requires the package's installed dependencies and Azure CLI core/telemetry;
missing modules are failures, not skips. It does not require pytest, credentials,
SSH servers, network services, or mocks. Coverage includes:

* A published bcrypt_pbkdf known vector and sensitivity to bytes after byte 72.
* Generated RSA and Ed25519 encrypted OpenSSH keys, correct/wrong/missing
  passphrases, and passphrases longer than 72 bytes (including rejecting the
  truncated password and a changed suffix).
* Real Paramiko RSA/Ed25519 loading, public-key comparison, signing and
  verification, and rejection of incorrect/missing passphrases.
* Real psutil PID, executable name, parent, and creation-time observations.
* Azure CLI's cached/uncached shell-name helpers and telemetry session-ID helper
  in a real child process, with the expected hash computed from its actual parent.
  The test creates and removes an isolated configuration directory under
  `build_scripts\windows\artifacts`, routes the child process's configuration,
  extension and temporary-file paths there, and does not submit telemetry or
  touch the user's profile.

The bcrypt 5 `hashpw` password-length restriction is not the OpenSSH bcrypt KDF
contract; these tests exercise the latter, including long SSH passphrases.
No sshtunnel/Paramiko `DSSKey` compatibility workaround is included.

Passing on x64 validates behavior on x64 only. A real Windows ARM64 runner, the
native package, PE/module architecture checks, and its complete install/CLI smoke
tests remain mandatory before claiming native ARM64 validation.

### Validation performed on native ARM64

The repository-local embedded CPython 3.14.7 reports
`platform.machine() == "ARM64"`. Its isolated validation environment contains:
`bcrypt==5.0.0`, `psutil==7.2.2`, `cffi==2.0.0`, `PyNaCl==1.6.2`,
`pywin32==311`, `pymsalruntime==0.20.6`, `packaging==25.0`, and transitive
`pycparser==3.0`. No cryptography downgrade or development artifact was installed.

All three attainable regression tests passed natively:

```powershell
& .\build_scripts\windows\artifacts\validation-python\python.exe -I -B `
  .\build_scripts\windows\tests\test_native_dependencies.py -v `
  BcryptTests ProcessTests.test_current_process_and_parent
```

Imports of bcrypt, psutil, `_cffi_backend`, `nacl.bindings`, pymsalruntime, and
win32api also succeeded; win32api returned the real current process ID. This is
not an authenticated broker test or a complete PE architecture audit.

Rechecked the complete requirement matrix using `packaging.requirements`,
`packaging.tags`, `packaging.utils.parse_wheel_filename`, file-level
`Requires-Python`, and live PyPI JSON: 143 selected distributions per architecture
with the bounded ARM64 overrides, no x86/x64 wheel gaps, and only cryptography
48.0.1 missing for ARM64. Subsequent actual x86/x64 emulation testing invalidated
automatic `platform_machine` selection, not the availability of those wheel tags.
An actual binary-only pip download of cryptography 48.0.1 from both the configured
index and explicit `https://pypi.org/simple` failed with
`No matching distribution found`.

Encrypted OpenSSH/Paramiko tests and the full CLI shell/telemetry subprocess test
remain unexecuted on native ARM64: the secure cryptography pin cannot currently
be installed from an official compatible release wheel, and this validation
interpreter is not a fully installed CLI package. Those tests are not skipped by
the complete suite.
Native validation of three dependency behaviors does not establish a successful
full ARM64 package or remove the cryptography release gate.

The independent runtime investigation resolved the apparent CRT mismatch as an
**incidental ARM64EC companion, not a native runtime failure**. See
[CPython ARM64 runtime validation](runtime-arm64.md) for the exact artifact,
CHPE/debug metadata, native stdlib imports, and loaded-CRT evidence. The native
interpreter successfully loads its own `VCRUNTIME140.dll`; the companion
`vcruntime140_1.dll` is not normally loaded in those checks.

The runtime verifier permits only the documented companion at the runtime root
with SHA-256
`60c70e34e2e156f8bd214b92c2125c252e17d86ac8a25799ea1a4ecabde1d97c`,
reporting it separately from native code. Changed hashes, other locations, and
wrong-architecture dependencies still fail. The official runtime remains intact,
and any actual required dependency-load failure must still fail validation.
This narrow policy neither invalidates the three passing native dependency tests
nor removes the cryptography wheel and MSAL/pyOpenSSL version-constraint gates.

### EMULATED x64 encrypted-key validation

The separate official embedded CPython 3.14.7 interpreter under
`artifacts\marker-audit-x64` reports `sysconfig.get_platform() == "win-amd64"`
and runs through x64 emulation on the ARM64 host. **These results are not native
ARM64 validation.**

Installed published wheels into that isolated interpreter only:
`cryptography==48.0.1`, `paramiko==5.0.0`, `PyNaCl==1.6.2`, `cffi==2.0.0`,
`psutil==6.1.0`, `invoke==2.2.0`, and transitive `pycparser==3.0`.
First tested `bcrypt==5.0.0`, then replaced it with the original
`bcrypt==3.2.0` (which also installed transitive `six==1.17.0`). No cryptography
downgrade, development artifact, or dependency-constraint override was used.
This is a focused test environment, not an installation of every CLI pin.

The following command passed **four tests with bcrypt 5.0.0 and four tests with
bcrypt 3.2.0**; `pip check` also passed for both environments:

```powershell
& .\build_scripts\windows\artifacts\marker-audit-x64\python.exe -I -B `
  .\build_scripts\windows\tests\test_native_dependencies.py -v `
  BcryptTests OpenSSHTests
```

Both runs exercised the known KDF vector, sensitivity to bytes after byte 72,
RSA and Ed25519 encrypted OpenSSH keys, correct/wrong/missing/long passphrases,
and actual Paramiko loading, signing and public-key verification. The initial
run exposed test API assumptions, corrected before both passing runs: Paramiko
5 RSA signing needs an explicit SHA-2 algorithm, and Ed25519 verification needs
a public-key instance rather than the private-key loader's instance. No
production Paramiko/sshtunnel code was changed.

All bootstrap, package-install, configuration, and temporary-file paths were
kept under repository artifacts; pip used `--no-cache-dir`. The full CLI-helper
test was not run in this focused emulator environment. Native encrypted-key
and complete CLI package validation remain blocked by the production ARM64
cryptography wheel and its associated version constraints.
