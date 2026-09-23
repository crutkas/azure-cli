# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib.util
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("verify_runtime", SCRIPTS / "verify_runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
REQUIREMENTS_SPEC = importlib.util.spec_from_file_location(
    "prepare_arm64_requirements", SCRIPTS / "prepare_arm64_requirements.py")
requirements = importlib.util.module_from_spec(REQUIREMENTS_SPEC)
REQUIREMENTS_SPEC.loader.exec_module(requirements)


def write_pe(path, machine):
    header = bytearray(64)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 60, 64)
    path.write_bytes(header + b"PE\0\0" + struct.pack("<H", machine))


class RuntimeTests(unittest.TestCase):
    def test_all_machine_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "python.exe"
            for arch, machine in runtime.MACHINE_TYPES.items():
                with self.subTest(arch=arch):
                    write_pe(path, machine)
                    self.assertEqual(runtime.pe_machine(path), machine)
                    with patch.object(runtime.sys, "executable", str(path)):
                        self.assertEqual(runtime.verify(directory, arch, True), 1)

    def test_mixed_architecture_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "python.exe"
            write_pe(path, runtime.MACHINE_TYPES["arm64"])
            write_pe(Path(directory) / "dependency.pyd", runtime.MACHINE_TYPES["x64"])
            with patch.object(runtime.sys, "executable", str(path)):
                with self.assertRaisesRegex(ValueError, "dependency.pyd.*expected arm64"):
                    runtime.verify(directory, "arm64", True)

    def test_wrong_interpreter_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "packaged interpreter"):
                runtime.verify(directory, "arm64")

    def test_pip_templates_have_their_declared_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "python.exe"
            write_pe(path, runtime.MACHINE_TYPES["arm64"])
            templates = root / "Lib" / "site-packages" / "pip" / "_vendor" / "distlib"
            templates.mkdir(parents=True)
            for name, machine in runtime.PIP_LAUNCHERS.items():
                write_pe(templates / name, machine)
            with patch.object(runtime.sys, "executable", str(path)):
                self.assertEqual(runtime.verify(root, "arm64", True), 7)
                write_pe(templates / "unexpected.exe", runtime.MACHINE_TYPES["x64"])
                with self.assertRaisesRegex(ValueError, "unexpected.exe"):
                    runtime.verify(root, "arm64", True)

    def test_pip_template_name_does_not_hide_wrong_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "python.exe"
            write_pe(path, runtime.MACHINE_TYPES["arm64"])
            templates = root / "Lib" / "site-packages" / "pip" / "_vendor" / "distlib"
            templates.mkdir(parents=True)
            write_pe(templates / "t32.exe", runtime.MACHINE_TYPES["x64"])
            with patch.object(runtime.sys, "executable", str(path)):
                with self.assertRaisesRegex(ValueError, "t32.exe"):
                    runtime.verify(root, "arm64", True)

    def test_setuptools_templates_have_their_declared_architecture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "python.exe"
            write_pe(path, runtime.MACHINE_TYPES["arm64"])
            templates = root / "Lib" / "site-packages" / "setuptools"
            templates.mkdir(parents=True)
            for name, machine in runtime.SETUPTOOLS_LAUNCHERS.items():
                write_pe(templates / name, machine)
            with patch.object(runtime.sys, "executable", str(path)):
                self.assertEqual(runtime.verify(root, "arm64", True), 9)
                write_pe(templates / "cli-arm64.exe", runtime.MACHINE_TYPES["x64"])
                with self.assertRaisesRegex(ValueError, "cli-arm64.exe"):
                    runtime.verify(root, "arm64", True)

    def test_upstream_companion_requires_exact_path_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "python.exe"
            companion = root / "vcruntime140_1.dll"
            write_pe(executable, runtime.MACHINE_TYPES["arm64"])
            write_pe(companion, runtime.MACHINE_TYPES["x64"])
            with patch.object(runtime.sys, "executable", str(executable)):
                with self.assertRaisesRegex(ValueError, "vcruntime140_1.dll"):
                    runtime.verify(root, "arm64", True)
                digest = hashlib.sha256(companion.read_bytes()).hexdigest()
                with patch.object(runtime, "ARM64EC_COMPANION_SHA256", digest):
                    self.assertEqual(runtime.verify(root, "arm64", True), 2)
                    companion.rename(root / "other.dll")
                    with self.assertRaisesRegex(ValueError, "other.dll"):
                        runtime.verify(root, "arm64", True)

    def test_corrupt_binaries_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.dll"
            for data in (b"", b"MZ", b"MZ" + bytes(62)):
                with self.subTest(data=data):
                    path.write_bytes(data)
                    with self.assertRaises(ValueError):
                        runtime.pe_machine(path)


