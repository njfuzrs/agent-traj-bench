#!/usr/bin/env python3
"""T3 生成，勿手改。解析 junit XML → 写 reward.json / reward.txt。

## 🔴 为什么文件名是 reward.json（单数）

核 harbor 源码 `models/trial/paths.py:45-46` + `verifier/verifier.py:226`：
harbor 读 `/logs/verifier/reward.json`，**没有** `rewards.json` 这个名字。
写复数的后果不是报错而是**静默降级** —— harbor 退回读 `reward.txt`（单值），
`f2p` / `p2p` 两个键永远不进 result.json。

## 🔴 为什么必须做文件覆盖核对，不能只读 failures

实测：`bun test --reporter=junit good.test.ts loadfail.test.ts` 的 XML 根节点是
`tests="6" failures="0"`（看着全绿），而日志是 `6 pass / 1 fail / 1 error` ——
**加载失败的文件不会生成 `<testsuite>` 节点，从 XML 里整个消失**。
只读 `failures` 会把「一个测试文件根本没跑起来」判成满分通过。

所以判绿要求**三条同时成立**：① 名单里每个文件都在 XML 里出现（证明加载成功）
② 该文件 `failures == 0` ③ 该文件 `tests > 0`（零用例不构成回归保护）。

## 每条路径都要写 reward（规则1）

XML 缺失或解析失败 → 判 0 并在 `reward.json` 记 `error`，**不抛异常**。
只单跑一个加载失败的文件时 bun 连 XML 都不写，这条路径是真实会走到的。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

VERIFIER_DIR = Path("/logs/verifier")
#: 名单由 T3 字面写入（规则5），与 test.sh 里那两行同源
F2P_FILES = json.loads(Path("/tests/f2p.json").read_text())
P2P_FILES = json.loads(Path("/tests/p2p.json").read_text())


def side_score(xml_name: str, required: list[str]) -> tuple[float, dict]:
    """一侧的分：要求的每个文件都必须**出现且全绿**，否则 0。"""
    if not required:
        # 空名单不该判满分 —— 那是「没有判据」，不是「通过了」
        return 0.0, {"error": "empty_file_list"}
    path = VERIFIER_DIR / xml_name
    if not path.exists():
        # bun 在「唯一的文件加载失败」时不写 XML，这条路径是实测走到过的
        return 0.0, {"error": "xml_missing", "missing": required}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return 0.0, {"error": "xml_parse_error", "detail": str(e)[:200]}

    seen: dict[str, tuple[int, int]] = {}
    for suite in root:  # 只看直接子节点：bun 一个文件一个顶层 testsuite
        f = suite.get("file")
        if f:
            seen[f] = (int(suite.get("tests") or 0), int(suite.get("failures") or 0))

    missing = [f for f in required if f not in seen]          # 没加载起来 = 没跑
    empty = [f for f in required if seen.get(f, (0, 0))[0] == 0 and f not in missing]
    failed = [f for f in required if seen.get(f, (0, 1))[1] > 0]
    ok = not missing and not empty and not failed
    return (1.0 if ok else 0.0), {
        "n_required": len(required),
        "n_seen": len(required) - len(missing),
        "missing": missing,
        "no_tests": empty,
        "failed": failed,
    }


def main() -> int:
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    f2p, f2p_detail = side_score("f2p.xml", F2P_FILES)
    p2p, p2p_detail = side_score("p2p.xml", P2P_FILES)
    # reward = 两侧都过才算解出来：F2P 证明修好了，P2P 证明没砸别处
    reward = 1.0 if (f2p == 1.0 and p2p == 1.0) else 0.0
    doc = {"reward": reward, "f2p": f2p, "p2p": p2p, "f2p_detail": f2p_detail, "p2p_detail": p2p_detail}
    # 双源：harbor 优先读 reward.json，reward.txt 供 T5 交叉核对（§3.8-D）
    (VERIFIER_DIR / "reward.json").write_text(json.dumps(doc, ensure_ascii=False) + "\n")
    (VERIFIER_DIR / "reward.txt").write_text(f"{reward}\n")
    print(json.dumps(doc, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
