"""Move pre-platform x2doc output directories under ``output/x``."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

Result = tuple[str, Path, Path]


def migrate_output(root: Path, *, apply: bool = False) -> list[Result]:
    results: list[Result] = []
    if not root.exists():
        return results
    platform_names = {"x", "wechat"}
    for source in sorted(item for item in root.iterdir() if item.is_dir()):
        if source.name in platform_names:
            continue
        destination = root / "x" / source.name
        if destination.exists():
            results.append(("skipped", source, destination))
        elif not apply:
            results.append(("would-move", source, destination))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            results.append(("moved", source, destination))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("output"))
    parser.add_argument("--apply", action="store_true", help="实际移动；默认仅预览")
    args = parser.parse_args()
    results = migrate_output(args.root, apply=args.apply)
    for status, source, destination in results:
        print(f"{status}: {source} -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
