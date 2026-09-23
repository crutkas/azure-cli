# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""Reject mislabeled Windows packages, including emulated native dependencies."""

import argparse
import hashlib
from pathlib import Path
import struct
import sys


MACHINE_TYPES = {"x86": 0x014C, "x64": 0x8664, "arm64": 0xAA64}
# These are inert templates used by pip to create entry-point launchers, not
# imported native dependencies. pip intentionally ships all three architectures.
PIP_LAUNCHERS = {
    f"{kind}{suffix}.exe": MACHINE_TYPES[arch]
    for kind in ("t", "w")
    for suffix, arch in (("32", "x86"), ("64", "x64"), ("64-arm", "arm64"))
}
SETUPTOOLS_LAUNCHERS = {
    f"{kind}{suffix}.exe": MACHINE_TYPES[arch]
    for kind in ("cli", "gui")
    for suffix, arch in (("", "x86"), ("-32", "x86"), ("-64", "x64"), ("-arm64", "arm64"))
}
# CPython's official 3.14.7 ARM64 archive also ships this ARM64EC companion.
# It is not loadable or required by classic ARM64 Python. Do not generalize this
# exception to other CRTs or dependencies: see ../runtime-arm64.md.
ARM64EC_COMPANION_SHA256 = "60c70e34e2e156f8bd214b92c2125c252e17d86ac8a25799ea1a4ecabde1d97c"


def pe_machine(path):
    with Path(path).open("rb") as binary:
        header = binary.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError(f"{path}: missing DOS header")
        binary.seek(struct.unpack_from("<I", header, 60)[0])
        signature = binary.read(6)
        if len(signature) != 6 or signature[:4] != b"PE\0\0":
            raise ValueError(f"{path}: missing PE header")
        return struct.unpack_from("<H", signature, 4)[0]


def verify(root, arch, all_binaries=False):
    root = Path(root).resolve()
    executable = root / "python.exe"
    if Path(sys.executable).resolve() != executable:
        raise ValueError(f"Run this check using the packaged interpreter: {executable}")
    if not executable.is_file():
        raise ValueError(f"Packaged interpreter is missing: {executable}")
    expected = MACHINE_TYPES[arch]
    paths = [executable]
    if all_binaries:
        paths = sorted(path for path in root.rglob("*")
                       if path.is_file() and path.suffix.lower() in {".exe", ".dll", ".pyd"})
    templates = 0
    companions = 0
    for path in paths:
        required = expected
        if path.parent == root / "Lib" / "site-packages" / "pip" / "_vendor" / "distlib":
            if path.name in PIP_LAUNCHERS:
                required = PIP_LAUNCHERS[path.name]
                templates += 1
        elif path.parent == root / "Lib" / "site-packages" / "setuptools":
            if path.name in SETUPTOOLS_LAUNCHERS:
                required = SETUPTOOLS_LAUNCHERS[path.name]
                templates += 1
        actual = pe_machine(path)
        if (arch == "arm64" and path == root / "vcruntime140_1.dll"
                and actual == MACHINE_TYPES["x64"]
                and hashlib.sha256(path.read_bytes()).hexdigest() == ARM64EC_COMPANION_SHA256):
            companions += 1
            print(f"Recognized upstream ARM64EC companion (not native code): {path}")
            continue
        if actual != required:
            raise ValueError(f"{path}: PE machine 0x{actual:04x}, expected {arch} "
                             f"or declared launcher template machine (0x{required:04x})")
    print(f"Verified {len(paths) - templates - companions} {arch} PE binaries, {templates} launcher "
          f"templates, and {companions} pinned upstream companions using {sys.executable}")
    return len(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--arch", required=True, choices=MACHINE_TYPES)
    parser.add_argument("--all", action="store_true", dest="all_binaries")
    args = parser.parse_args()
    try:
        verify(args.root, args.arch, args.all_binaries)
    except (OSError, ValueError) as ex:
        parser.exit(1, f"Architecture verification failed: {ex}\n")


if __name__ == "__main__":
    main()
