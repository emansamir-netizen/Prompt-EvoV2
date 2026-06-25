"""PromptEvo reporting subsystem.

Separate from the ``reports/`` directory which is used as the runtime
output destination for per-session artifacts (transcripts, messages,
summaries). Placing the builder here avoids a package / output-directory
namespace collision.
"""
