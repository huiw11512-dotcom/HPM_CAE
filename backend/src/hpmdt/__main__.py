"""Temporary Studio entry point for the reboot baseline."""
from __future__ import annotations

import argparse

from hpmdt import __version__


def main() -> None:
    parser = argparse.ArgumentParser(description="HPM-DT Studio")
    parser.add_argument("--version", action="store_true", help="显示版本")
    args = parser.parse_args()
    if args.version:
        print(f"HPM-DT Studio {__version__}")
        return
    print("HPM-DT Studio reboot baseline. Domain implementation starts in Commit 2.")


if __name__ == "__main__":
    main()
