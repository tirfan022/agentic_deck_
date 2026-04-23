from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt
from src.agent.state import AgentState
from src.agent.nodes import researcher_node, architect_node


def human_review_node(state: AgentState):
    """
    Pauses the graph for human review.
    Streamlit will display the slides_json, then resume with 'approve'.
    """
    decision = interrupt("Please review and approve the slide outline.")
    return {"is_approved": decision == "approve"}


# Build the graph
builder = StateGraph(AgentState)

builder.add_node("researcher", researcher_node)
builder.add_node("architect", architect_node)
builder.add_node("human_review", human_review_node)

builder.add_edge(START, "researcher")
builder.add_edge("researcher", "architect")
builder.add_edge("architect", "human_review")
builder.add_edge("human_review", END)

# Compile with in-memory checkpointing (required for interrupt to work)
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)
