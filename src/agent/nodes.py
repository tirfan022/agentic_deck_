import os
import json
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.messages import HumanMessage as LCHumanMessage
from src.tools.rag_service import get_retriever, query_local_docs

# ─── Web Search Tool (replaces web_scout.py) ────────────────────────────────

web_search_tool = TavilySearchResults(k=3)

def perform_web_search(topic: str) -> str:
    """
    Searches the web using Tavily and returns a formatted string of results.
    """
    try:
        results = web_search_tool.invoke(topic)
        context = ""
        for i, r in enumerate(results):
            context += f"\n--- Source {i+1}: {r.get('url', 'N/A')} ---\n"
            context += f"Title: {r.get('title', 'N/A')}\n"
            context += f"Content: {r.get('content', '')}\n"
        return context if context else "No relevant web results found."
    except Exception as e:
        return f"Web search failed: {str(e)}"


# ─── Researcher Node ─────────────────────────────────────────────────────────

def researcher_node(state):
    """
    Hybrid researcher:
    - If PDFs are indexed → uses RAG (local ChromaDB)
    - Otherwise → falls back to Tavily web search
    """
    topic = state.get("topic", "")

    retriever = get_retriever()

    if retriever:
        print("🔍 Local docs found — running RAG...")
        context = query_local_docs(topic, retriever)
        source = "local PDFs"
    else:
        print("🌐 No local docs — searching the web...")
        context = perform_web_search(topic)
        source = "web search"

    return {
        "research_notes": context,
        "messages": [LCHumanMessage(content=f"Research completed via {source} for topic: {topic}")]
    }


# ─── Architect Node ──────────────────────────────────────────────────────────

def architect_node(state):
    """
    Uses Gemini to convert research notes into a clean 5-slide JSON outline.
    """
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)

    notes = state.get("research_notes", "No research notes available.")
    topic = state.get("topic", "General Topic")

    system_instructions = (
        "You are a professional presentation architect. "
        "Create a 5-slide presentation based on the provided research notes. "
        "Output ONLY raw JSON — a list of exactly 5 dicts. "
        "Each dict must have: "
        "'title' (a short string) and "
        "'content' (a list of 3-4 concise bullet point strings). "
        "Do NOT include markdown, code fences, or any explanation. Just the JSON."
    )

    prompt = f"Topic: {topic}\n\nResearch Notes:\n{notes}"

    response = llm.invoke([
        SystemMessage(content=system_instructions),
        HumanMessage(content=prompt)
    ])

    try:
        clean_json = response.content.replace("```json", "").replace("```", "").strip()
        slides = json.loads(clean_json)
    except Exception as e:
        print(f"⚠️ JSON parse error: {e}\nRaw response:\n{response.content}")
        slides = [
            {
                "title": "Research Summary",
                "content": [
                    "Could not parse structured output.",
                    "Please try again with a more specific topic.",
                    f"Raw error: {str(e)}"
                ]
            }
        ]

    return {
        "slides_json": slides,
        "messages": [LCHumanMessage(content=f"Architect built {len(slides)} slides for: {topic}")]
    }