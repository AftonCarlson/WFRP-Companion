from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from wfrp_companion.config import AppConfig


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        ...

    def embed_query(self, text: str) -> tuple[float, ...]:
        ...


class UnsupportedEmbeddingProviderError(ValueError):
    def __init__(self, provider_name: str) -> None:
        super().__init__(f"Unsupported embedding provider: {provider_name}")
        self.provider_name = provider_name


class EmbeddingProviderError(RuntimeError):
    pass


class EmbeddingProviderDependencyError(EmbeddingProviderError):
    pass


class EmbeddingProviderRuntimeError(EmbeddingProviderError):
    pass


class EmbeddingDimensionError(ValueError):
    pass


@dataclass(frozen=True)
class LocalHashEmbeddingProvider:
    provider_name: str
    model_name: str
    dimensions: int

    @classmethod
    def from_config(cls, config: AppConfig) -> LocalHashEmbeddingProvider:
        return cls(
            provider_name="local-hash",
            model_name=config.embedding_model,
            dimensions=config.embedding_dimensions,
        )

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        from wfrp_companion.source_objects.embeddings import text_embedding_vector

        return tuple(
            text_embedding_vector(text, dimensions=self.dimensions) for text in texts
        )

    def embed_query(self, text: str) -> tuple[float, ...]:
        from wfrp_companion.source_objects.embeddings import text_embedding_vector

        return text_embedding_vector(text, dimensions=self.dimensions)


_SENTENCE_TRANSFORMERS_MODEL_CACHE: dict[tuple[str, str | None, bool], object] = {}


@dataclass(frozen=True)
class SentenceTransformersEmbeddingProvider:
    provider_name: str
    model_name: str
    dimensions: int
    batch_size: int
    device: str | None
    query_prompt_name: str | None
    local_files_only: bool

    @classmethod
    def from_config(cls, config: AppConfig) -> SentenceTransformersEmbeddingProvider:
        return cls(
            provider_name="sentence-transformers",
            model_name=config.embedding_model,
            dimensions=config.embedding_dimensions,
            batch_size=config.embedding_batch_size,
            device=config.embedding_device,
            query_prompt_name=config.embedding_query_prompt_name,
            local_files_only=config.embedding_local_files_only,
        )

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        try:
            encoded = self._model().encode(
                tuple(texts),
                batch_size=self.batch_size,
                normalize_embeddings=True,
            )
            return tuple(
                self._validate_vector(vector) for vector in _coerce_vectors(encoded)
            )
        except (EmbeddingProviderError, EmbeddingDimensionError):
            raise
        except Exception as exc:
            raise EmbeddingProviderRuntimeError(
                f"Unable to encode documents with {self.model_name}"
            ) from exc

    def embed_query(self, text: str) -> tuple[float, ...]:
        kwargs: dict[str, object] = {
            "batch_size": 1,
            "normalize_embeddings": True,
        }
        if self.query_prompt_name is not None:
            kwargs["prompt_name"] = self.query_prompt_name
        try:
            encoded = self._model().encode(text, **kwargs)
            return self._validate_vector(_coerce_vector(encoded))
        except (EmbeddingProviderError, EmbeddingDimensionError):
            raise
        except Exception as exc:
            raise EmbeddingProviderRuntimeError(
                f"Unable to encode query with {self.model_name}"
            ) from exc

    def _model(self) -> object:
        cache_key = (self.model_name, self.device, self.local_files_only)
        if cache_key not in _SENTENCE_TRANSFORMERS_MODEL_CACHE:
            try:
                module = importlib.import_module("sentence_transformers")
            except ModuleNotFoundError as exc:
                raise EmbeddingProviderDependencyError(
                    "sentence-transformers is required for "
                    "WFRP_EMBEDDING_PROVIDER=sentence-transformers"
                ) from exc
            kwargs: dict[str, object] = {"local_files_only": self.local_files_only}
            if self.device is not None:
                kwargs["device"] = self.device
            try:
                _SENTENCE_TRANSFORMERS_MODEL_CACHE[cache_key] = (
                    module.SentenceTransformer(self.model_name, **kwargs)
                )
            except Exception as exc:
                raise EmbeddingProviderRuntimeError(
                    f"Unable to load sentence-transformers model {self.model_name}"
                ) from exc
        return _SENTENCE_TRANSFORMERS_MODEL_CACHE[cache_key]

    def _validate_vector(self, vector: tuple[float, ...]) -> tuple[float, ...]:
        if len(vector) != self.dimensions:
            raise EmbeddingDimensionError(
                f"{self.provider_name} model {self.model_name} expected "
                f"{self.dimensions} dimensions but returned {len(vector)}"
            )
        return vector


def _coerce_vectors(encoded: object) -> tuple[tuple[float, ...], ...]:
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    return tuple(_coerce_vector(vector) for vector in encoded)


def _coerce_vector(encoded: object) -> tuple[float, ...]:
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    return tuple(float(value) for value in encoded)


def resolve_embedding_provider(config: AppConfig) -> EmbeddingProvider | None:
    if config.embedding_provider == "disabled":
        return None
    if config.embedding_provider == "local-hash":
        return LocalHashEmbeddingProvider.from_config(config)
    if config.embedding_provider == "sentence-transformers":
        return SentenceTransformersEmbeddingProvider.from_config(config)
    raise UnsupportedEmbeddingProviderError(config.embedding_provider)
