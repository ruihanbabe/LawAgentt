# Safety 模块

负责 `input/context/proposal → risk and constraints → allow/limit/block`。拥有风险判断和最终安全决策；证据、Review、法规有效期、PII 和回答结构门禁必须 fail closed，不能被 LLM 绕过。当前实现分布在 Safety 角色、`delivery_gate.py`、`law_validity.py` 和 `pii.py`。
