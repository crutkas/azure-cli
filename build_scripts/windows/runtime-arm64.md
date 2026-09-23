# CPython ARM64 runtime validation

Evidence collected on native Windows ARM64, 2026-09-23. This is independent of
the missing cryptography wheel and does not establish full CLI package support.

## Official artifact and actual execution

- URL: https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-arm64.zip
- Archive SHA-256:
  `f6773983c8959d4281e48c4540cb0bdd23e42391e4e951ce17e7ceb52658f21c`
- Extracted interpreter:
  `build_scripts\windows\artifacts\validation-python\python.exe`
- Actual version: `3.14.7 (tags/v3.14.7:823f032, Aug 5 2026, 11:30:42)
  [MSC v.1944 64 bit (ARM64)]`; `platform.machine()` reports `ARM64`.
- Real imports of `ctypes`, `ssl`, `sqlite3`, `lzma`, `bz2`, `socket`, `hashlib`,
  `decimal`, and `uuid` succeeded in that interpreter.

## Incidental ARM64EC companion, not a native runtime failure

The **original ZIP member**, not a dependency-installed replacement, contains
`vcruntime140_1.dll`, file version `14.51.36247.0`, SHA-256
`60c70e34e2e156f8bd214b92c2125c252e17d86ac8a25799ea1a4ecabde1d97c`.
Its PE machine field is `0x8664`, but that field alone does **not** identify
ordinary x64 code. The file has CHPE metadata (VA `0x18000a2e8`) and its debug
record names `arm64ret\bin\arm64ec\vcruntime140_1.arm64.pdb`.
Its dynamic relocation table VA and offset/section are zero. The evidence
identifies an ARM64EC companion, not a classic ARM64 or loadable ARM64X image.

Explicitly calling `ctypes.WinDLL` on the absolute path of that file from the
native interpreter fails with `OSError: [WinError 193] %1 is not a valid Win32
application`. This deliberate load of an incompatible companion is **not**
evidence that Python needs or normally loads it. After the successful native
stdlib imports above, `GetModuleHandleW("vcruntime140_1.dll")` returned null,
while `GetModuleHandleW("vcruntime140.dll")` returned a loaded module.
`GetModuleFileNameW` resolved that loaded CRT to the extracted runtime's own
`validation-python\VCRUNTIME140.dll`, not a system-installed replacement.

Upstream [python/cpython#109669](https://github.com/python/cpython/issues/109669)
documents the same ARM64EC companion packaging and classic-ARM64 loading
distinction. It was closed as not planned/stale; a maintainer noted that a
different local build had ARM64X support. That comment is not proof that this
exact release DLL is ARM64X. CPython `PC/layout/main.py` packages all
`vcruntime*.dll` files from its build; `PCbuild/pyproject.props` obtains those
files from the platform's Visual C++ redistributable directory.

## Package policy

Keep the official runtime intact; do not delete or replace CRTs, install a
system runtime, or downgrade Python based on this incidental file.
`verify_runtime.py` recognizes **only this exact hash at the runtime root**
as an upstream ARM64EC companion and reports it separately from native code.
Any changed hash, another location/name, or wrong-architecture dependency
still fails. pip's and setuptools' inert cross-architecture entry-point
templates likewise have an explicit, limited policy.

Native dependency tests and extracted-package smoke tests remain mandatory:
if a dependency actually attempts to load an incompatible CRT, its failure
must not be suppressed. Successful independent native tests must be reported
separately from the currently blocked full cryptography/CLI package tests.
