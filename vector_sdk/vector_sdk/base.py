from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Optional
from enum import StrEnum
from pydantic import BaseModel
from enum import Enum


class ChildDocument(BaseModel):
    """Class for storing a piece of text and associated metadata."""

    page_content: str

    vector: Optional[list[float]] = None

    """Arbitrary metadata about the page content (e.g., source, relationships to other
        documents, etc.).
    """
    metadata: dict = {}


class Document(BaseModel):
    """Class for storing a piece of text and associated metadata."""

    page_content: str

    vector: Optional[list[float]] = None

    """Arbitrary metadata about the page content (e.g., source, relationships to other
        documents, etc.).
    """
    metadata: dict = {}

    provider: Optional[str] = ""

    children: Optional[list[ChildDocument]] = None


class BaseDocumentTransformer(ABC):
    """Abstract base class for document transformation systems.

    A document transformation system takes a sequence of Documents and returns a
    sequence of transformed Documents.

    Example:
        .. code-block:: python

            class EmbeddingsRedundantFilter(BaseDocumentTransformer, BaseModel):
                model_config = ConfigDict(arbitrary_types_allowed=True)

                embeddings: Embeddings
                similarity_fn: Callable = cosine_similarity
                similarity_threshold: float = 0.95

                def transform_documents(
                    self, documents: Sequence[Document], **kwargs: Any
                ) -> Sequence[Document]:
                    stateful_documents = get_stateful_documents(documents)
                    embedded_documents = _get_embeddings_from_stateful_docs(
                        self.embeddings, stateful_documents
                    )
                    included_idxs = _filter_similar_embeddings(
                        embedded_documents, self.similarity_fn, self.similarity_threshold
                    )
                    return [stateful_documents[i] for i in sorted(included_idxs)]

                async def atransform_documents(
                    self, documents: Sequence[Document], **kwargs: Any
                ) -> Sequence[Document]:
                    raise NotImplementedError

    """

    @abstractmethod
    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        """Transform a list of documents.

        Args:
            documents: A sequence of Documents to be transformed.

        Returns:
            A list of transformed Documents.
        """

    @abstractmethod
    async def atransform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        """Asynchronously transform a list of documents.

        Args:
            documents: A sequence of Documents to be transformed.

        Returns:
            A list of transformed Documents.
        """


class ModelPropertyKey(Enum):
    """
    Enum class for model property key.
    """

    MODE = "mode"
    CONTEXT_SIZE = "context_size"
    MAX_CHUNKS = "max_chunks"
    FILE_UPLOAD_LIMIT = "file_upload_limit"
    SUPPORTED_FILE_EXTENSIONS = "supported_file_extensions"
    MAX_CHARACTERS_PER_CHUNK = "max_characters_per_chunk"
    DEFAULT_VOICE = "default_voice"
    VOICES = "voices"
    WORD_LIMIT = "word_limit"
    AUDIO_TYPE = "audio_type"
    MAX_WORKERS = "max_workers"


class RerankMode(StrEnum):
    RERANKING_MODEL = "reranking_model"
    WEIGHTED_SCORE = "weighted_score"
