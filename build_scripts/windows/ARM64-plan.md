# Native Windows ARM64 delivery plan

Baseline: `6cd38278b625b845433864dd0454c0d362350bf2`.

The first deliverable is a native CPython 3.14 Windows ARM64 ZIP. MSI support
follows, without changing existing x86/x64 artifacts. This is implementation
work, not an announcement of supported production ARM64 distributions.

1. Audit the complete Windows dependency set against CPython 3.14 ARM64 wheel
   tags. Preserve x86/x64 pins where ARM64 needs newer native dependencies.
   Never downgrade cryptography or pin an unpublished release to obtain wheels.
2. Add native runtime selection, architecture-separated caches, explicit
   host/target validation, fail-fast native dependency installation, and a
   distinctly named ARM64 ZIP. Validate every shipped PE binary.
3. Exercise actual process queries, bcrypt KDF, and encrypted OpenSSH RSA and
   Ed25519 keys with correct, wrong, and long passphrases. Run these against the
   packaged runtime, not only development Python or mocked APIs.
4. Add an ARM64-capable, separately versioned WiX toolchain and ARM64 installer
   identities. Default to refusing cross-architecture MSI replacement rather
   than silently uninstalling another architecture. Require release-owner
   approval of migration policy and disposable-machine lifecycle validation.
5. Add opt-in native CI with an explicitly supplied, provisioned ARM64 pool.
   Do not invent an internal pool or connect unvalidated packages to production
   signing/publication. Fail enabled validation on unavailable dependencies.
6. Document commands, evidence, limitations, and release prerequisites. Separate
   implementation, native validation, and production readiness in the handoff.

## Release gates

- Supported, official wheels for the complete pinned dependency set, including
  cryptography and MSAL broker dependencies.
- Native ZIP startup, local commands, extension installation, native dependency
  tests, and binary architecture checks.
- MSI clean install, repair, same-architecture upgrade, downgrade rejection,
  uninstall, and cross-architecture rejection on disposable hosts.
- Existing x86/x64 package build and installer regression runs.
- Approved internal Windows ARM64 agent, signing/SBOM/release integration, and
  authenticated broker/browser/service-principal tests with explicit permission.
- Distribution documentation and package-manager manifests owned outside this
  repository, only after production approval.

No credentials, cloud resources, package publication, upstream push, or upstream
PR are part of this work. The user authorized committing this foundation,
pushing its branch to the `crutkas/azure-cli` fork, and a draft review-preview PR
contained entirely within that fork. An existing review base must not be
overwritten or used to introduce unrelated changes without approval. An experimental
cryptography build must not enter the normal production resolver; any future
exception needs explicit opt-in, immutable source/artifact provenance, hashes,
and a separate non-production artifact.

## Implementation handoff

Runtime/ZIP routing, native-binary verification, explicitly generated ARM64
dependency pins, installer definitions, regression tests, and manual native CI
are implemented. Shared x86/x64 dependency pins and artifact names are preserved.
ARM64 MSI/ZIP self-upgrade is deliberately refused until production endpoints
are approved; that guard is not upgrade support.

See [README.md](README.md) for commands and production prerequisites,
[dependency-audit.md](dependency-audit.md) for the 143-distribution audit and
real dependency results, [runtime-arm64.md](runtime-arm64.md) for native runtime
provenance and the incidental ARM64EC companion, and
[msi-arm64.md](msi-arm64.md) for fixture evidence and unexecuted lifecycle gates.
Passing installer fixture compilation or independent bcrypt/psutil tests does
not establish a complete working CLI ZIP/MSI. Cryptography wheel availability
and coordinated MSAL/pyOpenSSL constraints remain production blockers.
Specifically, MSAL 1.39.0 (also the latest stable release) excludes cryptography
51; pyOpenSSL 26.2.0 excludes 49 and newer, and even released pyOpenSSL 26.4.0
excludes 51. Cryptography 48.x through the latest 50.0.1 have no Windows ARM64
wheels. A cryptography 51 release alone cannot satisfy this plan's dependency
gate; compatible supported MSAL/pyOpenSSL releases and normal resolver/native
regression results are required too.

