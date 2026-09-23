# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline upgrade regression tests; no CLI dependencies or installed CLI are required.

Load the actual util handler with stand-ins for its dependency interfaces. All upgrade
side effects are mocked, including subprocess reload, so these tests never run an upgrade.
"""

import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]
CUSTOM = ROOT / "src/azure-cli/azure/cli/command_modules/util/custom.py"


class UnsupportedUpgradeError(Exception):
    def __init__(self, message, recommendation=None):
        super().__init__(message)
        self.recommendation = recommendation


def module(name, **attributes):
    result = ModuleType(name)
    result.__dict__.update(attributes)
    return result


class UpgradeArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.latest = Mock(return_value="2.1.0")
        self.extensions = Mock(return_value=[])
        self.remove = Mock()
        self.prompt = Mock(return_value=True)
        self.logger = Mock()
        modules = {
            "knack": module("knack"),
            "knack.log": module("knack.log", get_logger=Mock(return_value=self.logger)),
            "knack.util": module("knack.util", CLIError=Exception),
            "knack.prompting": module("knack.prompting", prompt_y_n=self.prompt, NoTTYException=RuntimeError),
            "azure": module("azure"),
            "azure.cli": module("azure.cli"),
            "azure.cli.core": module("azure.cli.core", telemetry=Mock(), __version__="2.0.0"),
            "azure.cli.core._environment": module("azure.cli.core._environment", _ENV_AZ_INSTALLER="AZ_INSTALLER"),
            "azure.cli.core.azclierror": module(
                "azure.cli.core.azclierror", UnclassifiedUserFault=UnsupportedUpgradeError),
            "azure.cli.core.extension": module(
                "azure.cli.core.extension", get_extensions=self.extensions, WheelExtension=object),
            "azure.cli.core.util": module(
                "azure.cli.core.util", get_latest_version_from_ame_storage=self.latest,
                rmtree_with_retry=self.remove),
            "packaging": module("packaging"),
            "packaging.version": module(
                "packaging.version", parse=lambda value: tuple(int(part) for part in value.split("."))),
        }
        self.enterContext(patch.dict(sys.modules, modules))
        spec = importlib.util.spec_from_file_location("upgrade_custom_under_test", CUSTOM)
        self.custom = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.custom)
        self.enterContext(patch.dict(os.environ, {"AZ_INSTALLER": "MSI"}))
        self.target = self.enterContext(patch("sysconfig.get_platform", return_value="win-arm64"))
        self.enterContext(patch("platform.system", return_value="Windows"))
        self.enterContext(patch("platform.machine", return_value="ARM64"))
        self.bitness = self.enterContext(patch("platform.architecture", return_value=("64bit", "")))
        self.temp = self.enterContext(patch("tempfile.gettempdir", return_value="mock-temp"))
        self.mkdir = self.enterContext(patch("os.makedirs"))
        self.download = self.enterContext(patch.object(
            self.custom, "_download_from_url", return_value="mock-installer.msi"))
        self.popen = self.enterContext(patch("subprocess.Popen"))
        self.call = self.enterContext(patch("subprocess.call", return_value=0))
        self.output = self.enterContext(patch(
            "subprocess.check_output", return_value=b'{"azure-cli-core": "2.1.0"}'))
        # upgrade_version reloads subprocess after upgrade; do not let that unpatch side effects.
        self.enterContext(patch("importlib.reload", side_effect=lambda value: value))

    def assert_no_upgrade_side_effects(self):
        for effect in (self.latest, self.extensions, self.prompt, self.temp, self.mkdir,
                       self.remove, self.download, self.popen, self.call, self.output):
            effect.assert_not_called()

    def test_util_native_arm64_msi_zip_fail_before_version_lookup_or_prompt(self):
        for installer in ("MSI", "ZIP", "msi", "zip"):
            for yes in (False, True):
                for update_all in (False, True):
                    with self.subTest(installer=installer, yes=yes, update_all=update_all):
                        with patch.dict(os.environ, {"AZ_INSTALLER": installer}):
                            with self.assertRaisesRegex(
                                    UnsupportedUpgradeError, "native Windows ARM64 MSI/ZIP") as error:
                                self.custom.upgrade_version(None, yes=yes, update_all=update_all)
                        self.assertIn("Keep the current installation", error.exception.recommendation)
                        self.assert_no_upgrade_side_effects()
                        self.bitness.assert_not_called()

    def test_util_native_arm64_direct_msi_call_is_protected(self):
        with self.assertRaisesRegex(UnsupportedUpgradeError, "production ARM64 upgrade package"):
            self.custom._upgrade_on_windows()
        self.assert_no_upgrade_side_effects()
        self.bitness.assert_not_called()

    def test_util_emulated_x86_x64_msi_urls_are_unchanged(self):
        for target, bitness, url in (
                ("win32", "32bit", "https://aka.ms/installazurecliwindows"),
                ("win-amd64", "64bit", "https://aka.ms/installazurecliwindowsx64")):
            with self.subTest(target=target):
                self.target.return_value = target
                self.bitness.return_value = (bitness, "")
                with self.assertRaises(SystemExit) as exit_result:
                    self.custom.upgrade_version(None, yes=True)
                self.assertEqual(exit_result.exception.code, 0)
                self.download.assert_called_with(url, os.path.join("mock-temp", "azure-cli-msi"))
                self.popen.assert_called_with(["msiexec.exe", "/i", "mock-installer.msi"])

    def test_util_emulated_x86_x64_zip_url_is_unchanged(self):
        for target in ("win32", "win-amd64"):
            with self.subTest(target=target):
                self.target.return_value = target
                with patch.dict(os.environ, {"AZ_INSTALLER": "ZIP"}):
                    self.custom.upgrade_version(None, yes=True)
                self.logger.warning.assert_any_call(
                    "Please download the latest ZIP from %s, delete the old installation folder and extract the "
                    "new version to the same location", "https://aka.ms/installazurecliwindowszipx64")
                self.download.assert_not_called()
                self.remove.assert_not_called()
                self.popen.assert_not_called()

    def test_util_native_arm64_pip_flow_is_unchanged(self):
        with patch.dict(os.environ, {"AZ_INSTALLER": "PIP"}):
            self.custom.upgrade_version(None, yes=True)
        self.target.assert_not_called()
        self.call.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "--upgrade", "azure-cli", "-vv",
             "--disable-pip-version-check", "--no-cache-dir"], shell=True)
        self.download.assert_not_called()

    def test_util_non_windows_upgrade_flow_is_unchanged(self):
        self.target.return_value = "linux-aarch64"
        with patch("platform.system", return_value="Linux"):
            with patch.dict(os.environ, {"AZ_INSTALLER": "HOMEBREW"}):
                self.custom.upgrade_version(None, yes=True)
        self.target.assert_not_called()
        self.assertEqual(self.call.call_count, 2)
        self.call.assert_any_call(["brew", "update"])
        self.call.assert_any_call(["brew", "upgrade", "azure-cli"])
        self.download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
