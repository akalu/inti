"""
INTI - TAS (AI Agent Version) — Vector Memory Store (Hybrid Memory Layer 2)
========================================================
Semantic memory backed by ChromaDB + Gemini Embedding 2.

Provides:
  EmbeddingClient       — Gemini Embedding API wrapper (text + multimodal)
  VectorMemoryStore     — Drop-in semantic store with multimodal support
  VectorMemoryManager   — Manages ChromaDB collections for vector stores

Multimodal embedding (Gemini Embedding 2):
  Text     — up to 8,192 tokens
  Images   — PNG/JPEG, up to 6 per request
  Video    — MP4/MOV, up to 120 seconds
  Audio    — MP3/WAV, up to 80 seconds
  PDFs     — up to 6 pages

All modalities share the same embedding space, enabling
cross-modal search (e.g. find images by text query).

Ref: Phase 27 — Hybrid Memory System
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from core.messages import MemoryTier

logger = logging.getLogger("taas")


# ============================================================
# Media type constants
# ============================================================

class MediaType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    PDF = "pdf"


MIME_MAP = {
    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    # Video
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    # Documents
    ".pdf": "application/pdf",
}

# Max file sizes (bytes) for safety
MAX_FILE_SIZES = {
    MediaType.IMAGE: 20 * 1024 * 1024,   # 20MB per image
    MediaType.AUDIO: 50 * 1024 * 1024,   # 50MB for audio
    MediaType.VIDEO: 100 * 1024 * 1024,  # 100MB for video
    MediaType.PDF: 20 * 1024 * 1024,     # 20MB for PDF
}


def detect_media_type(file_path: Path) -> Optional[MediaType]:
    """Detect media type from file extension."""
    ext = file_path.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg"):
        return MediaType.IMAGE
    elif ext in (".mp3", ".wav"):
        return MediaType.AUDIO
    elif ext in (".mp4", ".mov"):
        return MediaType.VIDEO
    elif ext == ".pdf":
        return MediaType.PDF
    return None


def get_mime_type(file_path: Path) -> str:
    """Get MIME type from file extension."""
    return MIME_MAP.get(file_path.suffix.lower(), "application/octet-stream")


# ============================================================
# Embedding Client — Gemini Embedding 2 + fallback
# ============================================================

class EmbeddingClient:
    """
    Wraps the Gemini Embedding API with multimodal support.
    
    Primary model: gemini-embedding-2-preview (multimodal)
    Fallback: gemini-embedding-001 (text-only, no multimodal)
    
    Supports embedding:
      - Text (embed_text)
      - Images (embed_image)  — PNG/JPEG
      - Audio (embed_audio)   — MP3/WAV
      - Video (embed_video)   — MP4/MOV
      - PDFs (embed_pdf)
      - Mixed content (embed_multimodal) — aggregated embedding
    
    All modalities share the same vector space.
    """

    PRIMARY_MODEL = "gemini-embedding-2-preview"
    FALLBACK_MODEL = "gemini-embedding-001"
    DEFAULT_DIMS = 768  # MRL truncation for efficiency

    def __init__(
        self,
        api_key: str = "",
        dims: int = DEFAULT_DIMS,
        primary_model: str = PRIMARY_MODEL,
        fallback_model: str = FALLBACK_MODEL,
    ):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._dims = dims
        self._primary_model = primary_model
        self._fallback_model = fallback_model
        self._client = None
        self._active_model = primary_model
        self._call_count = 0
        self._fallback_active = False
        self._cache: dict[str, list[float]] = {}
        self._cache_max = 500
        self._lock = threading.Lock()

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string. Returns a vector of floats."""
        # Check cache first
        cache_key = hashlib.md5(text.encode()).hexdigest()
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        vector = self._call_api(text)

        # Cache the result
        with self._lock:
            if len(self._cache) >= self._cache_max:
                # Evict oldest half
                keys = list(self._cache.keys())
                for k in keys[:len(keys) // 2]:
                    del self._cache[k]
            self._cache[cache_key] = vector

        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single API call."""
        if not texts:
            return []

        # Check cache for each
        results: list[Optional[list[float]]] = []
        uncached_indices = []
        uncached_texts = []

        for i, text in enumerate(texts):
            cache_key = hashlib.md5(text.encode()).hexdigest()
            with self._lock:
                cached = self._cache.get(cache_key)
            if cached is not None:
                results.append(cached)
            else:
                results.append(None)
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Batch embed uncached texts
        if uncached_texts:
            vectors = self._call_api_batch(uncached_texts)
            for idx, vec in zip(uncached_indices, vectors):
                results[idx] = vec
                cache_key = hashlib.md5(uncached_texts[uncached_indices.index(idx)].encode()).hexdigest()
                with self._lock:
                    self._cache[cache_key] = vec

        return results  # type: ignore

    def _call_api(self, text: str) -> list[float]:
        """Call Gemini Embedding API with fallback."""
        from google.genai import types

        client = self._get_client()
        self._call_count += 1

        # Truncate very long texts to fit token limit
        truncated = text[:8000] if len(text) > 8000 else text

        try:
            result = client.models.embed_content(
                model=self._active_model,
                contents=truncated,
                config=types.EmbedContentConfig(
                    output_dimensionality=self._dims
                ),
            )
            return result.embeddings[0].values
        except Exception as e:
            if not self._fallback_active:
                logger.warning(
                    f"[VECTOR] Primary model {self._active_model} failed: {e}. "
                    f"Falling back to {self._fallback_model}"
                )
                self._active_model = self._fallback_model
                self._fallback_active = True
                return self._call_api(text)
            else:
                logger.error(f"[VECTOR] Embedding failed on fallback: {e}")
                # Return zero vector as last resort
                return [0.0] * self._dims

    def _call_api_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch embed via Gemini API."""
        from google.genai import types

        client = self._get_client()
        self._call_count += 1

        # Truncate long texts
        truncated = [t[:8000] for t in texts]

        try:
            result = client.models.embed_content(
                model=self._active_model,
                contents=truncated,
                config=types.EmbedContentConfig(
                    output_dimensionality=self._dims
                ),
            )
            return [emb.values for emb in result.embeddings]
        except Exception as e:
            if not self._fallback_active:
                logger.warning(
                    f"[VECTOR] Batch embedding failed on {self._active_model}: {e}. "
                    f"Falling back to {self._fallback_model}"
                )
                self._active_model = self._fallback_model
                self._fallback_active = True
                return self._call_api_batch(texts)
            else:
                logger.error(f"[VECTOR] Batch embedding failed on fallback: {e}")
                return [[0.0] * self._dims] * len(texts)

    @property
    def stats(self) -> dict:
        return {
            "active_model": self._active_model,
            "fallback_active": self._fallback_active,
            "call_count": self._call_count,
            "cache_size": len(self._cache),
            "multimodal": not self._fallback_active,
        }

    # ============================================================
    # Multimodal Embedding Methods
    # ============================================================

    def _embed_bytes(self, data: bytes, mime_type: str) -> list[float]:
        """
        Core method: embed raw bytes of any supported modality.
        Uses types.Part.from_bytes() — the unified Gemini Embedding 2 API.
        
        Falls back to zero vector if multimodal model is not available
        (fallback model gemini-embedding-001 is text-only).
        """
        from google.genai import types

        if self._fallback_active:
            logger.warning(
                "[VECTOR] Multimodal embedding unavailable (fallback model is text-only). "
                "Returning zero vector."
            )
            return [0.0] * self._dims

        client = self._get_client()
        self._call_count += 1

        try:
            result = client.models.embed_content(
                model=self._active_model,
                contents=[
                    types.Part.from_bytes(
                        data=data,
                        mime_type=mime_type,
                    ),
                ],
                config=types.EmbedContentConfig(
                    output_dimensionality=self._dims,
                ),
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error(f"[VECTOR] Multimodal embedding failed ({mime_type}): {e}")
            return [0.0] * self._dims

    def embed_image(self, image_path: str | Path) -> list[float]:
        """
        Embed an image file (PNG/JPEG).
        Returns a vector in the same space as text embeddings.
        """
        path = Path(image_path)
        if not path.exists():
            logger.error(f"[VECTOR] Image file not found: {path}")
            return [0.0] * self._dims

        # Cache by file hash
        file_hash = hashlib.md5(path.read_bytes()[:4096]).hexdigest() + "_img"
        with self._lock:
            if file_hash in self._cache:
                return self._cache[file_hash]

        data = path.read_bytes()
        mime = get_mime_type(path)
        vector = self._embed_bytes(data, mime)

        with self._lock:
            self._cache[file_hash] = vector
        return vector

    def embed_audio(self, audio_path: str | Path) -> list[float]:
        """
        Embed an audio file (MP3/WAV, up to 80 seconds).
        Returns a vector in the same space as text embeddings.
        """
        path = Path(audio_path)
        if not path.exists():
            logger.error(f"[VECTOR] Audio file not found: {path}")
            return [0.0] * self._dims

        file_hash = hashlib.md5(path.read_bytes()[:4096]).hexdigest() + "_aud"
        with self._lock:
            if file_hash in self._cache:
                return self._cache[file_hash]

        data = path.read_bytes()
        mime = get_mime_type(path)
        vector = self._embed_bytes(data, mime)

        with self._lock:
            self._cache[file_hash] = vector
        return vector

    def embed_video(self, video_path: str | Path) -> list[float]:
        """
        Embed a video file (MP4/MOV, up to 120 seconds).
        Returns a vector in the same space as text embeddings.
        """
        path = Path(video_path)
        if not path.exists():
            logger.error(f"[VECTOR] Video file not found: {path}")
            return [0.0] * self._dims

        file_hash = hashlib.md5(path.read_bytes()[:8192]).hexdigest() + "_vid"
        with self._lock:
            if file_hash in self._cache:
                return self._cache[file_hash]

        data = path.read_bytes()
        mime = get_mime_type(path)
        vector = self._embed_bytes(data, mime)

        with self._lock:
            self._cache[file_hash] = vector
        return vector

    def embed_pdf(self, pdf_path: str | Path) -> list[float]:
        """
        Embed a PDF document (up to 6 pages).
        Returns a vector in the same space as text embeddings.
        """
        path = Path(pdf_path)
        if not path.exists():
            logger.error(f"[VECTOR] PDF file not found: {path}")
            return [0.0] * self._dims

        file_hash = hashlib.md5(path.read_bytes()[:4096]).hexdigest() + "_pdf"
        with self._lock:
            if file_hash in self._cache:
                return self._cache[file_hash]

        data = path.read_bytes()
        vector = self._embed_bytes(data, "application/pdf")

        with self._lock:
            self._cache[file_hash] = vector
        return vector

    def embed_file(self, file_path: str | Path) -> tuple[list[float], MediaType]:
        """
        Auto-detect modality and embed any supported file.
        Returns (vector, media_type).
        """
        path = Path(file_path)
        media_type = detect_media_type(path)

        if media_type is None:
            logger.warning(f"[VECTOR] Unsupported file type: {path.suffix}")
            return [0.0] * self._dims, MediaType.TEXT

        if media_type == MediaType.IMAGE:
            return self.embed_image(path), media_type
        elif media_type == MediaType.AUDIO:
            return self.embed_audio(path), media_type
        elif media_type == MediaType.VIDEO:
            return self.embed_video(path), media_type
        elif media_type == MediaType.PDF:
            return self.embed_pdf(path), media_type
        return [0.0] * self._dims, MediaType.TEXT

    def embed_multimodal(
        self,
        text: str = "",
        image_path: str | Path | None = None,
        audio_path: str | Path | None = None,
    ) -> list[float]:
        """
        Create one aggregated embedding from text + image + audio.
        Uses Gemini's multi-part content to produce a single vector
        that captures the combined semantics.
        """
        from google.genai import types

        if self._fallback_active:
            # Fallback is text-only
            if text:
                return self._call_api(text)
            return [0.0] * self._dims

        parts = []
        if text:
            parts.append(types.Part(text=text))
        if image_path:
            p = Path(image_path)
            if p.exists():
                parts.append(types.Part.from_bytes(
                    data=p.read_bytes(), mime_type=get_mime_type(p),
                ))
        if audio_path:
            p = Path(audio_path)
            if p.exists():
                parts.append(types.Part.from_bytes(
                    data=p.read_bytes(), mime_type=get_mime_type(p),
                ))

        if not parts:
            return [0.0] * self._dims

        client = self._get_client()
        self._call_count += 1

        try:
            result = client.models.embed_content(
                model=self._active_model,
                contents=[
                    types.Content(parts=parts),
                ],
                config=types.EmbedContentConfig(
                    output_dimensionality=self._dims,
                ),
            )
            return result.embeddings[0].values
        except Exception as e:
            logger.error(f"[VECTOR] Multimodal aggregated embedding failed: {e}")
            # Fall back to text-only if available
            if text:
                return self._call_api(text)
            return [0.0] * self._dims


# ============================================================
# Vector Memory Store — ChromaDB-backed semantic store
# ============================================================

class VectorMemoryStore:
    """
    Semantic memory store backed by ChromaDB.
    
    Drop-in compatible with MemoryStore's access control model.
    Adds semantic search capability via query_semantic().
    
    Regular write(key, value) and read(key) still work for exact access.
    """

    def __init__(
        self,
        collection_name: str,
        tier: MemoryTier,
        owner: str,
        access_list: list[str] | None = None,
        embedding_client: Optional[EmbeddingClient] = None,
        chroma_client=None,
    ):
        self.tier = tier
        self.owner = owner
        self.access_list = access_list or []
        self.collection_name = collection_name
        self._embedding_client = embedding_client
        self._lock = threading.Lock()

        # ChromaDB collection
        if chroma_client is None:
            import chromadb
            chroma_client = chromadb.Client()

        self._collection = chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # In-memory index for key→id mapping and fast exact-key reads
        self._key_index: dict[str, str] = {}
        self._timestamps: dict[str, float] = {}
        self._rebuild_key_index()

    def _rebuild_key_index(self):
        """Rebuild the key→id index from ChromaDB metadata."""
        try:
            all_data = self._collection.get(include=["metadatas"])
            if all_data and all_data["ids"]:
                for doc_id, meta in zip(all_data["ids"], all_data["metadatas"]):
                    if meta and "key" in meta:
                        self._key_index[meta["key"]] = doc_id
                        self._timestamps[meta["key"]] = meta.get("timestamp", 0)
        except Exception as e:
            logger.warning(f"[VECTOR] Failed to rebuild key index for {self.collection_name}: {e}")

    def _check_access(self, requester: str, write: bool = False) -> bool:
        """Enforce access control rules (identical to MemoryStore)."""
        if self.tier == MemoryTier.ISOLATED:
            return requester == self.owner
        elif self.tier == MemoryTier.SHARED:
            if write:
                return requester == self.owner
            return requester == self.owner or requester in self.access_list
        elif self.tier == MemoryTier.GLOBAL:
            return True
        elif self.tier == MemoryTier.TRANSIENT:
            return requester == self.owner
        return False

    def _make_document_text(self, key: str, value: Any) -> str:
        """Convert a key-value pair to a text string for embedding."""
        if isinstance(value, dict):
            # Extract meaningful text from dict
            parts = [key]
            for k, v in value.items():
                if isinstance(v, str):
                    parts.append(f"{k}: {v}")
                elif isinstance(v, (list, dict)):
                    parts.append(f"{k}: {str(v)[:200]}")
                else:
                    parts.append(f"{k}: {v}")
            return "\n".join(parts)
        elif isinstance(value, str):
            return f"{key}: {value}"
        elif isinstance(value, list):
            items = [str(item)[:200] for item in value[:20]]
            return f"{key}: " + " | ".join(items)
        else:
            return f"{key}: {str(value)[:500]}"

    def write(self, key: str, value: Any, requester: str) -> bool:
        """Write data to the vector store. Auto-embeds for semantic search."""
        if not self._check_access(requester, write=True):
            return False

        with self._lock:
            doc_text = self._make_document_text(key, value)
            doc_id = f"{self.collection_name}_{hashlib.md5(key.encode()).hexdigest()[:12]}"
            ts = time.time()

            metadata = {
                "key": key,
                "timestamp": ts,
                "owner": self.owner,
                "requester": requester,
                "value_type": type(value).__name__,
                "media_type": MediaType.TEXT.value,
            }

            # Store the raw value as a JSON string in metadata for exact reads
            import json
            try:
                raw_json = json.dumps(value, default=str)[:10000]
                metadata["raw_value"] = raw_json
            except (TypeError, ValueError):
                metadata["raw_value"] = str(value)[:10000]

            # Embed and upsert
            if self._embedding_client:
                embedding = self._embedding_client.embed_text(doc_text)
                self._collection.upsert(
                    ids=[doc_id],
                    documents=[doc_text],
                    embeddings=[embedding],
                    metadatas=[metadata],
                )
            else:
                # No embedding client — use ChromaDB's default embedding
                self._collection.upsert(
                    ids=[doc_id],
                    documents=[doc_text],
                    metadatas=[metadata],
                )

            self._key_index[key] = doc_id
            self._timestamps[key] = ts

        return True

    def write_media(
        self,
        key: str,
        file_path: str | Path,
        requester: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> bool:
        """
        Store a media file (image, audio, video, PDF) in the vector store.
        
        The file itself is NOT stored in ChromaDB — only its embedding
        and metadata (including the file path for retrieval).
        
        Args:
            key: unique identifier for this media
            file_path: path to the media file
            requester: who is writing
            description: text description (improves search quality)
            tags: optional tags for filtering
        """
        if not self._check_access(requester, write=True):
            return False

        path = Path(file_path)
        if not path.exists():
            logger.error(f"[VECTOR] Media file not found: {path}")
            return False

        media_type = detect_media_type(path)
        if media_type is None:
            logger.error(f"[VECTOR] Unsupported media type: {path.suffix}")
            return False

        # Check file size
        max_size = MAX_FILE_SIZES.get(media_type, 20 * 1024 * 1024)
        if path.stat().st_size > max_size:
            logger.error(
                f"[VECTOR] File too large: {path.stat().st_size} bytes "
                f"(max {max_size} for {media_type.value})"
            )
            return False

        if not self._embedding_client:
            logger.error("[VECTOR] No embedding client — cannot embed media")
            return False

        with self._lock:
            doc_id = f"{self.collection_name}_{hashlib.md5(key.encode()).hexdigest()[:12]}"
            ts = time.time()

            # Create document text for search context
            doc_parts = [f"{key} [{media_type.value}]"]
            if description:
                doc_parts.append(description)
            if tags:
                doc_parts.append(f"tags: {', '.join(tags)}")
            doc_parts.append(f"file: {path.name}")
            doc_text = "\n".join(doc_parts)

            # Embed the media file
            if description:
                # Aggregated embedding: media + text description
                if media_type == MediaType.IMAGE:
                    embedding = self._embedding_client.embed_multimodal(
                        text=description, image_path=path,
                    )
                elif media_type == MediaType.AUDIO:
                    embedding = self._embedding_client.embed_multimodal(
                        text=description, audio_path=path,
                    )
                else:
                    # Video/PDF: embed file directly (no aggregation API for these)
                    embedding, _ = self._embedding_client.embed_file(path)
            else:
                embedding, _ = self._embedding_client.embed_file(path)

            import json
            metadata = {
                "key": key,
                "timestamp": ts,
                "owner": self.owner,
                "requester": requester,
                "media_type": media_type.value,
                "file_path": str(path.resolve()),
                "file_name": path.name,
                "file_size": path.stat().st_size,
                "mime_type": get_mime_type(path),
                "description": description[:500],
                "tags": json.dumps(tags or []),
                "value_type": "media",
                "raw_value": json.dumps({
                    "file_path": str(path.resolve()),
                    "media_type": media_type.value,
                    "description": description,
                    "tags": tags or [],
                }),
            }

            self._collection.upsert(
                ids=[doc_id],
                documents=[doc_text],
                embeddings=[embedding],
                metadatas=[metadata],
            )

            self._key_index[key] = doc_id
            self._timestamps[key] = ts

        logger.info(
            f"[VECTOR] Stored {media_type.value}: {key} → {path.name}"
        )
        return True

    def read(self, key: str, requester: str) -> tuple[bool, Any]:
        """Read data by exact key. Returns (success, value)."""
        if not self._check_access(requester, write=False):
            return False, None

        with self._lock:
            doc_id = self._key_index.get(key)
            if doc_id is None:
                return False, None

            try:
                result = self._collection.get(
                    ids=[doc_id],
                    include=["metadatas"],
                )
                if result and result["metadatas"] and result["metadatas"][0]:
                    raw = result["metadatas"][0].get("raw_value")
                    if raw:
                        import json
                        try:
                            return True, json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            return True, raw
                return False, None
            except Exception as e:
                logger.warning(f"[VECTOR] Read failed for {key}: {e}")
                return False, None

    def read_all(self, requester: str) -> tuple[bool, dict]:
        """Read all data. Returns (success, {key: value})."""
        if not self._check_access(requester, write=False):
            return False, {}

        result = {}
        try:
            all_data = self._collection.get(include=["metadatas"])
            if all_data and all_data["metadatas"]:
                import json
                for meta in all_data["metadatas"]:
                    if meta and "key" in meta:
                        raw = meta.get("raw_value", "")
                        try:
                            result[meta["key"]] = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            result[meta["key"]] = raw
        except Exception as e:
            logger.warning(f"[VECTOR] read_all failed: {e}")
        return True, result

    def query_semantic(
        self,
        query: str,
        requester: str,
        top_k: int = 5,
        min_score: float = 0.0,
        media_filter: MediaType | None = None,
    ) -> list[dict]:
        """
        Semantic search across stored data (text + multimodal).
        
        Args:
            query: text query (searches across all modalities)
            requester: who is querying
            top_k: max results
            min_score: minimum similarity threshold
            media_filter: optional, filter by MediaType (IMAGE, AUDIO, etc.)
        
        Returns list of dicts with:
          - key: the original key
          - value: the stored value (incl. file_path for media)
          - score: similarity score (0-1, higher = more similar)
          - document: the text representation
          - media_type: 'text', 'image', 'audio', 'video', 'pdf'
        """
        if not self._check_access(requester, write=False):
            return []

        try:
            # Build where_filter for media type
            where_filter = None
            if media_filter:
                where_filter = {"media_type": media_filter.value}

            count = self._collection.count() or 0
            if count == 0:
                return []

            if self._embedding_client:
                query_embedding = self._embedding_client.embed_text(query)
                results = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(top_k, count),
                    include=["metadatas", "documents", "distances"],
                    where=where_filter,
                )
            else:
                results = self._collection.query(
                    query_texts=[query],
                    n_results=min(top_k, count),
                    include=["metadatas", "documents", "distances"],
                    where=where_filter,
                )

            if not results or not results["ids"] or not results["ids"][0]:
                return []

            import json
            output = []
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                doc = results["documents"][0][i] if results["documents"] else ""
                # ChromaDB cosine distance: 0 = identical, 2 = opposite
                # Convert to similarity: 1 - (distance/2)
                distance = results["distances"][0][i] if results["distances"] else 1.0
                score = 1.0 - (distance / 2.0)

                if score < min_score:
                    continue

                raw = meta.get("raw_value", "")
                try:
                    value = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    value = raw

                output.append({
                    "key": meta.get("key", doc_id),
                    "value": value,
                    "score": round(score, 4),
                    "document": doc,
                    "media_type": meta.get("media_type", "text"),
                    "file_path": meta.get("file_path", ""),
                    "timestamp": meta.get("timestamp", 0),
                })

            return output

        except Exception as e:
            logger.warning(f"[VECTOR] Semantic query failed: {e}")
            return []

    def query_by_image(
        self,
        image_path: str | Path,
        requester: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        Search using an image as the query.
        Finds semantically similar content across ALL modalities.
        """
        if not self._check_access(requester, write=False):
            return []
        if not self._embedding_client:
            return []

        try:
            query_embedding = self._embedding_client.embed_image(image_path)
            count = self._collection.count() or 0
            if count == 0:
                return []

            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, count),
                include=["metadatas", "documents", "distances"],
            )
            return self._parse_query_results(results, min_score)
        except Exception as e:
            logger.warning(f"[VECTOR] Image query failed: {e}")
            return []

    def query_by_audio(
        self,
        audio_path: str | Path,
        requester: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        Search using an audio file as the query.
        Finds semantically similar content across ALL modalities.
        """
        if not self._check_access(requester, write=False):
            return []
        if not self._embedding_client:
            return []

        try:
            query_embedding = self._embedding_client.embed_audio(audio_path)
            count = self._collection.count() or 0
            if count == 0:
                return []

            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, count),
                include=["metadatas", "documents", "distances"],
            )
            return self._parse_query_results(results, min_score)
        except Exception as e:
            logger.warning(f"[VECTOR] Audio query failed: {e}")
            return []

    def _parse_query_results(self, results: dict, min_score: float = 0.0) -> list[dict]:
        """Parse ChromaDB query results into standardized output."""
        if not results or not results["ids"] or not results["ids"][0]:
            return []

        import json
        output = []
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            doc = results["documents"][0][i] if results["documents"] else ""
            distance = results["distances"][0][i] if results["distances"] else 1.0
            score = 1.0 - (distance / 2.0)

            if score < min_score:
                continue

            raw = meta.get("raw_value", "")
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                value = raw

            output.append({
                "key": meta.get("key", doc_id),
                "value": value,
                "score": round(score, 4),
                "document": doc,
                "media_type": meta.get("media_type", "text"),
                "file_path": meta.get("file_path", ""),
                "timestamp": meta.get("timestamp", 0),
            })
        return output

    def delete(self, key: str, requester: str) -> bool:
        """Delete a key from the store."""
        if not self._check_access(requester, write=True):
            return False

        with self._lock:
            doc_id = self._key_index.pop(key, None)
            self._timestamps.pop(key, None)
            if doc_id:
                try:
                    self._collection.delete(ids=[doc_id])
                    return True
                except Exception as e:
                    logger.warning(f"[VECTOR] Delete failed for {key}: {e}")
        return False

    def clear(self, requester: str) -> bool:
        """Clear all data in this collection."""
        if not self._check_access(requester, write=True):
            return False

        with self._lock:
            try:
                # Delete all IDs
                all_data = self._collection.get()
                if all_data and all_data["ids"]:
                    self._collection.delete(ids=all_data["ids"])
                self._key_index.clear()
                self._timestamps.clear()
                return True
            except Exception as e:
                logger.warning(f"[VECTOR] Clear failed: {e}")
                return False

    @property
    def size(self) -> int:
        try:
            return self._collection.count()
        except Exception:
            return 0

    def keys(self) -> list[str]:
        return list(self._key_index.keys())


# ============================================================
# Vector Memory Manager — Factory for creating vector stores
# ============================================================

class VectorMemoryManager:
    """
    Manages ChromaDB client and EmbeddingClient lifecycle.
    Creates VectorMemoryStore instances for the MemoryManager.
    """

    def __init__(
        self,
        persist_directory: str = "data/chromadb",
        api_key: str = "",
        embedding_dims: int = 768,
    ):
        self._persist_dir = persist_directory
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._dims = embedding_dims

        # Initialize ChromaDB with disk persistence
        import chromadb
        os.makedirs(persist_directory, exist_ok=True)
        self._chroma_client = chromadb.PersistentClient(
            path=persist_directory,
        )

        # Initialize Gemini Embedding client
        self._embedding_client = EmbeddingClient(
            api_key=self._api_key,
            dims=self._dims,
        )

        logger.info(
            f"[VECTOR] VectorMemoryManager initialized. "
            f"ChromaDB path: {persist_directory}, "
            f"Embedding model: {self._embedding_client._active_model}, "
            f"Dimensions: {self._dims}"
        )

    def create_store(
        self,
        collection_name: str,
        tier: MemoryTier,
        owner: str,
        access_list: list[str] | None = None,
    ) -> VectorMemoryStore:
        """Create a new VectorMemoryStore backed by a ChromaDB collection."""
        return VectorMemoryStore(
            collection_name=collection_name,
            tier=tier,
            owner=owner,
            access_list=access_list,
            embedding_client=self._embedding_client,
            chroma_client=self._chroma_client,
        )

    @property
    def embedding_client(self) -> EmbeddingClient:
        return self._embedding_client

    @property
    def stats(self) -> dict:
        """Get stats about the vector memory system."""
        return {
            "persist_directory": self._persist_dir,
            "embedding": self._embedding_client.stats,
            "collections": [
                col.name for col in self._chroma_client.list_collections()
            ],
        }
