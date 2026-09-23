"""Standalone source-contract tests: python -m unittest discover -s build_scripts/windows/tests."""

import re
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


WINDOWS = Path(__file__).resolve().parents[1]
WIX = {"w": "http://schemas.microsoft.com/wix/2006/wi"}
MSBUILD = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}


def product_for(platform):
    """Resolve only the preprocessor directives used by Product.wxs, without requiring WiX."""
    variables = {"Platform": platform}
    active = True
    branches = []
    output = []

    def expand(text):
        text = text.replace("$(env.CLI_VERSION)", "2.99.0")
        return re.sub(r"\$\(var\.([^)]+)\)", lambda match: variables[match[1]], text)

    for part in re.split(r"(<\?.*?\?>)", (WINDOWS / "Product.wxs").read_text(encoding="utf-8")):
        if not part.startswith("<?") or part.startswith("<?xml"):
            if active:
                output.append(expand(part))
            continue
        directive = part[2:-2].strip()
        command, _, argument = directive.partition(" ")
        if command in ("if", "elseif"):
            if command == "if":
                branches.append([active, False])
            parent, matched = branches[-1]
            # Fail closed if new WiX expression syntax needs a real preprocessor.
            expression = re.fullmatch(r'(.+?)\s*=\s*"([^"]*)"', argument)
            if not expression:
                raise AssertionError(f"Unsupported expression: {argument}")
            active = parent and not matched and expand(expression[1]).strip('" ') == expression[2]
            branches[-1][1] = matched or active
        elif command == "else":
            parent, matched = branches[-1]
            active = parent and not matched
            branches[-1][1] = True
        elif command == "endif":
            active = branches.pop()[0]
        elif active and command == "define":
            name, value = argument.split("=", 1)
            variables[name.strip()] = expand(value.strip().strip('"'))
        elif active and command == "undef":
            del variables[argument]
        elif active and command == "error":
            raise ValueError(expand(argument))
        elif command not in ("define", "undef", "error"):
            raise AssertionError(f"Unsupported directive: {command}")
    assert not branches
    return ET.fromstring("".join(output))


class MsiArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.products = {arch: product_for(arch) for arch in ("x86", "x64", "arm64")}

    def test_package_identity_and_minimum_installer(self):
        codes = set()
        for arch, tree in self.products.items():
            product = tree.find("w:Product", WIX)
            codes.add(uuid.UUID(product.get("UpgradeCode")))
            package = product.find("w:Package", WIX)
            self.assertEqual(package.get("InstallerVersion"), "500" if arch == "arm64" else "200")
            self.assertEqual(package.get("InstallScope"), "perMachine")
            self.assertEqual(package.get("Compressed"), "yes")
        self.assertEqual(len(codes), 3)
        self.assertEqual(self.products["arm64"].find("w:Product", WIX).get("Name"),
                         "Microsoft Azure CLI (ARM64)")

    def test_existing_upgrade_codes_remain_stable(self):
        for arch, expected in (
                ("x86", "dff82af0-3f95-4ac9-8efd-948604fdb028"),
                ("x64", "90762fec-9554-4729-a107-c6a8ea316698"),
                ("arm64", "a26a9a9e-7e9a-4a41-bf5a-54cd57a028f8")):
            self.assertEqual(self.products[arch].find("w:Product", WIX).get("UpgradeCode"), expected)

    def test_component_bitness_and_unique_identities(self):
        identities = []
        for arch, tree in self.products.items():
            components = tree.findall(".//w:Component", WIX)
            self.assertEqual(len(components), 5)
            for component in components:
                self.assertEqual(component.get("Win64"), "no" if arch == "x86" else "yes")
                identities.append(uuid.UUID(component.get("Guid")))
            folder = tree.find(".//w:Directory[@Id='AZURECLIFOLDER']", WIX)
            seed = folder.get("ComponentGuidGenerationSeed")
            if arch == "arm64":
                self.assertEqual(str(uuid.UUID(seed)), "bf2f6ec9-467d-4865-a20f-cfd619e358ec")
            else:
                self.assertIsNone(seed)  # Do not change existing harvested component identities.
            program_files = "ProgramFilesFolder" if arch == "x86" else "ProgramFiles64Folder"
            self.assertIsNotNone(tree.find(f".//w:Directory[@Id='{program_files}']", WIX))
        self.assertEqual(len(identities), len(set(identities)))

    def test_cross_architecture_detection_never_removes_products(self):
        for arch, tree in self.products.items():
            expected = ("x86", "x64") if arch == "arm64" else ("arm64",)
            conditions = tree.findall(".//w:Product/w:Condition", WIX)
            for other in expected:
                code = self.products[other].find("w:Product", WIX).get("UpgradeCode")
                rows = tree.findall(f".//w:Upgrade[@Id='{code}']/w:UpgradeVersion", WIX)
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.get("OnlyDetect"), "yes")
                self.assertEqual(row.get("Minimum"), "0.0.0")
                self.assertEqual(row.get("IncludeMinimum"), "yes")
                self.assertIsNone(row.get("Maximum"))
                self.assertIsNone(row.get("MigrateFeatures"))
                condition = next(item for item in conditions if row.get("Property") in item.text)
                self.assertTrue(condition.text.startswith("Installed OR NOT "))
                self.assertIn("manually", condition.get("Message"))

    def test_same_architecture_upgrade_and_x64_migration_are_preserved(self):
        for arch, tree in self.products.items():
            product = tree.find("w:Product", WIX)
            own = product.find(f"w:Upgrade[@Id='{product.get('UpgradeCode')}']", WIX)
            upgrade, downgrade = list(own)
            self.assertEqual(upgrade.get("Property"), "WIX_UPGRADE_DETECTED")
            self.assertEqual(upgrade.get("IncludeMaximum"), "no")
            self.assertEqual(upgrade.get("MigrateFeatures"), "yes")
            self.assertIsNone(upgrade.get("OnlyDetect"))
            self.assertEqual(downgrade.get("OnlyDetect"), "yes")
            self.assertEqual(product.find(".//w:RemoveExistingProducts", WIX).get("Before"),
                             "InstallInitialize")
            migrations = product.findall(".//w:UpgradeVersion[@Property='WIX_X86_UPGRADE_DETECTED']", WIX)
            self.assertEqual(len(migrations), 1 if arch == "x64" else 0)
            if migrations:
                self.assertEqual(migrations[0].get("IncludeMaximum"), "yes")
                self.assertIsNone(migrations[0].get("OnlyDetect"))

    def test_native_arm64_environment_broadcast(self):
        for arch, tree in self.products.items():
            action = tree.find(".//w:CustomActionRef", WIX)
            self.assertEqual(action.get("Id"), "WixBroadcastEnvironmentChange_A64"
                             if arch == "arm64" else "WixBroadcastEnvironmentChange")

    def test_project_harvest_and_platform_contract(self):
        project = ET.parse(WINDOWS / "azure-cli.wixproj").getroot()
        self.assertEqual(project.find(".//m:InstallerPlatform", MSBUILD).text, "$(Platform)")
        groups = {group.get("Condition", "").strip(): group for group in project.findall("m:PropertyGroup", MSBUILD)}
        for configuration in ("Debug", "Release"):
            group = groups[f"'$(Configuration)|$(Platform)' == '{configuration}|arm64'"]
            self.assertIn("arm64", group.find("m:IntermediateOutputPath", MSBUILD).text)
            self.assertIn("AzureCliSource=$(AzureCliSource)", group.find("m:DefineConstants", MSBUILD).text)
        roots = project.findall(".//m:LocalWixRoot", MSBUILD)
        self.assertEqual([item.text for item in roots], [r"artifacts\wix-arm64-3.14.1", r"artifacts\wix"])
        self.assertIn("'$(Platform)' == 'arm64'", roots[0].get("Condition"))
        names = project.findall(".//m:OutputName", MSBUILD)
        self.assertEqual([item.text for item in names], ["Microsoft Azure CLI", "Microsoft Azure CLI arm64"])
        self.assertEqual(names[1].get("Condition").strip(), "'$(Platform)' == 'arm64'")
        heat = project.find(".//m:HeatDirectory", MSBUILD)
        self.assertEqual(heat.get("AutogenerateGuids"), "true")
        self.assertEqual(heat.get("DirectoryRefId"), "DynamicCliDir")
        self.assertEqual(heat.get("PreprocessorVariable"), "var.AzureCliSource")
        solution = (WINDOWS / "azure-cli.sln").read_text(encoding="utf-8-sig")
        for configuration in ("Debug", "Release"):
            self.assertIn(f"{configuration}|arm64.Build.0 = {configuration}|arm64", solution)

    def test_unsupported_architecture_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Unsupported platform"):
            product_for("riscv64")

    def test_lifecycle_script_safety_contract(self):
        script = (WINDOWS / "scripts" / "test_arm64_msi.ps1").read_text(encoding="utf-8")
        for tree in self.products.values():
            code = tree.find("w:Product", WIX).get("UpgradeCode")
            self.assertIn("{" + code.upper() + "}", script)
        for guard in ("if (-not $DisposableHost)", "::OSArchitecture", "::ProcessArchitecture",
                      "[Security.Principal.WindowsBuiltInRole]::Administrator",
                      "if (@(Get-CliProducts).Count)", "if (-not $ownedCodes.Contains($Package.Code))"):
            self.assertIn(guard, script)
        self.assertIn("$process.ExitCode -eq 3010", script)
        self.assertIn("$process.ExitCode -ne $ExpectedExitCode", script)
        self.assertIn("$ExpectedExitCode -eq 1603", script)
        self.assertIn("-SimpleMatch 'Uninstall the existing'", script)
        self.assertIn("'/norestart'", script)
        self.assertIn('& $python -I $runtimeVerifier --root $directory --arch arm64 --all', script)
        self.assertNotIn("Win32_Product", script)


if __name__ == "__main__":
    unittest.main()
