"""
INTI — TEST 2 DEMO: Video Processing + Semantic Search
=======================================================
Script para mostrar el feature de video processing en vivo.

Muestra:
  1. El video ya está vectorizado (2 chunks en ChromaDB)
  2. Hacemos una pregunta sin darle contexto del video
  3. INTI recupera el chunk exacto via búsqueda semántica
  4. Gemini analiza el chunk y responde con timestamp preciso

Correr: python demo_test2_video.py
"""

import asyncio
import os
import sys
import time

# ── Color helpers (sin dependencias extra) ──────────────────────
CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
MAGENTA = "\033[95m"
WHITE   = "\033[97m"
DIM     = "\033[2m"
RESET   = "\033[0m"
BOLD    = "\033[1m"

def banner(text: str, color: str = CYAN):
    width = 60
    print(f"\n{color}{BOLD}{'─' * width}{RESET}")
    print(f"{color}{BOLD}  {text}{RESET}")
    print(f"{color}{BOLD}{'─' * width}{RESET}\n")

def step(n: int, text: str):
    print(f"{YELLOW}{BOLD}[{n}]{RESET} {WHITE}{text}{RESET}")

def info(text: str):
    print(f"    {DIM}{text}{RESET}")

def result(label: str, value: str, color: str = GREEN):
    print(f"    {color}{BOLD}{label}:{RESET} {WHITE}{value}{RESET}")


# ── Main demo ────────────────────────────────────────────────────

async def run_demo():
    banner("INTI — TEST 2: VIDEO PROCESSING", MAGENTA)

    # Load env
    from dotenv import load_dotenv
    load_dotenv()

    VIDEO_PATH = os.path.join(
        os.path.dirname(__file__), "data", "media", "video_test_inti.mp4"
    )

    # ── STEP 1: Show what's already in ChromaDB ──────────────────
    step(1, "Checking ChromaDB — video already vectorized")
    info("(embedding was done previously, this costs $0 tokens)")
    time.sleep(0.8)

    try:
        import chromadb
        chroma_path = os.path.join(os.path.dirname(__file__), "data", "chromadb_multimodal")
        client = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_collection("multimodal_knowledge")
        total = collection.count()

        # Get all entries for our video
        all_data = collection.get(include=["metadatas"])
        video_chunks = [
            m for m in all_data["metadatas"]
            if m.get("file", "").endswith(".mp4") or m.get("type") == "video"
        ]

        result("Total vectors in DB", str(total))
        result("Video chunks found", str(len(video_chunks)))
        for i, chunk in enumerate(video_chunks):
            info(f"  Chunk {i}: {chunk.get('timestamp', 'N/A')}  "
                 f"({chunk.get('start_sec', 0):.0f}s → {chunk.get('end_sec', 0):.0f}s)")
        print()
    except Exception as e:
        print(f"    {YELLOW}Could not inspect ChromaDB directly: {e}{RESET}\n")

    # ── STEP 2: Semantic search (free, local) ────────────────────
    step(2, "Semantic Search — no context given to INTI about the video")
    time.sleep(0.5)

    QUESTIONS = [
        "In what moment does the man look saddest?",
        "What is the man doing in this video?",
    ]

    print(f"    {YELLOW}Questions to ask INTI:{RESET}")
    for q in QUESTIONS:
        print(f"      → \"{q}\"")
    print()
    time.sleep(1.0)

    # Import and use MediaEmbedderTool directly
    sys.path.insert(0, os.path.dirname(__file__))
    from tools.media_embedder import MediaEmbedderTool

    tool = MediaEmbedderTool()

    # ── STEP 3: Search + Analyze each question ───────────────────
    step(3, "Running analyze — search vector DB + send chunk to Gemini")
    print()

    for i, question in enumerate(QUESTIONS):
        print(f"  {CYAN}{BOLD}Question {i+1}:{RESET} \"{question}\"")
        print(f"  {DIM}  Embedding query → cosine search in ChromaDB → upload chunk → Gemini Flash...{RESET}")

        t0 = time.time()
        res = await tool.execute(
            action="analyze",
            query=question,
            top_k=3,
        )
        elapsed = time.time() - t0

        if res.success:
            out = res.output
            print(f"  {GREEN}{BOLD}  ✓ Response ({elapsed:.1f}s):{RESET}")
            print(f"    {WHITE}Source:{RESET}     {out.get('source_file', 'N/A')}")
            print(f"    {WHITE}Timestamp:{RESET}  {out.get('source_timestamp', 'N/A')}")
            print(f"    {WHITE}Score:{RESET}      {out.get('score', 0):.3f}")
            print()
            analysis = out.get("analysis", "No analysis")
            # Pretty-print analysis (wrap at 70 chars)
            lines = analysis.split("\n")
            for line in lines[:8]:  # cap at 8 lines for demo
                print(f"    {line}")
            if len(lines) > 8:
                print(f"    {DIM}... (truncated for demo){RESET}")
        else:
            print(f"  {YELLOW}  ✗ Error: {res.error}{RESET}")

        print()
        print(f"  {'─' * 55}")
        print()
        time.sleep(0.5)

    # ── STEP 4: Summary ──────────────────────────────────────────
    banner("TEST 2 COMPLETE", GREEN)
    print(f"  {WHITE}What just happened:{RESET}")
    print(f"  {DIM}  1. Video was split into 60s chunks with 5s overlap{RESET}")
    print(f"  {DIM}  2. Each chunk → Gemini Embedding 2 → stored in ChromaDB{RESET}")
    print(f"  {DIM}  3. Query text embedded → cosine similarity search (local, free){RESET}")
    print(f"  {DIM}  4. Top matching chunk sent to Gemini Flash → answer with timestamp{RESET}")
    print()
    print(f"  {YELLOW}Gemini had zero context about the movie.{RESET}")
    print(f"  {YELLOW}It identified the scene and timestamp from the video chunk alone.{RESET}")
    print()


if __name__ == "__main__":
    asyncio.run(run_demo())
