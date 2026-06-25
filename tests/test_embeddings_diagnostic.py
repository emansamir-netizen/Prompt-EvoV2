"""DIAGNOSTIC (not a real regression): does embedding resolution actually work?

scout_planner Phases 1 & 2 (the pre-attack target recon) only run when
`_resolve_embeddings` returns a live embeddings object. This test exercises that
exact path and reports the outcome, so we can confirm whether recon is being
silently skipped in this environment.

Run with: pytest tests/test_embeddings_diagnostic.py -s
It never fails -- it just reports.
"""

import os


def test_report_embedding_availability():
    print("\n================ EMBEDDING DIAGNOSTIC ================")
    print("OLLAMA_BASE_URL = " + os.getenv("OLLAMA_BASE_URL", "(unset -> http://localhost:11434)"))
    print("EMBEDDING_MODEL = " + os.getenv("EMBEDDING_MODEL", "(unset -> nomic-embed-text)"))
    print("OPENAI_API_KEY  = " + ("set" if os.getenv("OPENAI_API_KEY") else "unset"))

    from agents.scout_planner import _resolve_embeddings

    emb = None
    try:
        emb = _resolve_embeddings(config={})
    except Exception as exc:  # noqa: BLE001
        print("_resolve_embeddings raised: " + type(exc).__name__ + ": " + str(exc))

    if emb is None:
        print(">> RESULT: embeddings = None  ->  scout_planner Phase 1 (domain")
        print("   detection) and Phase 2 (vuln profiling) are SKIPPED. No")
        print("   pre-attack target recon runs; planner falls back to the")
        print("   static goal pool only.")
    else:
        print(">> RESULT: embeddings resolved -> " + type(emb).__name__)
        try:
            vec = emb.embed_query("connectivity test")
            print("   embed_query OK -- vector length = " + str(len(vec)))
            print(">> Embeddings WORK. Recon Phases 1 & 2 can run.")
        except Exception as exc:  # noqa: BLE001
            print("   embed_query FAILED: " + type(exc).__name__ + ": " + str(exc))
            print(">> Object resolved but live embed failed -> recon still skipped.")
    print("=====================================================")
