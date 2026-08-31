# API 模块

负责 HTTP、请求校验、路由和 SSE transport，不承担法律推理。拥有 transport DTO；将 HTTP 输入转换为交互请求，将内部事件投影为 SSE。当前实现位于 `main.py` 和本目录的 `sse.py`，必须保持外部协议及脱敏约束不变。
