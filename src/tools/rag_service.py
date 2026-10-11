
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma


ROOT_DIR = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_PATH = ROOT_DIR / "knowledge_base"

# Embeddings are reusable model weights, not user documents.
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


def process_local_documents():
    """Load only PDFs currently present in the temporary knowledge base."""
    if not KNOWLEDGE_BASE_PATH.is_dir():
        return []

    documents = []

    for pdf_path in sorted(KNOWLEDGE_BASE_PATH.iterdir()):
        if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            continue

        if pdf_path.stat().st_size == 0:
            continue

        try:
            documents.extend(PyPDFLoader(str(pdf_path)).load())
        except Exception as exc:
            print(f"Could not load PDF {pdf_path.name}: {exc}")

    return documents


def get_retriever():
    """Build a fresh, non-persistent vector store for this request."""
    documents = process_local_documents()

    if not documents:
        print("No current-request PDFs found. RAG will be skipped.")
        return None

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
    )
    chunks = splitter.split_documents(documents)

    if not chunks:
        return None

    # No persist_directory: the vector store exists only in memory.
    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
    )

    print(f"Created an in-memory index with {len(chunks)} chunks.")
    return vector_store.as_retriever(search_kwargs={"k": 3})


def query_local_docs(query: str, retriever) -> str:
    """Retrieve relevant text from the current request's uploaded PDFs."""
    if retriever is None:
        return ""

    try:
        documents = retriever.invoke(query)
        return "\n\n".join(
            doc.page_content for doc in documents if doc.page_content.strip()
        )
    except Exception as exc:
        print(f"PDF retrieval failed: {exc}")
        return ""
