"""Embedding service — mocked Cohere path + local TF-IDF fallback."""
from unittest.mock import patch

import numpy as np

from services import embedding_service


def test_local_embed_shape_and_norm():
    with patch.object(embedding_service, "_use_bedrock", return_value=False):
        matrix = embedding_service.embed_texts(["Customer Name", "KUNNR customer number"])
    assert matrix.shape[0] == 2
    assert matrix.shape[1] > 1
    norms = np.linalg.norm(matrix, axis=1)
    np.testing.assert_allclose(norms, np.ones(2), atol=1e-5)


def test_local_empty_list():
    with patch.object(embedding_service, "_use_bedrock", return_value=False):
        matrix = embedding_service.embed_texts([])
    assert matrix.shape == (0, 0)


@patch.object(embedding_service, "_use_bedrock", return_value=True)
@patch.object(embedding_service, "_has_bedrock_api_key", return_value=True)
@patch.object(embedding_service, "_invoke_embed_via_api_key")
def test_cohere_parses_float_dict(mock_invoke, _key, _use):
    mock_invoke.return_value = {
        "embeddings": {"float": [[1.0, 0.0], [0.0, 1.0]]},
    }
    matrix = embedding_service.embed_texts(["a", "b"])
    assert matrix.shape == (2, 2)
    mock_invoke.assert_called_once()
    norms = np.linalg.norm(matrix, axis=1)
    np.testing.assert_allclose(norms, np.ones(2), atol=1e-5)


def test_vectors_from_response_list_form():
    data = {"embeddings": [[0.1, 0.2], [0.3, 0.4]]}
    assert embedding_service._vectors_from_response(data) == [[0.1, 0.2], [0.3, 0.4]]
