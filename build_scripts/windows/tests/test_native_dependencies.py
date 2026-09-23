# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline regression tests run by the packaged Python, without mocks or pytest.

Run from a checkout with a writable build_scripts\\windows\\artifacts directory:
    <package>\\python.exe -I <repo>\\build_scripts\\windows\\tests\\test_native_dependencies.py -v

These are behavioral checks, not evidence of native ARM64 execution. The packaging
tests must separately verify the interpreter and loaded native modules' architecture.
"""

import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import time
import unittest
import uuid

import bcrypt
import psutil


class BcryptTests(unittest.TestCase):
    def test_openssh_kdf_known_vector(self):
        # bcrypt_pbkdf's published password/salt, rounds=4, 32-byte test vector.
        actual = bcrypt.kdf(
            password=b"password", salt=b"salt", desired_key_bytes=32,
            rounds=4, ignore_few_rounds=True,
        )
        self.assertEqual(
            actual.hex(),
            "5bbf0cc293587f1c3635555c27796598d47e579071bf427e9d8fbe842aba34d9",
        )

    def test_openssh_kdf_uses_password_bytes_after_72(self):
        prefix = b"p" * 72
        kwargs = {"salt": b"native-dependency-test", "desired_key_bytes": 32,
                  "rounds": 4, "ignore_few_rounds": True}
        key = bcrypt.kdf(password=prefix + b"correct suffix", **kwargs)
        self.assertEqual(key, bcrypt.kdf(password=prefix + b"correct suffix", **kwargs))
        self.assertNotEqual(key, bcrypt.kdf(password=prefix + b"wrong suffix", **kwargs))
        self.assertNotEqual(key, bcrypt.kdf(password=prefix, **kwargs))


class OpenSSHTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
        import paramiko

        cls.serialization = serialization
        cls.paramiko = paramiko
        cls.keys = {
            "rsa": rsa.generate_private_key(public_exponent=65537, key_size=2048),
            "ed25519": ed25519.Ed25519PrivateKey.generate(),
        }

    @classmethod
    def public_bytes(cls, key):
        return key.public_key().public_bytes(
            cls.serialization.Encoding.OpenSSH, cls.serialization.PublicFormat.OpenSSH,
        )

    @classmethod
    def encrypted_bytes(cls, key, password):
        return key.private_bytes(
            cls.serialization.Encoding.PEM, cls.serialization.PrivateFormat.OpenSSH,
            cls.serialization.BestAvailableEncryption(password),
        )

    def test_cryptography_encrypted_keys(self):
        for kind, key in self.keys.items():
            for password in (b"correct passphrase", b"p" * 72 + b"correct suffix"):
                with self.subTest(kind=kind, password_length=len(password)):
                    encrypted = self.encrypted_bytes(key, password)
                    self.assertIn(b"BEGIN OPENSSH PRIVATE KEY", encrypted)
                    loaded = self.serialization.load_ssh_private_key(encrypted, password)
                    self.assertEqual(self.public_bytes(loaded), self.public_bytes(key))
                    wrong_passwords = [b"wrong passphrase", password[:-1] + b"!"]
                    if len(password) > 72:
                        wrong_passwords.append(password[:72])
                    for wrong in wrong_passwords:
                        with self.assertRaises(ValueError):
                            self.serialization.load_ssh_private_key(encrypted, wrong)
                    with self.assertRaises((TypeError, ValueError)):
                        self.serialization.load_ssh_private_key(encrypted, None)

    def test_paramiko_encrypted_keys(self):
        classes = {"rsa": self.paramiko.RSAKey, "ed25519": self.paramiko.Ed25519Key}
        for kind, key in self.keys.items():
            for password in (b"correct passphrase", b"p" * 72 + b"correct suffix"):
                with self.subTest(kind=kind, password_length=len(password)):
                    encrypted = self.encrypted_bytes(key, password).decode("ascii")
                    loaded = classes[kind].from_private_key(
                        io.StringIO(encrypted), password=password.decode("ascii"),
                    )
                    self.assertTrue(loaded.can_sign())
                    self.assertEqual(
                        "{} {}".format(loaded.get_name(), loaded.get_base64()).encode("ascii"),
                        self.public_bytes(key),
                    )
                    payload = b"Azure CLI native dependency regression"
                    # Paramiko 5 requires RSA SHA-2, and Ed25519 verification
                    # needs a public-key instance rather than a private-key loader.
                    signature = loaded.sign_ssh_data(
                        payload, algorithm="rsa-sha2-512" if kind == "rsa" else None,
                    )
                    verifier = classes[kind](data=loaded.asbytes())
                    self.assertTrue(verifier.verify_ssh_sig(
                        payload, self.paramiko.Message(signature.asbytes()),
                    ))
                    wrong_passwords = [b"wrong passphrase", password[:-1] + b"!"]
                    if len(password) > 72:
                        wrong_passwords.append(password[:72])
                    for wrong in wrong_passwords:
                        with self.assertRaises((self.paramiko.SSHException, ValueError)):
                            classes[kind].from_private_key(
                                io.StringIO(encrypted), password=wrong.decode("ascii"),
                            )
                    with self.assertRaises(self.paramiko.PasswordRequiredException):
                        classes[kind].from_private_key(io.StringIO(encrypted))


class ProcessTests(unittest.TestCase):
    def test_current_process_and_parent(self):
        before = time.time()
        process = psutil.Process(os.getpid())
        self.assertEqual(process.pid, os.getpid())
        self.assertTrue(process.is_running())
        self.assertEqual(process.name().lower(), Path(sys.executable).name.lower())
        self.assertGreater(process.create_time(), 0)
        self.assertLessEqual(process.create_time(), before)
        parent = process.parent()
        self.assertIsNotNone(parent)
        self.assertEqual(parent.pid, os.getppid())
        self.assertEqual(parent.pid, process.ppid())
        self.assertTrue(parent.name())
        self.assertLessEqual(parent.create_time(), process.create_time())

    def test_cli_shell_and_telemetry_process_helpers(self):
        # Keep all child-process state inside the checkout, never the user's
        # profile or the system temporary directory.
        config_dir = (Path(__file__).resolve().parents[1] / "artifacts" /
                      ("native-dependency-config-" + uuid.uuid4().hex))
        config_dir.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, config_dir)
        environment = os.environ.copy()
        environment["AZURE_CONFIG_DIR"] = str(config_dir)
        environment["AZURE_EXTENSION_DIR"] = str(config_dir / "cliextensions")
        environment["AZURE_CORE_COLLECT_TELEMETRY"] = "no"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["TEMP"] = str(config_dir)
        environment["TMP"] = str(config_dir)
        parent = psutil.Process()
        # Force the real telemetry helper to identify this process as the session
        # boundary, rather than depending on the test runner's older ancestors.
        time.sleep(max(0, 1.2 - (time.time() - parent.create_time())))
        script = textwrap.dedent("""
            import hashlib
            import os
            import psutil
            from azure.cli.core import get_default_cli, telemetry
            from azure.cli.core.util import _get_parent_proc_name, get_parent_proc_name

            process = psutil.Process()
            parent = process.parent()
            assert parent is not None
            assert parent.pid == int(os.environ["NATIVE_TEST_PARENT_PID"])
            assert process.create_time() - parent.create_time() > 1

            shell_parent = parent
            if shell_parent.name().lower() == "python.exe":
                shell_parent = shell_parent.parent()
            assert shell_parent is not None
            expected_shell = shell_parent.name()
            grandparent = shell_parent.parent()
            if grandparent and grandparent.name().lower() in ("powershell.exe", "pwsh.exe"):
                expected_shell = grandparent.name()
            assert _get_parent_proc_name() == expected_shell
            assert get_parent_proc_name() == expected_shell
            assert get_parent_proc_name() == expected_shell

            telemetry.set_application(get_default_cli(), "_ARGCOMPLETE")
            installation_id = telemetry._get_installation_id()
            assert installation_id
            content = "{}{}{}".format(installation_id, parent.create_time(), parent.pid)
            expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
            actual = telemetry._get_session_id()
            assert actual == expected, (actual, expected)
            assert telemetry._get_session_id() == actual
            print("CLI process helpers passed")
        """)
        environment["NATIVE_TEST_PARENT_PID"] = str(parent.pid)
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script], env=environment,
            capture_output=True, text=True, timeout=90, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CLI process helpers passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
