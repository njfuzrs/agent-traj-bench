#!/usr/bin/env python3
"""让本层的 `import common` 永远拿到本层那份 —— 与 pipeline/tests/conftest.py 对称

为什么需要这个文件（迁移方案 §2.8）：`pipeline/s1_s3/common.py` 与
`scripts/common.py` 同名不同物，两层都用 `sys.path.insert(0, ...)` + `import
common`，而 `sys.modules` 是进程级缓存 ⇒ **谁先加载谁赢**。

单独跑一层时不会撞（两层从不在同一进程里跑生产代码）。撞的只有一种场合：
`pytest pipeline/tests scripts/tests` 一次收集两个目录。实测两种顺序都红 ——
scripts 先则 pipeline 5 条挂在 `module 'common' has no attribute AGENT_SOURCES`，
pipeline 先则 scripts 整个收集失败（`no attribute REPO_ROOT`）。

⛔ 判据落在 pytest 层，不改生产代码：两层的 `import common` 写法是对的，
错的是「同一进程里装两份同名模块」这件事本身。

两个时机都要管：
  ① 收集期 —— conftest 比同目录的测试模块先导入，这里先把 sys.modules 占住，
     测试模块的 `import common` 就直接拿到本层那份，不会走 sys.path 查找。
  ② 运行期 —— 测试函数内用 spec 现加载的脚本（scripts 层有 5 个）自己也会
     `import common`，那时 sys.modules 里可能是另一层留下的。autouse fixture
     在每条用例前把本层那份重新占住，退出时原样还回去。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_OWN_COMMON = Path(__file__).resolve().parent.parent / "common.py"  # scripts/common.py
_own = None


def _load_own():
    """按绝对路径加载本层的 common，绕开 sys.path 与 sys.modules 缓存"""
    global _own
    if _own is None:
        spec = importlib.util.spec_from_file_location("common", _OWN_COMMON)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _own = mod
    return _own


# 时机①：收集期就占住
sys.modules["common"] = _load_own()


@pytest.fixture(autouse=True)
def _own_common_wins():
    """时机②：每条用例期间保证 sys.modules['common'] 是本层那份"""
    prev = sys.modules.get("common")
    sys.modules["common"] = _load_own()
    try:
        yield
    finally:
        if prev is None:
            sys.modules.pop("common", None)
        else:
            sys.modules["common"] = prev
