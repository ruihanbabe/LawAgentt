# Conversation 模块

负责一次用户交互的 application lifecycle：识别会话、加载历史/画像、处理 PII、调用 Runtime、保存结果和 Trace。拥有交互生命周期，不拥有 Runtime 的 Task/Artifact。当前实现位于本目录的 `harness.py`。
