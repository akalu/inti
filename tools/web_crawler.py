"""
INTI - TAS (AI Agent Version) — Web Crawler Tool (Crawl4AI)
==========================================
LLM-optimized web content extraction via Crawl4AI.

Replaces the basic BeautifulSoup web_browser.py with a modern pipeline:
  1. AsyncWebCrawler renders JavaScript (Playwright under the hood)
  2. Converts HTML → clean Markdown (strips nav, ads, scripts, CSS)
  3. Optional: chunks the Markdown and embeds into VectorMemoryStore
     for semantic search (RAG) instead of burning tokens every query.

Actions:
  crawl       — single page → clean Markdown
  deep_crawl  — follow internal links (up to max_pages)
  crawl_embed — crawl + chunk + embed into vector store for RAG

Risk: LOW — read-only web content extraction.

Install: pip install crawl4ai
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# Defaults
MAX_CONTENT_CHARS = 15_000   # Max chars to return (saves tokens)
MAX_PAGES = 5                # Max pages for deep_crawl
CHUNK_SIZE = 800             # Characters per chunk for embedding
CHUNK_OVERLAP = 100          # Overlap between chunks


class WebCrawlerTool(Tool):
    """
    Crawl web pages and extract LLM-ready Markdown content.

    Uses Crawl4AI's AsyncWebCrawler which:
    - Renders JavaScript (Playwright)
    - Strips navigation, ads, footers, scripts, CSS
    - Outputs clean Markdown optimized for LLM consumption
    - Reduces token usage by ~60-70% vs raw HTML
    """

    name = "web_crawler"
    description = (
        "Crawl web pages and extract clean, LLM-ready Markdown content. "
        "Renders JavaScript, strips noise (nav, ads, scripts), outputs "
        "optimized Markdown. Actions: crawl (single page), deep_crawl "
        "(follow links), crawl_embed (crawl + store as embeddings for "
        "semantic search). Saves ~60-70% tokens vs raw HTML."
    )
    category = ToolCategory.BROWSER
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParam("action", "One of: crawl, deep_crawl, crawl_embed", "string", True),
        ToolParam("url", "URL to crawl", "string", True),
        ToolParam("max_chars", f"Max chars to return (default {MAX_CONTENT_CHARS})", "int", False, MAX_CONTENT_CHARS),
        ToolParam("max_pages", f"Max pages for deep_crawl (default {MAX_PAGES})", "int", False, MAX_PAGES),
        ToolParam("collection", "Vector store collection name for crawl_embed", "string", False, "web_knowledge"),
        ToolParam("query", "Semantic query to search embedded content", "string", False),
        ToolParam("wait_for", "CSS selector to wait for before extracting (for JS-heavy pages)", "string", False),
        ToolParam("exclude_selectors", "CSS selectors to exclude (comma-separated)", "string", False),
    ]

    def __init__(self, vector_store_factory=None):
        """
        Args:
            vector_store_factory: Optional callable that returns a VectorMemoryStore
                                  for a given collection name. Enables crawl_embed.
        """
        self._vector_factory = vector_store_factory

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.pop("action", "").lower()
        url = kwargs.pop("url", "").strip()

        if not action:
            return ToolResult(success=False, error="Missing 'action' parameter")
        if not url:
            return ToolResult(success=False, error="Missing 'url' parameter")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        try:
            if action == "crawl":
                return await self._crawl_single(url, **kwargs)
            elif action == "deep_crawl":
                return await self._deep_crawl(url, **kwargs)
            elif action == "crawl_embed":
                return await self._crawl_and_embed(url, **kwargs)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown action: {action}. Use: crawl, deep_crawl, crawl_embed",
                )
        except ImportError:
            # Crawl4AI not installed → fallback to requests + HTML parsing
            logger.warning(
                "[CRAWLER] crawl4ai not installed — falling back to requests"
            )
            return await self._fallback_crawl(url, **kwargs)
        except Exception as e:
            logger.warning(f"[CRAWLER] Crawl4AI error: {e} — trying fallback")
            try:
                return await self._fallback_crawl(url, **kwargs)
            except Exception as fallback_err:
                logger.error(f"[CRAWLER] Fallback also failed: {fallback_err}")
                return ToolResult(success=False, error=str(e))

    # ----------------------------------------------------------------
    # Fallback: requests + stdlib HTML parsing (no Crawl4AI needed)
    # ----------------------------------------------------------------

    async def _fallback_crawl(self, url: str, **kwargs) -> ToolResult:
        """
        Fallback when Crawl4AI is not available or fails.
        Uses requests + BeautifulSoup to extract article content.
        Prioritizes <article>, <main> content; strips nav, ads, footers.
        """
        import asyncio

        max_chars = kwargs.get("max_chars", MAX_CONTENT_CHARS)
        start = time.time()

        # --- Fetch HTML ---
        try:
            import requests as _requests
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es,en;q=0.9",
            }
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: _requests.get(url, headers=headers, timeout=20, verify=False),
            )
            resp.raise_for_status()
            raw_html = resp.text
        except ImportError:
            import urllib.request, ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, context=ctx, timeout=20) as resp_u:
                html_bytes = resp_u.read()
                raw_html = html_bytes.decode("utf-8", errors="replace")

        # --- Extract article content with BeautifulSoup ---
        text = ""
        method = "fallback"
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_html, "html.parser")

            # Remove noise elements
            for tag in soup.find_all([
                "script", "style", "nav", "footer", "header", "aside",
                "noscript", "svg", "iframe", "form", "button",
            ]):
                tag.decompose()

            # Remove by class/id patterns (ads, sidebars, comments, social)
            noise_patterns = [
                "sidebar", "comment", "social", "share", "related",
                "newsletter", "subscribe", "popup", "modal", "cookie",
                "banner", "ad-", "advertisement", "promo", "widget",
            ]
            for el in soup.find_all(True):
                try:
                    el_class = " ".join(el.get("class") or [])
                    el_id = el.get("id") or ""
                    combined = f"{el_class} {el_id}".lower()
                    if any(p in combined for p in noise_patterns):
                        el.decompose()
                except Exception:
                    pass

            # Prioritize article/main content
            article = soup.find("article") or soup.find("main") or soup.find(class_=re.compile(r"article|content|entry|post|story", re.I))

            if article:
                # Extract from article body
                paragraphs = article.find_all(["p", "h1", "h2", "h3", "h4", "blockquote", "li"])
                text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
                method = "fallback (bs4-article)"
            else:
                # No article tag — extract all paragraph text from body
                body = soup.find("body") or soup
                paragraphs = body.find_all(["p", "h1", "h2", "h3", "h4"])
                text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)
                method = "fallback (bs4-body)"

        except ImportError:
            pass

        # Final fallback: raw HTML stripping
        if not text.strip():
            text = self._html_to_text(raw_html)
            method = "fallback (html-strip)"

        elapsed = (time.time() - start) * 1000

        return ToolResult(
            success=True,
            output=text[:max_chars],
            metadata={
                "url": url,
                "method": method,
                "html_length": len(raw_html),
                "text_length": len(text),
                "token_savings_pct": round(
                    (1 - len(text) / max(len(raw_html), 1)) * 100, 1
                ),
                "truncated": len(text) > max_chars,
                "elapsed_ms": round(elapsed, 0),
            },
        )

    @staticmethod
    def _html_to_text(html_content: str) -> str:
        """
        Convert raw HTML to clean text using only stdlib html.parser.
        Strips scripts, styles, nav, footer, and extracts readable content.
        """
        from html.parser import HTMLParser

        class _TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self._skip_tags = {"script", "style", "nav", "footer", "header", "noscript", "svg"}
                self._skip_depth = 0
                self._chunks: list[str] = []
                self._current_tag = ""

            def handle_starttag(self, tag, attrs):
                self._current_tag = tag
                if tag in self._skip_tags:
                    self._skip_depth += 1
                if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "li", "tr"):
                    self._chunks.append("\n")

            def handle_endtag(self, tag):
                if tag in self._skip_tags and self._skip_depth > 0:
                    self._skip_depth -= 1
                if tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr"):
                    self._chunks.append("\n")

            def handle_data(self, data):
                if self._skip_depth == 0:
                    text = data.strip()
                    if text:
                        self._chunks.append(text)

        extractor = _TextExtractor()
        try:
            extractor.feed(html_content)
        except Exception:
            pass

        # Join and clean up excessive whitespace
        raw_text = " ".join(extractor._chunks)
        # Collapse multiple newlines
        import re
        clean = re.sub(r"\n{3,}", "\n\n", raw_text)
        clean = re.sub(r" {2,}", " ", clean)
        return clean.strip()


    # ----------------------------------------------------------------
    # Action: crawl — single page → clean Markdown
    # ----------------------------------------------------------------

    async def _crawl_single(self, url: str, **kwargs) -> ToolResult:
        """Crawl a single page and return clean Markdown."""
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        max_chars = kwargs.get("max_chars", MAX_CONTENT_CHARS)
        wait_for = kwargs.get("wait_for")
        exclude = kwargs.get("exclude_selectors", "")

        config = CrawlerRunConfig(
            exclude_external_links=True,
            word_count_threshold=10,
        )
        if wait_for:
            config.wait_for = wait_for
        if exclude:
            config.excluded_selector = ",".join(
                s.strip() for s in exclude.split(",") if s.strip()
            )

        start = time.time()
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)

        if not result.success:
            # Crawl4AI failed — try BS4 fallback
            logger.info("[CRAWLER] Crawl4AI failed, trying BS4 fallback")
            return await self._fallback_crawl(url, **kwargs)

        # Prefer fit_markdown (cleaner) over raw markdown
        markdown = getattr(result, "fit_markdown", None) or result.markdown or ""

        # --- Quality check: detect navigation-heavy garbage ---
        # Count markdown links vs paragraph text
        link_count = markdown.count("](")
        lines = [l.strip() for l in markdown.split("\n") if l.strip()]
        nav_lines = sum(1 for l in lines if l.startswith("* [") or l.startswith("- [") or l.startswith("["))
        total_lines = max(len(lines), 1)
        nav_ratio = nav_lines / total_lines

        # If >40% of lines are navigation links, the extraction is garbage
        if nav_ratio > 0.4 or len(markdown.strip()) < 200:
            logger.info(
                f"[CRAWLER] Crawl4AI output is navigation-heavy "
                f"(nav_ratio={nav_ratio:.0%}, links={link_count}). "
                f"Falling back to BS4 article extraction."
            )
            return await self._fallback_crawl(url, **kwargs)

        # Token savings estimate
        html_len = len(result.html or "")
        md_len = len(markdown)
        savings_pct = round((1 - md_len / max(html_len, 1)) * 100, 1)

        elapsed = (time.time() - start) * 1000

        return ToolResult(
            success=True,
            output=markdown[:max_chars],
            metadata={
                "url": str(result.url or url),
                "title": (result.metadata or {}).get("title", ""),
                "markdown_length": md_len,
                "html_length": html_len,
                "token_savings_pct": savings_pct,
                "truncated": md_len > max_chars,
                "elapsed_ms": round(elapsed, 0),
                "links_found": len((result.links or {}).get("internal", [])) if result.links else 0,
            },
        )

    # ----------------------------------------------------------------
    # Action: deep_crawl — follow internal links
    # ----------------------------------------------------------------

    async def _deep_crawl(self, url: str, **kwargs) -> ToolResult:
        """Crawl a page and follow internal links up to max_pages."""
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        max_pages = min(kwargs.get("max_pages", MAX_PAGES), 20)
        max_chars = kwargs.get("max_chars", MAX_CONTENT_CHARS)

        config = CrawlerRunConfig(
            exclude_external_links=True,
            word_count_threshold=10,
        )

        pages_content = []
        visited = set()
        to_visit = [url]
        domain = urlparse(url).netloc

        start = time.time()
        async with AsyncWebCrawler() as crawler:
            while to_visit and len(visited) < max_pages:
                current_url = to_visit.pop(0)
                if current_url in visited:
                    continue
                visited.add(current_url)

                try:
                    result = await crawler.arun(url=current_url, config=config)
                    if result.success and result.markdown:
                        pages_content.append({
                            "url": str(result.url or current_url),
                            "title": (result.metadata or {}).get("title", ""),
                            "content": result.markdown[:max_chars // max_pages],
                        })

                        # Discover internal links
                        if result.links:
                            for link in result.links.get("internal", []):
                                link_url = link.get("href", "")
                                if (link_url and
                                    urlparse(link_url).netloc == domain and
                                    link_url not in visited):
                                    to_visit.append(link_url)
                except Exception as e:
                    logger.debug(f"[CRAWLER] Skip {current_url}: {e}")

        elapsed = (time.time() - start) * 1000

        # Combine all pages
        combined = "\n\n---\n\n".join(
            f"## {p['title'] or p['url']}\n\n{p['content']}"
            for p in pages_content
        )

        return ToolResult(
            success=bool(pages_content),
            output=combined[:max_chars],
            metadata={
                "pages_crawled": len(pages_content),
                "pages_visited": len(visited),
                "urls": [p["url"] for p in pages_content],
                "elapsed_ms": round(elapsed, 0),
                "truncated": len(combined) > max_chars,
            },
        )

    # ----------------------------------------------------------------
    # Action: crawl_embed — crawl + chunk + embed for semantic search
    # ----------------------------------------------------------------

    async def _crawl_and_embed(self, url: str, **kwargs) -> ToolResult:
        """
        Crawl a page, chunk the Markdown, and embed each chunk into
        VectorMemoryStore for semantic search (RAG pattern).

        If 'query' is provided, also runs a semantic search after embedding.
        """
        if not self._vector_factory:
            return ToolResult(
                success=False,
                error="crawl_embed requires a vector_store_factory to be configured",
            )

        # Step 1: Crawl — get FULL page content (no truncation for RAG)
        # Override max_chars so _crawl_single / _fallback_crawl return the
        # entire extracted text.  Chunking + embedding handles the size.
        rag_kwargs = {**kwargs, "max_chars": 500_000}
        crawl_result = await self._crawl_single(url, **rag_kwargs)
        if not crawl_result.success:
            crawl_result = await self._fallback_crawl(url, **rag_kwargs)
        if not crawl_result.success:
            return crawl_result

        markdown = crawl_result.output
        collection_name = kwargs.get("collection", "web_knowledge")
        query = kwargs.get("query")

        # Step 2: Chunk
        chunks = self._chunk_text(markdown, CHUNK_SIZE, CHUNK_OVERLAP)

        # Step 3: Embed into VectorMemoryStore
        store = self._vector_factory(collection_name)
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

        embedded_count = 0
        for i, chunk in enumerate(chunks):
            if len(chunk.strip()) < 50:  # Skip tiny chunks
                continue
            key = f"web:{url_hash}:chunk_{i}"
            store.write(key, {
                "content": chunk,
                "url": url,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "crawled_at": time.time(),
            }, requester="INTELLECT")
            embedded_count += 1

        result_metadata = {
            "url": url,
            "total_chunks": len(chunks),
            "embedded_chunks": embedded_count,
            "collection": collection_name,
            "token_savings_pct": crawl_result.metadata.get("token_savings_pct", 0),
        }

        # Step 4: Hybrid search — keyword + semantic
        search_results = []
        if query:
            # --- 4a: Keyword search (free, precise for proper nouns) ---
            keyword_hits = []
            query_terms = [
                t.strip().lower()
                for t in re.split(r"[\s,]+", query)
                if len(t.strip()) > 2 and t.strip().lower() not in {
                    "the", "what", "did", "how", "and", "for", "from",
                    "with", "was", "that", "this", "are", "has", "had",
                    "its", "who", "when", "where", "which", "about",
                    "into", "been", "will", "can", "does", "introduced",
                }
            ]
            logger.info(f"[CRAWLER] Hybrid search: query='{query}' terms={query_terms}")

            for i, chunk in enumerate(chunks):
                if len(chunk.strip()) < 50:
                    continue
                chunk_lower = chunk.lower()
                matched_terms = [t for t in query_terms if t in chunk_lower]
                if matched_terms:
                    overlap = len(matched_terms) / max(len(query_terms), 1)
                    # Smart snippet: center on the rarest term (most specific)
                    best_term = min(matched_terms, key=lambda t: chunk_lower.count(t))
                    term_pos = chunk_lower.find(best_term)
                    start = max(0, term_pos - 200)
                    snippet = chunk[start:start + 500]
                    keyword_hits.append({
                        "content": snippet,
                        "score": round(overlap, 3),
                        "url": url,
                        "_match_type": "keyword",
                        "_matched_terms": matched_terms,
                    })

            # Sort by overlap score (most matching terms first)
            keyword_hits.sort(key=lambda x: x["score"], reverse=True)
            keyword_hits = keyword_hits[:5]

            # --- 4b: Semantic search (embedding-based) ---
            semantic_hits = []
            try:
                hits = store.query_semantic(
                    query=query,
                    requester="INTELLECT",
                    top_k=5,
                    min_score=0.3,
                )
                semantic_hits = [
                    {
                        "content": h.get("value", {}).get("content", "")[:500],
                        "score": round(h.get("score", 0), 3),
                        "url": h.get("value", {}).get("url", ""),
                        "_match_type": "semantic",
                    }
                    for h in hits
                ]
            except Exception as e:
                logger.debug(f"[CRAWLER] Semantic search failed: {e}")

            # --- 4c: Merge results — keyword hits first (more precise) ---
            seen_contents = set()
            for hit in keyword_hits + semantic_hits:
                content_key = hit["content"][:100]
                if content_key not in seen_contents:
                    seen_contents.add(content_key)
                    search_results.append(hit)

            search_results = search_results[:7]  # Top 7 combined
            result_metadata["search_results_count"] = len(search_results)
            result_metadata["keyword_hits"] = len(keyword_hits)
            result_metadata["semantic_hits"] = len(semantic_hits)

            if keyword_hits and not semantic_hits:
                logger.info(
                    f"[CRAWLER] Hybrid search: keyword found {len(keyword_hits)} "
                    f"results that semantic search missed!"
                )

        output = {
            "status": f"Embedded {embedded_count} chunks from {url}",
            "search_results": search_results if search_results else None,
        }

        return ToolResult(
            success=True,
            output=output,
            metadata=result_metadata,
        )

    # ----------------------------------------------------------------
    # Utilities
    # ----------------------------------------------------------------

    @staticmethod
    def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
        """
        Split text into overlapping chunks, breaking at paragraph boundaries.
        """
        # Split on double newlines (paragraph boundaries)
        paragraphs = re.split(r"\n{2,}", text)
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk += ("\n\n" + para) if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    # Keep overlap from previous chunk
                    if overlap > 0:
                        current_chunk = current_chunk[-overlap:] + "\n\n" + para
                    else:
                        current_chunk = para
                else:
                    # Single paragraph bigger than chunk_size — split by sentences
                    if len(para) > chunk_size:
                        sentences = re.split(r"(?<=[.!?])\s+", para)
                        for sent in sentences:
                            if len(current_chunk) + len(sent) + 1 <= chunk_size:
                                current_chunk += (" " + sent) if current_chunk else sent
                            else:
                                if current_chunk:
                                    chunks.append(current_chunk)
                                current_chunk = sent
                    else:
                        current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks
