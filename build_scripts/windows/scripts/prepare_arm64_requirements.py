# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""Select reviewed ARM64 pins without host-architecture environment markers."""

import argparse
from pathlib import Path
import re
import sysconfig


REPLACEMENTS = {"bcrypt==3.2.0": "bcrypt==5.0.0", "psutil==6.1.0": "psutil==7.2.2"}


def arm64_requirements(source):
    lines = source.splitlines()
    for original in REPLACEMENTS:
        package = original.split("==", 1)[0]
        matching = [line for line in lines
                    if re.match(rf"^\s*{package}(?=[\s\[<>=!~;@]|$)", line, re.IGNORECASE)]
        if matching != [original]:
            raise ValueError(f"Expected exactly one unmodified {original} pin; "
                             "review the ARM64 dependency policy after changing Windows requirements.")
    return "\n".join(REPLACEMENTS.get(line, line) for line in lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if sysconfig.get_platform() != "win-arm64":
        parser.exit(1, "ARM64 requirements must be selected by the native ARM64 interpreter, not host markers.\n")
    if args.source.resolve() == args.output.resolve():
        parser.exit(1, "The generated requirements must not overwrite the shared Windows requirements.\n")
    try:
        content = arm64_requirements(args.source.read_text(encoding="utf-8"))
        args.output.write_text(content, encoding="utf-8")
    except (OSError, ValueError) as ex:
        parser.exit(1, f"ARM64 requirements generation failed: {ex}\n")
    print(f"Generated reviewed ARM64 requirements: {args.output}")


if __name__ == "__main__":
    main()
