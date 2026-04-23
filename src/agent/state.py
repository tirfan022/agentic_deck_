import operator
from typing import Annotated, List, TypedDict
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    The shared state (memory) for the AgenticDeck engine.
    """
    # Input topic from the user
    topic: str

    # Consolidated research string (Web + RAG)
    research_notes: str

    # Structured slide outline for the PowerPoint
    slides_json: List[dict]

    # Conversation history — Annotated ensures messages append, not overwrite
    messages: Annotated[List[BaseMessage], operator.add]

    # Control flag for Human-in-the-Loop review
    is_approved: bool