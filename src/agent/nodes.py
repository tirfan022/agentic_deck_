import os
import json
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.messages import HumanMessage as LCHumanMessage
from src.tools.rag_service import get_retriever, query_local_docs


def invoke_llm_with_fallback(messages, temperature=0.2):
    """Try Gemini first; use Groq if Gemini fails (for example, quota exhaustion)."""
    primary = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
        temperature=temperature,
    )

    try:
        return primary.invoke(messages)
    except Exception as primary_error:
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise RuntimeError(
                "Gemini failed and no backup is configured. Add GROQ_API_KEY "
                "to your .env file or Streamlit Cloud Secrets. "
                f"Original Gemini error: {primary_error}"
            ) from primary_error

        print(f"Gemini request failed; switching to Groq backup. Reason: {primary_error}")
        backup = ChatGroq(
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            temperature=temperature,
            api_key=groq_api_key,
        )
        try:
            return backup.invoke(messages)
        except Exception as backup_error:
            raise RuntimeError(
                "Both Gemini and the Groq backup failed. Check both providers' "
                "API keys, model availability, and rate limits. "
                f"Gemini error: {primary_error}; Groq error: {backup_error}"
            ) from backup_error

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
    """Search Tavily and format the returned results."""
    try:
        web_search_tool = get_web_search_tool()
        results = web_search_tool.invoke(topic)

        if not isinstance(results, list) or not results:
            return "No relevant web results found."

        sections = []

        for i, result in enumerate(results, start=1):
            if not isinstance(result, dict):
                continue

            sections.append(
                f"--- Source {i}: {result.get('url', 'N/A')} ---\n"
                f"Title: {result.get('title', 'N/A')}\n"
                f"Content: {result.get('content', '')}"
            )

        return "\n\n".join(sections) or "No relevant web results found."

    except Exception as e:
        raise RuntimeError(f"Web search failed: {e}") from e


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

    response = invoke_llm_with_fallback([
        SystemMessage(content=system_instructions),
        HumanMessage(content=prompt)
    ], temperature=0.2)

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

    response = invoke_llm_with_fallback([
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
    ], temperature=0.3)

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
