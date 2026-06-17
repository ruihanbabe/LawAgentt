from typing import TypedDict, Annotated, List
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class TodoItem(TypedDict):
    task: str
    status: str  # "pending" | "in_progress" | "completed"

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    todo_list: list[TodoItem]
