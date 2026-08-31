# Intake 模块

负责 `raw statement → extracted fact → clarified/confirmed fact → intake-ready state`。拥有案件事实、信息缺口、确认状态和充分性判断；未确认内容不得升级为确认事实。核心状态位于本目录的 `blackboard.py`，Understanding 角色仍由 Runtime 调度。