## Actionable remaining-items checklist

**There is no full working native ARM64 Azure CLI package yet.** The verified
results are 31 packaging/installer/upgrade-policy tests, three real native
bcrypt/psutil tests, and a native dependency binary scan. Encrypted
RSA/Ed25519/OpenSSH/Paramiko tests passed under **emulated x64**, with both
bcrypt 3.2.0 and 5.0.0; those are not native ARM64 encryption results. MSI
fixture builds and table inspection are not full CLI MSI builds or lifecycle
validation. The 143-distribution inventories are not complete transitive
resolver validation.

### Upstream dependency releases

- [ ] **cryptography:** obtain an official supported CPython 3.14 `win_arm64`
  wheel. None exists for published 48.x-50.x; 51 is not yet published as of
  2026-09-23. Do not downgrade, float on Git main, or substitute a development
  artifact in the production build.
- [ ] **MSAL:** obtain a tested, published release accepting the chosen
  cryptography version. Current/latest MSAL 1.39.0 requires `>=2.5,<51`.
- [ ] **pyOpenSSL:** obtain a tested, published release accepting that same
  version. Pinned 26.2.0 requires `>=46,<49`; latest 26.4.0 requires `>=49,<51`.
- [ ] **Azure CLI dependency integration:** select compatible released pins,
  resolve the entire candidate normally, and pass `pip check` plus regression
  tests without overriding constraints. Revalidate native broker dependencies.

MSAL and pyOpenSSL do **not currently require architectural ports based on
this evidence**: their inspected wheels are `msal-1.39.0-py3-none-any.whl` and
`pyopenssl-26.4.0-py3-none-any.whl`. Ordinary upstream API-compatibility changes,
tested dependency-bound updates, and published releases may suffice. Universal
wheel tags do not prove compatibility with cryptography 51, so upstream tests
must establish that before relaxing bounds. MSAL's separate native
`pymsalruntime` broker already has an importable CPython 3.14 ARM64 wheel in
the audited version. No MSAL or pyOpenSSL fork is needed or created for this
handoff; a fork is not a substitute for supported upstream compatibility.

### Downstream validation and release work

- [ ] **Build prerequisites:** provision 7-Zip and MSBuild on the approved
  builder, then produce complete ARM64 ZIP and MSI candidates. No complete
  package was produced on this shared development machine.
- [ ] **Native functionality:** run encrypted-key and CLI-helper tests,
  extracted ZIP startup/local commands/extensions, `az self-test`, and binary
  checks on native Windows ARM64. Validate optional downloaded helpers.
- [ ] **Existing architectures:** build and test complete x86/x64 packages,
  including emulated interpreters, without changing their dependency selection.
- [ ] **MSI lifecycle and policy:** obtain authorization for disposable-host
  clean install, repair, upgrade, downgrade rejection, uninstall, and
  cross-architecture rejection. Approve migration/coexistence policy and account
  for historical installers without reverse guards. Validate the x86
  EULA-print helper under Windows ARM64 emulation; it is not a native helper.
- [ ] **Authentication:** with explicit credentials/scenario authorization,
  validate broker, browser, and service-principal authentication.
- [ ] **Infrastructure and signing:** provision/approve a real ARM64 CI pool;
  wire SBOM, signing, artifact retention, and release qualification.
- [ ] **Upgrade URLs:** publish approved signed ARM64 artifacts and
  architecture-specific MSI/ZIP URLs plus version metadata. Replace the interim
  `az upgrade` refusal only after native end-to-end upgrade validation.
- [ ] **Publication:** obtain release approval, enable package publication, and
  update external install documentation/package-manager manifests. A source
  branch pushed to a fork is not an ARM64 product release.
