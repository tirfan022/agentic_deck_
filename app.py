import streamlit as st
import uuid
import os
import sys
import shutil
from pathlib import Path
from dotenv import load_dotenv
from langgraph.types import Command

from src.agent.nodes import revise_outline


ROOT_DIR = Path(__file__).resolve().parent
KB_DIR = ROOT_DIR / "knowledge_base"
VECTOR_DIR = ROOT_DIR / "vector_store"


def clear_transient_knowledge_base():
    """Delete previously uploaded PDFs and any old disk-based index."""
    for directory in (KB_DIR, VECTOR_DIR):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)


def save_request_pdfs(uploaded_files):
    """Save only the PDFs selected for the current request."""
    KB_DIR.mkdir(parents=True, exist_ok=True)
    for uploaded_file in uploaded_files or []:
        filename = Path(uploaded_file.name).name
        if not filename.lower().endswith(".pdf"):
            continue
        data = uploaded_file.getvalue()
        if not data.startswith(b"%PDF-"):
            raise ValueError(f"{filename} does not appear to be a valid PDF.")
        (KB_DIR / filename).write_bytes(data)


# Load and validate environment
load_dotenv()
sys.path.append(str(ROOT_DIR))

for key in ("GOOGLE_API_KEY", "TAVILY_API_KEY"):
    if not os.getenv(key):
        try:
            value = st.secrets[key]
        except (KeyError, FileNotFoundError):
            value = None
        if value:
            os.environ[key] = value

if not os.getenv("GOOGLE_API_KEY") or not os.getenv("TAVILY_API_KEY"):
    st.error(
        "API keys are missing. Configure GOOGLE_API_KEY and TAVILY_API_KEY "
        "in your .env file or Streamlit Secrets."
    )
    st.stop()

from src.agent.graph import graph
from src.tools.ppt_builder import build_presentation


st.set_page_config(page_title="AgenticDeck", page_icon="🚀", layout="centered")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "topic" not in st.session_state:
    st.session_state.topic = ""

config = {"configurable": {"thread_id": st.session_state.thread_id}}

# Sidebar
with st.sidebar:
    st.title("🚀 AgenticDeck Control")
    st.header("📂 Request Knowledge Base")

    if "pdf_upload_key" not in st.session_state:
        st.session_state.pdf_upload_key = 0

    uploaded_pdfs = st.file_uploader(
        "Upload PDFs for this presentation only",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"pdf_upload_{st.session_state.pdf_upload_key}",
        help="These PDFs are used only for the current generation request.",
    )

    st.divider()
    if st.button("🔄 Reset All (New Session)"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.topic = ""
        st.rerun()

# Main UI
st.title("🚀 AgenticDeck: Hybrid Research Agent")
st.markdown("Combines **Web Search** and **Your PDFs** to build professional slides.")

topic = st.text_input(
    "What should the presentation be about?",
    placeholder="e.g. Impact of Generative AI on 2026 Marketing",
    value=st.session_state.topic,
)

if st.button("Generate Outline", type="primary"):
    clean_topic = topic.strip()
    if len(clean_topic) < 3:
        st.warning("Please enter a topic with at least 3 characters.")
    elif len(clean_topic) > 300:
        st.warning("Topic must be 300 characters or fewer.")
    else:
        try:
            request_pdfs = list(uploaded_pdfs or [])
            clear_transient_knowledge_base()
            save_request_pdfs(request_pdfs)
            st.session_state.pdf_upload_key += 1

            st.session_state.thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            st.session_state.topic = clean_topic

            inputs = {
                "topic": clean_topic,
                "messages": [],
                "is_approved": False,
                "research_notes": "",
                "slides_json": [],
            }

            with st.spinner("Researching your topic..."):
                try:
                    for _ in graph.stream(inputs, config, stream_mode="values"):
                        pass
                finally:
                    clear_transient_knowledge_base()
            st.rerun()

        except Exception as exc:
            try:
                clear_transient_knowledge_base()
            except OSError:
                pass
            st.error(f"Outline generation failed: {exc}")

# Human-in-the-loop review
current_state = graph.get_state(config)

if current_state.next:
    st.divider()
    st.subheader("📋 Review AI-Generated Outline")
    slides = current_state.values.get("slides_json", [])

    if not slides:
        st.error("No slides were generated. Please try a different topic.")
    else:
        for i, slide_data in enumerate(slides):
            with st.expander(f"Slide {i + 1}: {slide_data.get('title', 'Untitled')}"):
                content = slide_data.get("content", [])
                if isinstance(content, list):
                    for bullet in content:
                        st.markdown(f"- {bullet}")
                else:
                    st.write(content)
else:
    slides = current_state.values.get("slides_json", [])

feedback = st.text_area(
    "What would you like to change?",
    placeholder="Make it more technical, add real-world examples, or improve the slide sequence.",
    max_chars=2000,
    key="outline_feedback",
)

if st.button("💡 Suggest Changes / Regenerate Outline"):
    if not feedback.strip():
        st.warning("Enter the changes you want first.")
    else:
        try:
            with st.spinner("Revising your outline..."):
                revised_slides = revise_outline(
                    topic=current_state.values.get("topic", ""),
                    research_notes=current_state.values.get("research_notes", ""),
                    current_slides=slides,
                    feedback=feedback,
                )
                graph.update_state(
                    config,
                    {"slides_json": revised_slides},
                    as_node="architect",
                )
                graph.invoke(None, config)
            st.rerun()
        except Exception as exc:
            st.error(f"Could not revise the outline: {exc}")

if st.button("✅ Approve & Build PowerPoint", use_container_width=True):
    with st.spinner("Generating text-only .pptx file..."):
        try:
            graph.invoke(Command(resume="approve"), config)
            final_state = graph.get_state(config).values
            ppt_file = build_presentation(
                final_state["slides_json"],
                topic=final_state.get("topic", st.session_state.get("topic", "")),
            )
            st.balloons()
            st.success("✅ Text-only presentation created successfully!")
            st.download_button(
                label="📥 Download Presentation (.pptx)",
                data=ppt_file,
                file_name=f"{st.session_state.topic.replace(' ', '_')}_Final.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        except Exception as exc:
            st.error(f"Failed to build presentation: {exc}")
