"""Fixed local-admin model and resource policy for the SAGE pre-release runtime."""

from __future__ import annotations


SAGE_LOCAL_ADMIN_MODEL = "sage-gemma4-e2b:q5_k_m"
SAGE_LOCAL_ADMIN_CONTEXT_WINDOW = 16_384
SAGE_LOCAL_ADMIN_KEEP_ALIVE = 0
SAGE_LOCAL_ADMIN_CONCURRENCY = 1

SAGE_LOCAL_ADMIN_SOURCE_REPOSITORY = "bartowski/google_gemma-4-E2B-it-GGUF"
SAGE_LOCAL_ADMIN_SOURCE_FILENAME = "google_gemma-4-E2B-it-Q5_K_M.gguf"
# Governed artifacts must bind immutable upstream bytes. A fixed SHA paired with
# ``resolve/main`` is not sufficient because Hugging Face branches are mutable.
SAGE_LOCAL_ADMIN_SOURCE_REVISION = "b5e99bd964eaacc27ba484bb2eb3e9f6160b9143"
SAGE_LOCAL_ADMIN_SOURCE_URL = (
    "https://huggingface.co/"
    f"{SAGE_LOCAL_ADMIN_SOURCE_REPOSITORY}/resolve/{SAGE_LOCAL_ADMIN_SOURCE_REVISION}/"
    f"{SAGE_LOCAL_ADMIN_SOURCE_FILENAME}?download=true"
)
SAGE_LOCAL_ADMIN_SOURCE_SHA256 = (
    "53c8e1a5bf3f9c83074f6ed8a737e8d17ac70e90904078dc3e010739d1152c6a"
)
SAGE_LOCAL_ADMIN_SOURCE_BYTES = 3_660_000_000

# E2B Q5_K_M is intentionally enabled only on hosts with at least 16 GiB RAM.
# Installation remains possible on smaller hosts so a future hardware upgrade does
# not require repeating setup, but SAGE will not run the assistant there.
SAGE_LOCAL_ADMIN_MIN_RAM_BYTES = 16 * 1024**3
SAGE_LOCAL_ADMIN_INSTALL_FREE_BYTES = 10 * 1024**3
