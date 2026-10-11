import os
import sys
import time
import uuid
import shutil
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from langgraph.types import Command

# --------------------------------------------------
# 1. PAGE CONFIG, PATHS, ENVIRONMENT
# --------------------------------------------------

st.set_page_config(page_title="AgenticDeck", page_icon="🚀", layout="centered")

ROOT_DIR = Path(__file__).resolve().parent
KB_DIR = ROOT_DIR / "knowledge_base"
VECTOR_DIR = ROOT_DIR / "vector_store"
OUTPUT_DIR = ROOT_DIR / "output"

load_dotenv()

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

for key in ("GOOGLE_API_KEY", "TAVILY_API_KEY"):
    if not os.getenv(key):
        try:
            value = st.secrets.get(key)
        except Exception:
            value = None
        if value:
            os.environ[key] = value

missing_keys = [
    key for key in ("GOOGLE_API_KEY", "TAVILY_API_KEY")
    if not os.getenv(key)
]

if missing_keys:
    st.error(
        "Missing API keys: "
        + ", ".join(missing_keys)
        + ". Configure them in your .env file or Streamlit Secrets."
    )
    st.stop()

from src.agent.graph import graph
from src.agent.nodes import revise_outline
from src.tools.ppt_builder import build_presentation


# --------------------------------------------------
# 2. SESSION STATE
# --------------------------------------------------

defaults = {
    "thread_id": str(uuid.uuid4()),
    "topic": "",
    "logo_path": None,
    "generated_pptx": None,
    "generated_filename": None,
    "_api_usage": {},
    "pdf_upload_key": 0,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


def get_config():
    return {"configurable": {"thread_id": st.session_state.thread_id}}


# --------------------------------------------------
# 3. SESSION-LEVEL RATE LIMITING
# --------------------------------------------------

def allow_action(action: str, per_minute: int, per_day: int) -> bool:
    """
    Session-level rolling-window limits.

    These limits protect against accidental repeated clicks in one
    Streamlit session. They are not global/provider-level API quotas.
    """
    now = time.time()
    usage = st.session_state["_api_usage"]
    history = [
        timestamp
        for timestamp in usage.get(action, [])
        if now - timestamp < 86400
    ]

    recent_count = sum(1 for timestamp in history if now - timestamp < 60)

    if recent_count >= per_minute:
        st.warning(
            f"Per-minute limit reached for {action.replace('_', ' ')}. "
            "Please wait a minute before trying again."
        )
        usage[action] = history
        return False

    if len(history) >= per_day:
        st.warning(
            f"Daily limit reached for {action.replace('_', ' ')}. "
            "Please try again later."
        )
        usage[action] = history
        return False

    history.append(now)
    usage[action] = history
    return True


# --------------------------------------------------
# 4. TRANSIENT PDF KNOWLEDGE BASE
# --------------------------------------------------

def clear_transient_knowledge_base():
    """Clear PDFs and any disk-based index for the next request."""
    for directory in (KB_DIR, VECTOR_DIR):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)


def save_request_pdfs(uploaded_files):
    """Save only PDFs selected for the current outline-generation request."""
    KB_DIR.mkdir(parents=True, exist_ok=True)

    for uploaded_file in uploaded_files or []:
        filename = Path(uploaded_file.name).name

        if not filename.lower().endswith(".pdf"):
            continue

        data = uploaded_file.getvalue()
        if not data.startswith(b"%PDF-"):
            raise ValueError(f"{filename} does not appear to be a valid PDF.")

        (KB_DIR / filename).write_bytes(data)


# --------------------------------------------------
# 5. SIDEBAR: PDFS, LOGO, RESET
# --------------------------------------------------

with st.sidebar:
    st.title("🚀 AgenticDeck Control")
    st.subheader("📂 Request Knowledge Base")

    uploaded_pdfs = st.file_uploader(
        "Upload PDFs for this presentation only",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"pdf_upload_{st.session_state.pdf_upload_key}",
        help="These PDFs are used for the current outline-generation request.",
    )

    st.divider()
    st.subheader("🎨 Branding")

    uploaded_logo = st.file_uploader(
        "Upload a company logo",
        type=["png", "jpg", "jpeg"],
        key="company_logo_upload",
    )

    if uploaded_logo:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        logo_path = OUTPUT_DIR / "logo.png"
        logo_path.write_bytes(uploaded_logo.getvalue())
        st.session_state.logo_path = str(logo_path)
        st.image(uploaded_logo, width=120, caption="Active logo")

    elif st.session_state.logo_path and Path(st.session_state.logo_path).is_file():
        st.image(
            st.session_state.logo_path,
            width=120,
            caption="Active logo",
        )

    if st.button("🗑️ Remove logo"):
        st.session_state.logo_path = None
        st.rerun()

    st.divider()
    if st.button("🔄 Reset Session"):
        # Reset the graph thread and generated output, but retain usage history
        # so resetting the UI does not reset this session's rate limits.
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.topic = ""
        st.session_state.generated_pptx = None
        st.session_state.generated_filename = None
        st.session_state.pdf_upload_key += 1
        st.rerun()


