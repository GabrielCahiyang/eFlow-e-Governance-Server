"""
Model Registry — defines available models and handles GGUF downloads from HuggingFace.

Each model entry maps a local tag (used by the frontend) to a HuggingFace repo
and filename.  Models are downloaded lazily on first use.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from huggingface_hub import hf_hub_download, hf_hub_url

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent / "models"


@dataclass
class ModelEntry:
    """A single model definition."""
    tag: str                  # e.g. "deepseek-r1:8b" — matches the frontend
    display_name: str
    hf_repo: str              # HuggingFace repo id
    hf_filename: str          # The .gguf file inside the repo
    chat_format: Optional[str]  # None uses the GGUF's own chat template
    n_ctx: int = 4096         # default context window
    description: str = ""
    family: str = ""
    parameter_size: str = ""
    quantization: str = "Q4_K_M"
    size_bytes: int = 0       # approximate file size
    supports_vision: bool = False
    extra_kwargs: dict = field(default_factory=dict)
    hf_revision: Optional[str] = None
    sha256: Optional[str] = None

    @property
    def local_path(self) -> Path:
        """Path where the GGUF file is stored locally."""
        safe_name = self.tag.replace(":", "_").replace("/", "_")
        return MODELS_DIR / f"{safe_name}.gguf"

    @property
    def is_downloaded(self) -> bool:
        return self.local_path.is_file()


# ── Model definitions ─────────────────────────────────────────────────

MODELS: list[ModelEntry] = [
    ModelEntry(
        tag="deepseek-r1:8b",
        display_name="DeepSeek R1 8B",
        hf_repo="bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF",
        hf_filename="DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf",
        chat_format="llama-3",
        n_ctx=8192,
        description="Proposal decomposition and reasoning",
        family="deepseek",
        parameter_size="8B",
        quantization="Q4_K_M",
        size_bytes=4_920_736_608,
    ),
    ModelEntry(
        tag="qwen3.5:2b",
        display_name="Qwen3.5 2B",
        hf_repo="bartowski/Qwen_Qwen3.5-2B-GGUF",
        hf_filename="Qwen_Qwen3.5-2B-Q4_K_M.gguf",
        chat_format=None,
        n_ctx=4096,
        description="Lightweight eFlow tutorial candidate",
        family="qwen3.5",
        parameter_size="2B",
        quantization="Q4_K_M",
        size_bytes=1_396_198_496,
        hf_revision="7d26695454df6de5fbcce2e58681e62dae06ce43",
        sha256="57a1085840f497d764a7fc5d346922dbde961efb54cc792ea81d694fd846a1d8",
    ),
    ModelEntry(
        tag="qwen3.5:4b",
        display_name="Qwen3.5 4B",
        hf_repo="lmstudio-community/Qwen3.5-4B-GGUF",
        hf_filename="Qwen3.5-4B-Q4_K_M.gguf",
        chat_format=None,
        n_ctx=4096,
        description="Higher-capacity eFlow tutorial candidate",
        family="qwen3.5",
        parameter_size="4B",
        quantization="Q4_K_M",
        size_bytes=2_707_513_696,
        hf_revision="f9f88ac3e234be915e23811a6d28ea287bdb927e",
        sha256="25082a7dd3776cc3c741c6347d3bd04523f05796607b3fbc32fa3a25dfa1418c",
    ),
]

# Quick lookup by tag
_MODEL_MAP: dict[str, ModelEntry] = {m.tag: m for m in MODELS}


def get_model(tag: str) -> Optional[ModelEntry]:
    """Look up a model by its tag."""
    return _MODEL_MAP.get(tag)


def list_all_models() -> list[ModelEntry]:
    """Return all registered models."""
    return list(MODELS)


def download_model(entry: ModelEntry, force: bool = False, *, use_http: bool = False) -> Path:
    """
    Download a model's GGUF file from HuggingFace if not already present.
    Returns the local file path.
    """
    if entry.is_downloaded and not force:
        logger.info(f"Model {entry.tag} already downloaded at {entry.local_path}")
        return entry.local_path

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Downloading {entry.display_name} from {entry.hf_repo}/{entry.hf_filename} ...")

    if use_http:
        curl = shutil.which("curl.exe" if os.name == "nt" else "curl")
        if not curl:
            raise RuntimeError("Direct HTTP download requires curl on PATH")
        downloaded_path = entry.local_path.with_suffix(".gguf.download")
        url = hf_hub_url(entry.hf_repo, entry.hf_filename, revision=entry.hf_revision)
        subprocess.run(
            [curl, "--location", "--fail", "--retry", "2", "--connect-timeout", "15",
             "--max-time", "1800", "--silent", "--show-error",
             "--output", str(downloaded_path),
             url + f"?download=true&nocache={time.time_ns()}"],
            check=True, timeout=1900,
        )
    else:
        downloaded_path = hf_hub_download(
            repo_id=entry.hf_repo,
            filename=entry.hf_filename,
            revision=entry.hf_revision,
            local_dir=str(MODELS_DIR),
        )

    # Rename to our standard name if needed
    dl = Path(downloaded_path)
    if entry.sha256:
        with dl.open("rb") as model_file:
            digest = hashlib.sha256()
            for chunk in iter(lambda: model_file.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry.sha256:
            raise RuntimeError(f"Checksum mismatch for {entry.tag}; model was not installed")
    if dl != entry.local_path:
        dl.replace(entry.local_path)

    logger.info(f"Downloaded {entry.display_name} → {entry.local_path}")
    return entry.local_path