class RequirementsTests(unittest.TestCase):
    def test_only_reviewed_pins_change(self):
        source = (SCRIPTS.parents[2] / "src" / "azure-cli" / "requirements.py3.windows.txt").read_text()
        actual = requirements.arm64_requirements(source)
        expected = source.replace("bcrypt==3.2.0", "bcrypt==5.0.0").replace("psutil==6.1.0", "psutil==7.2.2")
        self.assertEqual(actual.splitlines(), expected.splitlines())
        self.assertIn("cryptography==48.0.1", actual)
        self.assertIn("bcrypt==3.2.0", source)
        self.assertIn("psutil==6.1.0", source)

    def test_changed_missing_duplicate_or_marked_pins_require_review(self):
        for source in (
                "bcrypt==4.0.0\npsutil==6.1.0",
                "psutil==6.1.0",
                "bcrypt==3.2.0\nbcrypt==3.2.0\npsutil==6.1.0",
                "bcrypt==3.2.0\nbcrypt>=6\npsutil==6.1.0",
                "bcrypt==3.2.0; platform_machine == 'ARM64'\npsutil==6.1.0"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "review the ARM64 dependency policy"):
                        requirements.arm64_requirements(source)


@unittest.skipUnless(os.name == "nt", "Windows batch preflight")
class BuildPreflightTests(unittest.TestCase):
    def run_preflight(self, **settings):
        env = dict(os.environ, CLI_VERSION="0.0.0", ARCH="arm64", TARGET="zip")
        env.update(settings)
        command = f'call "{SCRIPTS / "build.cmd"}" --check'
        if "PROCESSOR_ARCHITECTURE" in settings:
            # cmd initializes architecture variables at startup; override afterward.
            command = ('set "PROCESSOR_ARCHITECTURE=AMD64" && '
                       'set "PROCESSOR_ARCHITEW6432=" && ' + command)
        return subprocess.run(
            f'"{os.environ["COMSPEC"]}" /d /c {command}',
            env=env, text=True, capture_output=True, check=False)

    def test_invalid_architecture(self):
        result = self.run_preflight(ARCH="aarch64")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Please set ARCH to "x86", "x64" or "arm64"', result.stdout)

    def test_existing_runtime_urls(self):
        for arch, python_arch in (("x86", "win32"), ("x64", "amd64")):
            with self.subTest(arch=arch):
                result = self.run_preflight(ARCH=arch)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"embed-{python_arch}.zip", result.stdout)
                self.assertIn("wix310-binaries-mirror.zip", result.stdout)
                self.assertIn("Artifact: Microsoft Azure CLI.zip", result.stdout)
                self.assertNotIn("Cleaning previous build artifacts", result.stdout)

    @unittest.skipUnless(os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() == "ARM64"
                         or os.environ.get("PROCESSOR_ARCHITEW6432", "").upper() == "ARM64",
                         "Native Windows ARM64 host")
    def test_arm64_runtime_and_toolchain_urls(self):
        result = self.run_preflight()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("embed-arm64.zip", result.stdout)
        self.assertIn("wix3141rtm/wix314-binaries.zip", result.stdout)
        self.assertIn("Artifact: Microsoft Azure CLI arm64.zip", result.stdout)

    def test_existing_msi_artifact_names(self):
        for arch in ("x86", "x64"):
            with self.subTest(arch=arch):
                result = self.run_preflight(ARCH=arch, TARGET="msi")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Artifact: Microsoft Azure CLI.msi", result.stdout)

    def test_invalid_target(self):
        result = self.run_preflight(TARGET="other")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Please set TARGET to "msi" or "zip"', result.stdout)

    def test_cross_packaging_is_rejected_before_cleaning(self):
        result = self.run_preflight(PROCESSOR_ARCHITECTURE="AMD64", PROCESSOR_ARCHITEW6432="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a native Windows ARM64 host", result.stdout)
        self.assertNotIn("Cleaning previous build artifacts", result.stdout)


if __name__ == "__main__":
    unittest.main()