# --------------------------------------------------
# 6. GENERATE INITIAL OUTLINE
# --------------------------------------------------

st.title("🚀 AgenticDeck: Hybrid Research Agent")
st.markdown(
    "Combines **web research** and **your PDFs** to build professional slides."
)

topic = st.text_input(
    "What should the presentation be about?",
    placeholder="e.g. Impact of Generative AI on 2026 Marketing",
    value=st.session_state.topic,
    max_chars=300,
)

if st.button("✨ Generate Outline", type="primary"):
    clean_topic = topic.strip()

    if len(clean_topic) < 3:
        st.warning("Please enter a topic with at least 3 characters.")
    elif allow_action("generate_outline", per_minute=2, per_day=10):
        request_pdfs = list(uploaded_pdfs or [])

        try:
            clear_transient_knowledge_base()
            save_request_pdfs(request_pdfs)

            st.session_state.pdf_upload_key += 1
            st.session_state.thread_id = str(uuid.uuid4())
            st.session_state.topic = clean_topic
            st.session_state.generated_pptx = None
            st.session_state.generated_filename = None

            config = get_config()
            inputs = {
                "topic": clean_topic,
                "messages": [],
                "is_approved": False,
                "research_notes": "",
                "slides_json": [],
            }

            with st.spinner("Researching your topic and generating an outline..."):
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


# --------------------------------------------------
# 7. REVIEW AND REVISE OUTLINE
# --------------------------------------------------

config = get_config()

try:
    current_state = graph.get_state(config)
except Exception:
    current_state = None

if current_state and current_state.next:
    st.divider()
    st.subheader("📋 Review AI-Generated Outline")

    slides = current_state.values.get("slides_json", [])
    research_notes = current_state.values.get("research_notes", "")

    if not slides:
        st.error("No slides were generated. Please try a different topic.")
    else:
        for index, slide_data in enumerate(slides, start=1):
            title = slide_data.get("title", "Untitled")
            with st.expander(f"Slide {index}: {title}"):
                content = slide_data.get("content", [])
                if isinstance(content, list):
                    for bullet in content:
                        st.markdown(f"- {bullet}")
                else:
                    st.write(content)

        st.markdown("### 💡 Suggest Changes / Regenerate Outline")
        feedback = st.text_area(
            "What would you like to change?",
            placeholder=(
                "Make it more technical, add real-world examples, "
                "or improve the slide sequence."
            ),
            max_chars=2000,
            key="outline_feedback",
        )

        if st.button("💡 Suggest Changes / Regenerate Outline"):
            if not feedback.strip():
                st.warning("Enter the changes you want first.")
            elif allow_action("revise_outline", per_minute=3, per_day=20):
                try:
                    with st.spinner("Revising your outline..."):
                        revised_slides = revise_outline(
                            topic=current_state.values.get("topic", st.session_state.topic),
                            research_notes=research_notes,
                            current_slides=slides,
                            feedback=feedback.strip(),
                        )

                        graph.update_state(
                            config,
                            {"slides_json": revised_slides},
                            as_node="architect",
                        )
                        graph.invoke(None, config)

                    st.session_state.generated_pptx = None
                    st.session_state.generated_filename = None
                    st.rerun()

                except Exception as exc:
                    st.error(f"Could not revise the outline: {exc}")

        if st.button("✅ Approve & Build PowerPoint", use_container_width=True):
            if allow_action("build_presentation", per_minute=2, per_day=10):
                try:
                    with st.spinner("Generating text-only PowerPoint..."):
                        graph.invoke(Command(resume="approve"), config)
                        final_state = graph.get_state(config).values

                        ppt_file = build_presentation(
                            final_state["slides_json"],
                            logo_path=st.session_state.logo_path,
                            topic=final_state.get("topic", st.session_state.topic),
                        )

                        st.session_state.generated_pptx = ppt_file.getvalue()
                        safe_topic = "".join(
                            char if char.isalnum() or char in "-_ " else "_"
                            for char in st.session_state.topic
                        ).strip().replace(" ", "_")
                        st.session_state.generated_filename = (
                            f"{safe_topic or 'AgenticDeck'}_Final.pptx"
                        )

                    st.balloons()
                    st.success("Presentation created successfully!")
                    st.rerun()

                except Exception as exc:
                    st.error(f"Failed to build presentation: {exc}")


# --------------------------------------------------
# 8. DOWNLOAD GENERATED POWERPOINT
# --------------------------------------------------

if st.session_state.generated_pptx:
    st.divider()
    st.success("Your PowerPoint is ready!")

    st.download_button(
        label="📥 Download Presentation (.pptx)",
        data=st.session_state.generated_pptx,
        file_name=st.session_state.generated_filename or "AgenticDeck_Final.pptx",
        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        use_container_width=True,
    )
