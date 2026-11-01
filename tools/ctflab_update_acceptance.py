#!/usr/bin/env python3
"""两个可信本地候选的槽位/回退验收；不替换已安装 App，不操作虚拟机。"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import ctflab_update as update


def main():
    if not sys.dont_write_bytecode:
        raise SystemExit("请使用 python3 -B，避免修改候选 App")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    root = Path(tempfile.mkdtemp(prefix="ctflab-update-acceptance-", dir="/private/tmp"))
    hashes = [update.app_tree_hash(app) for app in (args.first, args.second)]
    steps = []
    for index, app in enumerate((args.first, args.second)):
        item = update.stage(root, app, hashes[index], allow_local=True)
        steps.append({"operation": "stage", **item})
        steps.append({"operation": "select", **update.select(root, item["slot"])})
        print(json.dumps(steps[-1], ensure_ascii=False), flush=True)
    rollback = update.select(root, rollback=True)
    steps.append({"operation": "rollback", **rollback})
    passed = (rollback["active"] == steps[0]["slot"] and
              rollback["previous"] == steps[2]["slot"] and
              all(update.app_tree_hash(app) == value for app, value in zip((args.first, args.second), hashes)))
    result = {"passed": passed, "root": str(root), "steps": steps,
              "scope": "local-verified-slot-copy-select-rollback-no-launch-or-image-mutation"}
    (args.out / "update-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"passed": passed, "evidence": str(args.out / "update-evidence.json")}, ensure_ascii=False))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__": main()
