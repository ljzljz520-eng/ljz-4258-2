"""规范化输入摘要 (frozen input digest)。

用途：
  * 作业入队时对「窗口 + 参与样本 + 罐存量 + 拓扑」快照计算 SHA-256；
  * Worker 取出作业后重算摘要，不一致则拒绝（防止运行期间输入漂移）；
  * 签署记录冻结该摘要与算法版本，任何被纳入的输入变化都会产生新摘要，
    旧签署保持不变（不可变性要求）。
规范化：JSON sort_keys、固定分隔符、UTC ISO 时间、NaN 不允许。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def input_digest(payload: Any) -> str:
    blob = canonical_json(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
