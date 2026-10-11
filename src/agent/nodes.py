import os
import json
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.messages import HumanMessage as LCHumanMessage
from src.tools.rag_service import get_retriever, query_local_docs

# ─── Web Search Tool ────────────────────────────────

def get_web_search_tool():
    """Initialize Tavily only when a web search is actually needed."""
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY is missing. Check your .env file "
            "or Streamlit Cloud Secrets."
        )

    return TavilySearchResults(
        k=3,
        tavily_api_key=api_key,
    )

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
    llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0.2)

    notes = state.get("research_notes", "No research notes found.")
    topic = state.get("topic", "General Topic")

    system_instructions = (
        "You are a professional presentation architect. "
        "Create a 5-slide presentation based on the research notes. "
        "Output ONLY raw JSON — a list of 5 dicts, each with keys 'title' (string) "
        "and 'content' (list of 3-4 bullet point strings). "
        "Do NOT include any markdown, code fences, or explanation text."
    )

    prompt = f"Topic: {topic}\n\nResearch Notes:\n{notes}"

    response = llm.invoke([
        SystemMessage(content=system_instructions),
        HumanMessage(content=prompt)
    ])

    try:
        # Handle both string and list response formats
        raw = response.content
        if isinstance(raw, list):
            # Extract text from the first text block
            raw = next((block["text"] for block in raw if isinstance(block, dict) and block.get("type") == "text"), "")
        
        clean_json = raw.replace("```json", "").replace("```", "").strip()
        slides = json.loads(clean_json)
    except Exception as e:
        print(f"JSON parse error: {e}\nRaw response: {response.content}")
        slides = [{"title": "Error", "content": ["Could not parse output.", "Please try again."]}]

    return {
        "slides_json": slides,
        "messages": [LCHumanMessage(content=f"Architect built slides for: {topic}")]
    }



def revise_outline(topic, research_notes, current_slides, feedback):
    """Generate a revised outline using existing research notes."""
    import json

    if not feedback.strip():
        raise ValueError("Please describe the changes you want.")

    llm = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        temperature=0.3,
    )

    response = llm.invoke([
        SystemMessage(content=(
            "Revise a presentation outline using the user's feedback. "
            "Use the supplied research, preserve factual accuracy, and "
            "return ONLY valid JSON: a list of exactly five objects. "
            "Each object must have a title string and a content list "
            "containing 3 to 4 bullet-point strings."
        )),
        HumanMessage(content=(
            f"Topic:\n{topic}\n\n"
            f"Research notes:\n{research_notes[:18000]}\n\n"
            f"Current outline:\n"
            f"{json.dumps(current_slides, ensure_ascii=False)}\n\n"
            f"Requested changes:\n{feedback[:2000]}"
        )),
    ])

    raw = response.content
    if isinstance(raw, list):
        raw = "\n".join(
            item["text"]
            for item in raw
            if isinstance(item, dict)
            and item.get("type") == "text"
        )

    if not isinstance(raw, str):
        raise ValueError("The model returned an invalid response.")

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.rstrip().endswith("```"):
            raw = raw.rstrip()[:-3].strip()

    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end < start:
        raise ValueError("The model did not return valid JSON.")

    slides = json.loads(raw[start:end + 1])

    if not isinstance(slides, list) or len(slides) != 5:
        raise ValueError("The revised outline must have five slides.")

    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            raise ValueError(f"Slide {index} is invalid.")

        title = slide.get("title")
        content = slide.get("content")

        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"Slide {index} has no valid title.")

        if (
            not isinstance(content, list)
            or not 3 <= len(content) <= 4
            or any(not isinstance(item, str) or not item.strip()
                   for item in content)
        ):
            raise ValueError(
                f"Slide {index} must have 3 to 4 valid bullet points."
            )

    return slides