import os
from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# Initialize embeddings once (runs on CPU, no API key needed)
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

KNOWLEDGE_BASE_PATH = "./knowledge_base"
VECTOR_STORE_PATH = "./vector_store"


def process_local_documents():
    """
    Loads all valid PDFs from the knowledge_base folder.
    Skips empty or hidden files.
    Returns a list of Document objects, or [] if none found.
    """
    if not os.path.exists(KNOWLEDGE_BASE_PATH):
        return []

    files = [f for f in os.listdir(KNOWLEDGE_BASE_PATH) if f.endswith(".pdf")]
    if not files:
        return []

    # Remove empty or hidden files before loading
    for file in files:
        file_path = os.path.join(KNOWLEDGE_BASE_PATH, file)
        if os.path.getsize(file_path) == 0:
            print(f"Skipping empty file: {file}")
            os.remove(file_path)

    loader = DirectoryLoader(
        KNOWLEDGE_BASE_PATH,
        glob="**/[!.]*.pdf",
        loader_cls=PyPDFLoader
    )

    try:
        documents = loader.load()
        print(f"✅ Loaded {len(documents)} document pages from knowledge base.")
        return documents
    except Exception as e:
        print(f"Error loading documents: {e}")
        return []


def get_retriever():
    """
    Builds a Chroma vector store from local PDFs and returns a retriever.
    Persists the DB to ./vector_store for reuse.
    Returns None if no documents are available.
    """
    docs = process_local_documents()
    if not docs:
        print("⚠️ No local documents found. RAG will be skipped.")
        return None

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(docs)

    db = Chroma.from_documents(
        chunks,
        embeddings,
        persist_directory=VECTOR_STORE_PATH
    )
    print(f"✅ Vector store built with {len(chunks)} chunks.")
    return db.as_retriever(search_kwargs={"k": 3})


def query_local_docs(query: str, retriever):
    """
    Searches the local PDF vector store for content relevant to query.
    Returns a string of concatenated relevant chunks.
    """
    if not retriever:
        return "No local documents available for research."

    try:
        relevant_docs = retriever.invoke(query)
        context = "\n\n".join([doc.page_content for doc in relevant_docs])
        return context if context else "No relevant info found in local PDFs."
    except Exception as e:
        return f"Error searching PDFs: {str(e)}"