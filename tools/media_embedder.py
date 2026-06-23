"""
INTI - TAS (AI Agent Version) — Multimodal Media Embedder Tool
=============================================
Embeds videos, images, audio, text, and PDFs into a unified
ChromaDB vector space using Gemini Embedding 2 Preview.

Three actions:
  embed   — Chunk & embed a media file into ChromaDB
  search  — Semantic search across all embedded media (free, local)
  analyze — Hybrid: search + send relevant chunk to Gemini for detailed analysis
            Returns precise timestamps and answers complex visual/audio questions

Dependencies:
  - google-genai >= 1.70.0  (embed_content + Files API)
  - chromadb                (vector storage)
  - imageio-ffmpeg          (bundles ffmpeg for video/audio chunking)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# ── Config ──────────────────────────────────────────────────
EMBEDDING_MODEL = "gemini-embedding-2-preview"
ANALYSIS_MODEL = "gemini-2.5-flash"
CHUNK_DURATION_S = 60       # seconds per video/audio chunk
CHUNK_OVERLAP_S = 5         # overlap between chunks
COLLECTION_NAME = "multimodal_knowledge"
CHROMADB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chromadb_multimodal")

# Supported media types
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".py", ".js", ".html"}
PDF_EXTS = {".pdf"}


def _get_ffmpeg_exe() -> str:
    """Get the path to the ffmpeg executable."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"  # Fallback to system ffmpeg


def _get_media_duration(filepath: str) -> float:
    """Get duration of a media file in seconds using ffmpeg."""
    ffmpeg_exe = _get_ffmpeg_exe()

    try:
        # Use ffmpeg -i (works without ffprobe)
        result = subprocess.run(
            [ffmpeg_exe, "-i", filepath],
            capture_output=True, text=True, timeout=30,
        )
        # Duration is in stderr for ffmpeg -i
        output = result.stderr
        import re
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", output)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            return hours * 3600 + minutes * 60 + seconds
        return 0.0
    except Exception as e:
        logger.warning(f"[MEDIA] Could not get duration for {filepath}: {e}")
        return 0.0


def _chunk_media(filepath: str, chunk_dir: str) -> list[dict]:
    """
    Split a video/audio file into chunks using ffmpeg.
    Returns list of {path, start_sec, end_sec, timestamp}.
    """
    duration = _get_media_duration(filepath)
    if duration <= 0:
        return [{"path": filepath, "start_sec": 0, "end_sec": 0, "timestamp": "0:00"}]

    ffmpeg_exe = _get_ffmpeg_exe()
    ext = Path(filepath).suffix
    chunks = []
    start = 0

    while start < duration:
        end = min(start + CHUNK_DURATION_S, duration)
        chunk_name = f"chunk_{start:04d}_{int(end):04d}{ext}"
        chunk_path = os.path.join(chunk_dir, chunk_name)

        cmd = [
            ffmpeg_exe, "-y", "-i", filepath,
            "-ss", str(start), "-t", str(end - start),
            "-c", "copy",  # Fast: no re-encoding
            chunk_path,
        ]

        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
            if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 0:
                start_ts = f"{int(start // 60)}:{int(start % 60):02d}"
                end_ts = f"{int(end // 60)}:{int(end % 60):02d}"
                chunks.append({
                    "path": chunk_path,
                    "start_sec": start,
                    "end_sec": end,
                    "timestamp": f"{start_ts}-{end_ts}",
                })
        except Exception as e:
            logger.warning(f"[MEDIA] Chunk failed at {start}s: {e}")

        start += CHUNK_DURATION_S - CHUNK_OVERLAP_S

    return chunks if chunks else [{"path": filepath, "start_sec": 0, "end_sec": 0, "timestamp": "full"}]


