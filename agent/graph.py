from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage
from agent.llm import llm
from agent.tools import search_laws, search_cases
from agent.state import AgentState
from agent.planner import planner_node
from agent.todo_manager import todo_updater_node, format_todo_list, build_nag_reminder

tools = [search_laws, search_cases]
llm_with_tools = llm.bind_tools(tools)

BASE_SYSTEM_PROMPT = """你是一个专业的法律AI助手。你可以使用以下工具来回答用户的法律问题：

1. search_laws(query): 检索法律条文库，返回相关法条原文
2. search_cases(query): 检索法院裁判案例库，返回相似案例

回答规则：
- 按照任务列表顺序执行，每完成一个检索任务再进入下一个
- 基于检索到的法条和案例回答，标注引用来源（法条名称+条号）
- 如果检索结果不足以回答，明确告知"基于当前检索结果无法确定"
- 不要编造法条或案例
- 回答简洁专业，先给结论再附依据"""


def agent_node(state: AgentState):
    """ReAct Agent 核心节点，动态注入 system prompt。"""
    todo_list = state.get("todo_list", [])
    todo_display = format_todo_list(todo_list)
    nag = build_nag_reminder(todo_list)
    
    system_content = f"{BASE_SYSTEM_PROMPT}\n\n=== 当前任务列表 ===\n{todo_display}{nag}"
    
    # 替换第一条 system message
    messages = [SystemMessage(content=system_content)] + state["messages"][1:]
    
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState):
    """判断是否继续调用工具"""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ━━━━━━━━━━━━━━━━━━━━ 构建图 ━━━━━━━━━━━━━━━━━━━━
graph_builder = StateGraph(AgentState)

graph_builder.add_node("planner", planner_node)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", ToolNode(tools))
graph_builder.add_node("todo_updater", todo_updater_node)

graph_builder.add_edge(START, "planner")
graph_builder.add_edge("planner", "agent")
graph_builder.add_conditional_edges("agent", should_continue, ["tools", END])
graph_builder.add_edge("tools", "todo_updater")
graph_builder.add_edge("todo_updater", "agent")

graph = graph_builder.compile()
