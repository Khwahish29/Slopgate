from __future__ import annotations

import argparse
import json

from .core import analyze_report


def main() -> None:
    parser = argparse.ArgumentParser(description="SlopGate triage CLI")
    parser.add_argument("--report", required=True, help="Text of the vulnerability report to evaluate")
    parser.add_argument("--repo-root", default=".", help="Path to the repository checkout")
    parser.add_argument("--ref", default="HEAD", help="Version or ref the report claims")
    args = parser.parse_args()

    result = analyze_report(args.report, args.repo_root, args.ref)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