class MediaEmbedderTool(Tool):
    """
    Embed and search multimedia files using Gemini Embedding 2.

    embed   — Vectorize a file into ChromaDB (video/image/audio/text/PDF)
    search  — Semantic search across all embedded media (~free, local)
    analyze — Search + send relevant chunk to Gemini for detailed analysis
    """

    name = "media_embedder"
    description = (
        "Embed and search multimedia files (video, image, audio, text, PDF) "
        "using Gemini Embedding 2 Preview. "
        "Actions: embed (vectorize a file into ChromaDB), "
        "search (find relevant media by query), "
        "analyze (search + detailed AI analysis of the matching chunk). "
        "Analyze returns exact timestamps, visual details, and spoken content."
    )
    category = ToolCategory.UTILITY
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParam("action", "One of: embed, search, analyze", "string", True),
        ToolParam("path", "File path to embed (for 'embed' action)", "string", False),
        ToolParam("query", "Search query text (for 'search' and 'analyze' actions)", "string", False),
        ToolParam("top_k", "Number of results to return (default: 5)", "int", False, 5),
    ]

    def __init__(self):
        self._client = None
        self._chroma_collection = None

    def _get_client(self):
        """Lazy init Gemini client."""
        if self._client is None:
            from google import genai
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("DEFAULT_LLM_API_KEY")
            if not api_key:
                raise ValueError("No API key found (GEMINI_API_KEY or DEFAULT_LLM_API_KEY)")
            self._client = genai.Client(api_key=api_key)
        return self._client

    def _get_collection(self):
        """Lazy init ChromaDB persistent collection."""
        if self._chroma_collection is None:
            import chromadb
            os.makedirs(CHROMADB_PATH, exist_ok=True)
            chroma_client = chromadb.PersistentClient(path=CHROMADB_PATH)
            self._chroma_collection = chroma_client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"[MEDIA] ChromaDB collection '{COLLECTION_NAME}' at {CHROMADB_PATH}")
        return self._chroma_collection

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").lower()

        if action == "embed":
            return await self._embed(kwargs)
        elif action == "search":
            return await self._search(kwargs)
        elif action == "analyze":
            return await self._analyze(kwargs)
        else:
            return ToolResult(
                success=False,
                error=f"Unknown action: {action}. Use: embed, search, analyze",
            )

    # ────────────────────────────────────────────────────────────
    # EMBED — Vectorize a file into ChromaDB
    # ────────────────────────────────────────────────────────────

    async def _embed(self, kwargs: dict) -> ToolResult:
        filepath = kwargs.get("path", "").strip()
        if not filepath or not os.path.exists(filepath):
            return ToolResult(success=False, error=f"File not found: {filepath}")

        ext = Path(filepath).suffix.lower()
        filename = Path(filepath).name
        file_type = self._classify_file(ext)

        if not file_type:
            return ToolResult(
                success=False,
                error=f"Unsupported file type: {ext}. Supported: video, image, audio, text, PDF",
            )

        try:
            client = self._get_client()
            collection = self._get_collection()
            from google.genai import types

            embedded_count = 0

            if file_type in ("video", "audio"):
                # Chunk and embed each segment
                with tempfile.TemporaryDirectory(prefix="kronos_media_") as chunk_dir:
                    logger.info(f"[MEDIA] Chunking {file_type}: {filename}")
                    chunks = _chunk_media(filepath, chunk_dir)
                    logger.info(f"[MEDIA] Split into {len(chunks)} chunks")

                    for i, chunk in enumerate(chunks):
                        embedding = self._embed_file(
                            client, chunk["path"], file_type, types
                        )
                        if embedding:
                            doc_id = f"{filename}_chunk_{i}_{uuid.uuid4().hex[:8]}"
                            collection.add(
                                ids=[doc_id],
                                embeddings=[embedding],
                                metadatas=[{
                                    "file": filename,
                                    "file_path": filepath,
                                    "type": file_type,
                                    "chunk_index": i,
                                    "start_sec": chunk["start_sec"],
                                    "end_sec": chunk["end_sec"],
                                    "timestamp": chunk["timestamp"],
                                    "chunk_path": chunk["path"],
                                }],
                                documents=[
                                    f"{file_type} chunk {i} of {filename} "
                                    f"({chunk['timestamp']})"
                                ],
                            )
                            embedded_count += 1
                            logger.info(
                                f"[MEDIA] Embedded chunk {i + 1}/{len(chunks)}: "
                                f"{chunk['timestamp']}"
                            )

            elif file_type == "image":
                embedding = self._embed_file(client, filepath, file_type, types)
                if embedding:
                    doc_id = f"{filename}_{uuid.uuid4().hex[:8]}"
                    collection.add(
                        ids=[doc_id],
                        embeddings=[embedding],
                        metadatas=[{
                            "file": filename,
                            "file_path": filepath,
                            "type": file_type,
                            "start_sec": 0,
                            "end_sec": 0,
                            "timestamp": "image",
                        }],
                        documents=[f"Image: {filename}"],
                    )
                    embedded_count = 1

            elif file_type == "text":
                # Read and chunk text
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()

                # Chunk text into ~500 char segments
                chunk_size = 500
                text_chunks = [
                    text[i:i + chunk_size]
                    for i in range(0, len(text), chunk_size - 50)  # 50 char overlap
                ]

                for i, chunk_text in enumerate(text_chunks):
                    if not chunk_text.strip():
                        continue
                    embedding = self._embed_text(client, chunk_text, types)
                    if embedding:
                        doc_id = f"{filename}_text_{i}_{uuid.uuid4().hex[:8]}"
                        collection.add(
                            ids=[doc_id],
                            embeddings=[embedding],
                            metadatas=[{
                                "file": filename,
                                "file_path": filepath,
                                "type": "text",
                                "chunk_index": i,
                                "start_sec": 0,
                                "end_sec": 0,
                                "timestamp": f"chars {i * (chunk_size - 50)}-{i * (chunk_size - 50) + len(chunk_text)}",
                            }],
                            documents=[chunk_text[:200]],
                        )
                        embedded_count += 1

            elif file_type == "pdf":
                embedding = self._embed_file(client, filepath, file_type, types)
                if embedding:
                    doc_id = f"{filename}_{uuid.uuid4().hex[:8]}"
                    collection.add(
                        ids=[doc_id],
                        embeddings=[embedding],
                        metadatas=[{
                            "file": filename,
                            "file_path": filepath,
                            "type": "pdf",
                            "start_sec": 0,
                            "end_sec": 0,
                            "timestamp": "document",
                        }],
                        documents=[f"PDF: {filename}"],
                    )
                    embedded_count = 1

            total = collection.count()
            return ToolResult(
                success=True,
                output={
                    "status": f"Embedded {embedded_count} chunks from {filename}",
                    "file": filename,
                    "type": file_type,
                    "chunks_embedded": embedded_count,
                    "total_in_collection": total,
                },
            )

        except Exception as e:
            logger.error(f"[MEDIA] Embed error: {e}")
            return ToolResult(success=False, error=f"Embed failed: {e}")

    def _embed_file(self, client, filepath: str, file_type: str, types) -> list[float] | None:
        """Embed a single file via Gemini Embedding 2 Files API."""
        try:
            # Upload file to Files API
            uploaded = client.files.upload(file=filepath)

            # Wait for processing
            retries = 0
            while uploaded.state and uploaded.state.name == "PROCESSING" and retries < 30:
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
                retries += 1

            # Generate embedding
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_uri(
                                file_uri=uploaded.uri,
                                mime_type=uploaded.mime_type,
                            )
                        ]
                    )
                ],
            )

            # Cleanup uploaded file
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

            if response.embeddings:
                return list(response.embeddings[0].values)
            return None

        except Exception as e:
            # Retry on rate limit
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                for retry in range(3):
                    wait = 5 * (retry + 1)
                    logger.warning(f"[MEDIA] Rate limited, retry {retry+1}/3 in {wait}s...")
                    time.sleep(wait)
                    try:
                        uploaded = client.files.upload(file=filepath)
                        retries_inner = 0
                        while uploaded.state and uploaded.state.name == "PROCESSING" and retries_inner < 30:
                            time.sleep(2)
                            uploaded = client.files.get(name=uploaded.name)
                            retries_inner += 1
                        response = client.models.embed_content(
                            model=EMBEDDING_MODEL,
                            contents=[types.Content(parts=[types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type)])],
                        )
                        try:
                            client.files.delete(name=uploaded.name)
                        except Exception:
                            pass
                        if response.embeddings:
                            return list(response.embeddings[0].values)
                    except Exception:
                        continue
            logger.error(f"[MEDIA] File embedding failed for {filepath}: {e}")
            return None

    def _embed_text(self, client, text: str, types) -> list[float] | None:
        """Embed text content via Gemini Embedding 2 with retry on rate limit."""
        for attempt in range(4):  # 1 initial + 3 retries
            try:
                response = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=[text],
                )
                if response.embeddings:
                    return list(response.embeddings[0].values)
                return None
            except Exception as e:
                if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < 3:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"[MEDIA] Text embed rate limited, retry {attempt+1}/3 in {wait}s...")
                    time.sleep(wait)
                    continue
                logger.error(f"[MEDIA] Text embedding failed: {e}")
                return None
        return None


    # ────────────────────────────────────────────────────────────
    # SEARCH — Semantic search across all media (free, local)
    # ────────────────────────────────────────────────────────────

    async def _search(self, kwargs: dict) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Missing 'query' parameter")

        top_k = min(kwargs.get("top_k", 5), 20)

        try:
            client = self._get_client()
            collection = self._get_collection()
            from google.genai import types

            # Embed query text
            query_embedding = self._embed_text(client, query, types)
            if not query_embedding:
                return ToolResult(success=False, error="Failed to embed query")

            # Search ChromaDB
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["metadatas", "documents", "distances"],
            )

            if not results["ids"] or not results["ids"][0]:
                return ToolResult(
                    success=True,
                    output={"message": "No results found", "results": []},
                )

            # Format results
            search_results = []
            for i, doc_id in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i]
                distance = results["distances"][0][i]
                score = max(0, 1 - distance)  # cosine distance → similarity

                search_results.append({
                    "file": meta.get("file", "unknown"),
                    "type": meta.get("type", "unknown"),
                    "timestamp": meta.get("timestamp", ""),
                    "start_sec": meta.get("start_sec", 0),
                    "end_sec": meta.get("end_sec", 0),
                    "score": round(score, 3),
                    "preview": results["documents"][0][i][:200] if results["documents"][0] else "",
                })

            return ToolResult(
                success=True,
                output={
                    "query": query,
                    "results_count": len(search_results),
                    "results": search_results,
                },
            )

        except Exception as e:
            logger.error(f"[MEDIA] Search error: {e}")
            return ToolResult(success=False, error=f"Search failed: {e}")

    # ────────────────────────────────────────────────────────────
    # ANALYZE — Hybrid: search + Gemini analysis for timestamps
    # ────────────────────────────────────────────────────────────

    async def _analyze(self, kwargs: dict) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Missing 'query' parameter")

        # Stage 1: Search (free)
        search_result = await self._search(kwargs)
        if not search_result.success:
            return search_result

        results = search_result.output.get("results", [])
        if not results:
            return ToolResult(
                success=True,
                output={"message": "No relevant media found for analysis", "results": []},
            )

        # Stage 2: Analyze top result with Gemini Flash
        top = results[0]
        file_type = top.get("type", "")
        file_path = None

        # Find the original file path from ChromaDB metadata
        try:
            collection = self._get_collection()
            # Re-query to get file_path metadata
            all_results = collection.query(
                query_embeddings=[self._embed_text(
                    self._get_client(), query,
                    __import__("google.genai.types", fromlist=["types"])
                )],
                n_results=1,
                include=["metadatas"],
            )
            if all_results["metadatas"] and all_results["metadatas"][0]:
                meta = all_results["metadatas"][0][0]
                file_path = meta.get("file_path") or meta.get("chunk_path")
        except Exception:
            pass

        if not file_path or not os.path.exists(file_path):
            # Return search-only results if we can't find the file for analysis
            return ToolResult(
                success=True,
                output={
                    "query": query,
                    "search_results": results,
                    "analysis": "File not available for detailed analysis. Use search results above.",
                },
            )

        try:
            client = self._get_client()
            from google.genai import types
            from google.genai.types import Content, Part

            # Upload file for analysis
            uploaded = client.files.upload(file=file_path)
            retries = 0
            while uploaded.state and uploaded.state.name == "PROCESSING" and retries < 30:
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
                retries += 1

            # Ask Gemini to analyze with timestamp precision
            analysis_prompt = (
                f"Analyze this {file_type} and answer the following question precisely.\n"
                f"Question: {query}\n\n"
                f"IMPORTANT: Provide your answer with specific timestamps "
                f"(e.g., 'at 0:23', 'from 0:15 to 0:30'). "
                f"Describe exactly what you see/hear at those moments. "
                f"If it's an image, describe what you see in detail.\n"
                f"Source file: {top.get('file', 'unknown')}\n"
                f"Time range of this segment: {top.get('timestamp', 'unknown')}"
            )

            response = client.models.generate_content(
                model=ANALYSIS_MODEL,
                contents=[
                    Content(
                        role="user",
                        parts=[
                            Part.from_uri(
                                file_uri=uploaded.uri,
                                mime_type=uploaded.mime_type,
                            ),
                            Part(text=analysis_prompt),
                        ],
                    )
                ],
            )

            # Cleanup
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

            analysis_text = response.text if response.text else "Analysis completed but no text returned."

            return ToolResult(
                success=True,
                output={
                    "query": query,
                    "source_file": top.get("file", "unknown"),
                    "source_type": file_type,
                    "source_timestamp": top.get("timestamp", ""),
                    "analysis": analysis_text,
                    "score": top.get("score", 0),
                    "all_results": results[:3],  # Top 3 for context
                },
            )

        except Exception as e:
            logger.error(f"[MEDIA] Analysis error: {e}")
            return ToolResult(
                success=True,
                output={
                    "query": query,
                    "search_results": results,
                    "analysis_error": str(e),
                },
            )

    # ────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────

    def _classify_file(self, ext: str) -> str | None:
        ext = ext.lower()
        if ext in VIDEO_EXTS:
            return "video"
        if ext in AUDIO_EXTS:
            return "audio"
        if ext in IMAGE_EXTS:
            return "image"
        if ext in TEXT_EXTS:
            return "text"
        if ext in PDF_EXTS:
            return "pdf"
        return None
