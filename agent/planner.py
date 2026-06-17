import json
from langchain_core.messages import SystemMessage, HumanMessage
from agent.llm import llm
from agent.state import AgentState, TodoItem

PLANNER_PROMPT = """你是一个法律推理任务规划器。你的任务是将用户的法律问题拆解为可执行的检索和推理子任务。

规则：
1. 每个子任务必须是一个明确的、可通过检索工具完成的具体动作
2. 任务数量不超过 5 个
3. 对于简单的单跳问题（如"劳动合同法试用期多久"），只生成 1 个任务
4. 对于多跳问题（如"竞业协议违约金和试用期违法解除赔偿能否同时主张"），拆解为多个子任务
5. 最后一个任务应该是"综合已检索的信息回答用户问题"

输出格式：严格的 JSON 数组，不要有任何其他文字：
[
  {"task": "检索《劳动合同法》关于试用期时长的规定", "status": "pending"},
  {"task": "检索《劳动合同法》关于试用期违法解除的规定", "status": "pending"},
  {"task": "综合检索结果回答用户问题", "status": "pending"}
]

重要：你的输出必须以 [ 开头，以 ] 结尾，中间是合法 JSON。不要包含任何 markdown 格式标记。"""


def planner_node(state: AgentState) -> dict:
    """生成初始 todo_list，注入到 State 中。"""
    last_user_msg = state["messages"][-1].content
    
    response = llm.invoke([
        SystemMessage(content=PLANNER_PROMPT),
        HumanMessage(content=f"用户问题：{last_user_msg}\n\n请生成任务列表：")
    ])

    raw = response.content.strip()
    
    # 鲁棒的 JSON 提取：直接找第一个 '[' 和最后一个 ']'，规避 markdown 引号问题
    start_idx = raw.find('[')
    end_idx = raw.rfind(']')
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = raw[start_idx : end_idx + 1]
    else:
        json_str = "" # 找不到合法范围，触发下面的异常降级

    try:
        todo_items_raw = json.loads(json_str)
        todo_list = [
            {"task": item["task"], "status": "pending"}
            for item in todo_items_raw
        ]
    except Exception as e:
        print(f"⚠️ Planner JSON 解析失败，降级为单任务: {e}")
        print(f"   原始输出: {raw[:200]}")
        todo_list = [{"task": f"检索并回答：{last_user_msg}", "status": "pending"}]

    # 初始化：第一个任务标记为 in_progress
    if todo_list:
        todo_list[0]["status"] = "in_progress"

    print(f"📋 Planner 生成 {len(todo_list)} 个任务:")
    for i, t in enumerate(todo_list):
        print(f"   [{i+1}] ({t['status']}) {t['task']}")

    return {"todo_list": todo_list}
