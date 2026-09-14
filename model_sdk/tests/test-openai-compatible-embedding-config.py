from unittest.mock import patch

from model_sdk.models.openai_compatible.embedding import OpenAICompatibleEmbedding


def test_openai_compatible_embeddings_send_text_to_ollama_by_default():
    with patch(
        "model_sdk.models.openai_compatible.embedding.OpenAIEmbeddings"
    ) as embeddings:
        OpenAICompatibleEmbedding(
            provider="openai_compatible",
            model="bge-m3",
            base_url="http://ollama:11434/v1",
            api_key="test",
        )

    assert embeddings.call_args.kwargs["check_embedding_ctx_length"] is False


def test_explicit_context_length_setting_is_preserved():
    with patch(
        "model_sdk.models.openai_compatible.embedding.OpenAIEmbeddings"
    ) as embeddings:
        OpenAICompatibleEmbedding(
            provider="openai_compatible",
            check_embedding_ctx_length=True,
        )

    assert embeddings.call_args.kwargs["check_embedding_ctx_length"] is True
