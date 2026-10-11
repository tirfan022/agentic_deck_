import streamlit as st
import uuid
import os
import sys
from dotenv import load_dotenv
from langgraph.types import Command

# 1. LOAD & VALIDATE ENVIRONMENT
load_dotenv()

# Add root directory to sys.path for module discovery
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Check for API Keys
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
        "API keys are missing. Configure GOOGLE_API_KEY "
        "and TAVILY_API_KEY in your .env file or Streamlit Secrets."
    )
    st.stop()

# 2. IMPORT AGENT LOGIC
from src.agent.graph import graph
from src.tools.ppt_builder import build_presentation

# 3. PAGE CONFIG
st.set_page_config(page_title="AgenticDeck", page_icon="🚀", layout="centered")

# 4. INITIALIZE SESSION STATE
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "logo_path" not in st.session_state:
    st.session_state.logo_path = None
if "topic" not in st.session_state:
    st.session_state.topic = ""  # Persists topic across reruns

config = {"configurable": {"thread_id": st.session_state.thread_id}}

# 5. SIDEBAR
with st.sidebar:
    st.title("🚀 AgenticDeck Control")

    # --- PDF Knowledge Base ---
    st.header("📂 Knowledge Base")
    uploaded_pdfs = st.file_uploader(
        "Upload reference PDFs for RAG",
        type="pdf",
        accept_multiple_files=True
    )

    if uploaded_pdfs:
        os.makedirs("knowledge_base", exist_ok=True)
        for pdf in uploaded_pdfs:
            file_path = os.path.join("knowledge_base", pdf.name)
            with open(file_path, "wb") as f:
                f.write(pdf.getbuffer())
        st.success(f"✅ {len(uploaded_pdfs)} PDF(s) saved.")

        if st.button("📥 Index PDFs into Knowledge Base"):
            with st.spinner("Building vector store..."):
                from src.tools.rag_service import get_retriever
                retriever = get_retriever()
                if retriever:
                    st.success("✅ PDFs indexed successfully!")
                else:
                    st.error("❌ Indexing failed — check your PDF files.")

    # --- Branding ---
    st.header("🎨 Branding")
    uploaded_logo = st.file_uploader("Upload Company Logo", type=["png", "jpg", "jpeg"])

    if uploaded_logo:
        os.makedirs("output", exist_ok=True)
        logo_path = os.path.abspath(os.path.join("output", "logo.png"))
        st.session_state.logo_path = logo_path
        with open(logo_path, "wb") as f:
            f.write(uploaded_logo.getbuffer())
        st.image(uploaded_logo, width=100, caption="Logo Active")

    st.divider()
    if st.button("🔄 Reset All (New Session)"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.topic = ""
        st.session_state.logo_path = None
        st.rerun()

# 6. MAIN UI
st.title("🚀 AgenticDeck: Hybrid Research Agent")
st.markdown("Combines **Web Search** and **Your PDFs** to build professional slides.")

topic = st.text_input(
    "What should the presentation be about?",
    placeholder="e.g. Impact of Generative AI on 2026 Marketing",
    value=st.session_state.topic
)

if st.button("Generate Outline", type="primary"):
    if not topic:
        st.warning("Please enter a topic.")
    else:
        # Persist topic before rerun
        st.session_state.topic = topic

        with st.spinner("🤖 Agent is researching across Web and PDF Knowledge Base..."):
            try:
                inputs = {
                    "topic": topic,
                    "messages": [],
                    "is_approved": False,
                    "research_notes": "",
                    "slides_json": []
                }
                for event in graph.stream(inputs, config, stream_mode="values"):
                    pass
            except Exception as e:
                st.error(f"Agent error: {str(e)}")
                st.stop()

        st.rerun()

# 7. HUMAN-IN-THE-LOOP REVIEW
current_state = graph.get_state(config)

if current_state.next:  # Graph is paused at 'human_review'
    st.divider()
    st.subheader("📋 Review AI-Generated Outline")

    slides = current_state.values.get("slides_json", [])

    if not slides:
        st.error("No slides were generated. Please try a different topic.")
    else:
        for i, s in enumerate(slides):
            with st.expander(f"Slide {i+1}: {s.get('title', 'Untitled')}"):
                content = s.get("content", [])
                if isinstance(content, list):
                    for bullet in content:
                        st.markdown(f"- {bullet}")
                else:
                    st.write(content)

        if st.button("✅ Approve & Build PowerPoint", use_container_width=True):
            with st.spinner("Generating .pptx file..."):
                try:
                    graph.invoke(Command(resume="approve"), config)
                    final_state = graph.get_state(config).values
                    ppt_file = build_presentation(
                        final_state["slides_json"],
                        st.session_state.logo_path
                    )
                    st.balloons()
                    st.success("✅ Presentation created successfully!")
                    st.download_button(
                        label="📥 Download Presentation (.pptx)",
                        data=ppt_file,
                        file_name=f"{st.session_state.topic.replace(' ', '_')}_Final.pptx",
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation"
                    )
                except Exception as e:
                    st.error(f"Failed to build presentation: {str(e)}")