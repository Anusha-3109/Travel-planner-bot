"""Chroma vector store with local embeddings.

Embeddings run locally with Chroma's bundled ONNX all-MiniLM-L6-v2 model, so
indexing and search need no API key. The model (~80 MB) downloads on first use.
"""

from functools import lru_cache

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

import config


class LocalEmbeddings(Embeddings):
    def __init__(self) -> None:
        self._embed = DefaultEmbeddingFunction()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in vector] for vector in self._embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@lru_cache(maxsize=1)
def _embeddings() -> LocalEmbeddings:
    return LocalEmbeddings()


@lru_cache(maxsize=1)
def _client() -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=str(config.CHROMA_DIR))


def get_vectorstore() -> Chroma:
    return Chroma(
        client=_client(),
        collection_name=config.COLLECTION_NAME,
        embedding_function=_embeddings(),
        collection_metadata={"hnsw:space": "cosine"},
    )


def reset_vectorstore() -> Chroma:
    client = _client()
    if config.COLLECTION_NAME in [c.name for c in client.list_collections()]:
        client.delete_collection(config.COLLECTION_NAME)
    return get_vectorstore()
