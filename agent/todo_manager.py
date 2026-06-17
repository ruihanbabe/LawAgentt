from agent.state import AgentState, TodoItem

def todo_updater_node(state: AgentState) -> dict:
    """
    工具执行完成后，推进任务状态。
    1. 当前 in_progress 标记为 completed
    2. 下一个 pending 标记为 in_progress
    """
    todo_list = state.get("todo_list", [])
    if not todo_list:
        return {}

    # 找到当前 in_progress，标记为 completed
    for item in todo_list:
        if item["status"] == "in_progress":
            item["status"] = "completed"
            print(f"✅ 任务完成: {item['task']}")
            break

    # 找到下一个 pending，标记为 in_progress
    for item in todo_list:
        if item["status"] == "pending":
            item["status"] = "in_progress"
            print(f"▶️ 开始任务: {item['task']}")
            break

    return {"todo_list": todo_list}


def format_todo_list(todo_list: list[TodoItem]) -> str:
    """格式化 todo_list 为可读字符串。"""
    if not todo_list:
        return "（无任务规划）"

    lines = []
    for i, item in enumerate(todo_list, 1):
        icon = {"pending": "⬜", "in_progress": "🔵", "completed": "✅"}.get(item["status"], "⬜")
        lines.append(f"  {icon} [{i}] {item['task']}  [{item['status']}]")
    return "\n".join(lines)


def build_nag_reminder(todo_list: list[TodoItem]) -> str:
    """根据当前 todo 状态生成 nag reminder。"""
    if not todo_list:
        return ""

    current_task = None
    for item in todo_list:
        if item["status"] == "in_progress":
            current_task = item["task"]
            break

    all_completed = all(item["status"] == "completed" for item in todo_list)

    if all_completed:
        return "\n\n⚡ 提醒：所有规划任务已完成。请基于已检索到的法条和案例，综合回答用户的问题。不要再调用工具，直接给出最终答案。"
    elif current_task:
        return f"\n\n⚡ 提醒：你当前正在执行任务——「{current_task}」。请使用合适的检索工具完成这个任务。不要跳过当前任务去回答最终问题。"
    else:
        next_task = None
        for item in todo_list:
            if item["status"] == "pending":
                next_task = item["task"]
                item["status"] = "in_progress"
                break
        if next_task:
            return f"\n\n⚡ 提醒：请开始执行下一个任务——「{next_task}」。"
        return ""
