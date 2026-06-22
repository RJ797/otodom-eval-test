"""Central configuration.

The API key is read ONLY from the environment here and passed straight into the
SDK client. It is never logged, echoed, or returned by any endpoint.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Secrets -----------------------------------------------------------------
# Pulled from the environment at runtime. Do not print or expose this value.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# --- Server ------------------------------------------------------------------
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# --- Selectable models (Gemini only) ----------------------------------------
# Editable lists surfaced in the UI dropdowns. The UI also allows a free-text
# override so you can use an exact model id without changing code.
TEXT_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash",
    "gemini-3.1-pro",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]

# Image generation models only (models that output images).
IMAGE_MODELS = [
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
]

# Thinking levels offered for image generation.
IMAGE_THINKING_LEVELS = ["HIGH", "MINIMAL"]

DEFAULT_TEXT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"
DEFAULT_IMAGE_THINKING_LEVEL = "MINIMAL"


def has_api_key() -> bool:
    """Whether a non-placeholder key is configured (boolean only, never the value)."""
    return bool(GEMINI_API_KEY) and GEMINI_API_KEY != "your_gemini_api_key_here"


# =============================================================================
# Evaluation harness configuration
# =============================================================================

# --- Replicate (Flux) --------------------------------------------------------
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "")
# black-forest-labs/flux-2-klein-9b — 4-step distilled FLUX.2 [klein].
# Inputs: `prompt` (str, required), `images` (array of input image URLs/files,
# max 5, for image-to-image). Output: array of image URIs.
REPLICATE_FLUX_MODEL = "black-forest-labs/flux-2-klein-9b"
REPLICATE_FLUX_PROMPT_FIELD = "prompt"
REPLICATE_FLUX_IMAGES_FIELD = "images"
# Generation params (match the input image's aspect ratio for fair comparison).
REPLICATE_FLUX_ASPECT_RATIO = "match_input_image"
REPLICATE_FLUX_OUTPUT_FORMAT = "jpg"
REPLICATE_FLUX_OUTPUT_QUALITY = 100
REPLICATE_FLUX_OUTPUT_MEGAPIXELS = "1"
REPLICATE_FLUX_GO_FAST = False

# --- AWS S3 + CDN ------------------------------------------------------------
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET", "")
# Root path/prefix inside the bucket for this whole experiment workspace.
S3_ROOT_PREFIX = os.getenv("S3_ROOT_PREFIX", "image-eval").strip("/")
CDN_BASE_URL = os.getenv("CDN_BASE_URL", "").rstrip("/")

# --- MongoDB -----------------------------------------------------------------
MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "image_eval")

# Collection names
COLL_DATASETS = "datasets"
COLL_DATASET_ITEMS = "dataset_items"
COLL_RUNS = "runs"
COLL_RESULTS = "results"

# --- Model variants under test ----------------------------------------------
# Each variant is one column in the eval. `run_variant` in models_registry
# dispatches on `provider`.
VARIANTS: dict[str, dict] = {
    "gemini_min": {
        "provider": "gemini",
        "model": "gemini-3.1-flash-image",
        "thinking_level": "MINIMAL",
    },
    "gemini_high": {
        "provider": "gemini",
        "model": "gemini-3.1-flash-image",
        "thinking_level": "HIGH",
    },
    "flux": {
        "provider": "replicate",
        "model": REPLICATE_FLUX_MODEL,
    },
}
DEFAULT_VARIANTS = ["gemini_min", "gemini_high", "flux"]

# --- Gemini image generation options ----------------------------------------
GEMINI_IMAGE_SIZE = "1K"  # 1K / 2K
# "auto" => omit aspect_ratio so Gemini keeps/decides the shape (matches input
# on edits). Any other value (e.g. "1:1", "4:3") is sent through as-is.
GEMINI_IMAGE_ASPECT_RATIO = "auto"

# --- Pricing (USD) -----------------------------------------------------------
# Gemini API returns only token counts, so cost is computed from tokens. Image
# output tokens are billed far higher than text output, so they are priced
# separately. Defaults are Gemini 3.1 Flash Image STANDARD rates (USD per 1M).
GEMINI_PRICE_INPUT_PER_1M = float(os.getenv("GEMINI_PRICE_INPUT_PER_1M", "0.50"))
GEMINI_PRICE_TEXT_OUTPUT_PER_1M = float(os.getenv("GEMINI_PRICE_TEXT_OUTPUT_PER_1M", "3.00"))
GEMINI_PRICE_IMAGE_OUTPUT_PER_1M = float(os.getenv("GEMINI_PRICE_IMAGE_OUTPUT_PER_1M", "60.00"))
FLUX_COST_PER_IMAGE = float(os.getenv("FLUX_COST_PER_IMAGE", "0"))

# --- Scoring -----------------------------------------------------------------
SCORE_MIN = 1
SCORE_MAX = 10

# --- Runner behavior ---------------------------------------------------------
RUN_CONCURRENCY = int(os.getenv("RUN_CONCURRENCY", "12"))
RUN_MAX_RETRIES = int(os.getenv("RUN_MAX_RETRIES", "2"))


def has_replicate_token() -> bool:
    return bool(REPLICATE_API_TOKEN)


def has_mongo() -> bool:
    return bool(MONGODB_URI)


def has_s3() -> bool:
    return bool(S3_BUCKET) and bool(CDN_BASE_URL)
