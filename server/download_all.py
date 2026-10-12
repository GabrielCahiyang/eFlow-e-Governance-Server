"""
Download all models from HuggingFace to the local models/ directory.
Run this script to pre-download all GGUF models.

Usage:
    python server/download_all.py
"""

import sys
import argparse
import os
import time
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add server dir to path so we can import model_registry
sys.path.insert(0, str(Path(__file__).parent))

from model_registry import list_all_models, download_model, MODELS_DIR


def main():
    parser = argparse.ArgumentParser(description="Download the registered eFlow models.")
    parser.add_argument("--http", action="store_true", help="Use curl if Hugging Face transfers stall.")
    args = parser.parse_args()
    models = list_all_models()
    failed = False
    
    print("")
    print("=" * 50)
    print("  Downloading All Models from HuggingFace")
    print("=" * 50)
    print(f"  Models directory: {MODELS_DIR}")
    print(f"  Total models: {len(models)}")
    print("")
    
    for i, entry in enumerate(models, 1):
        status = "[OK] already downloaded" if entry.is_downloaded else "[>>] downloading..."
        size_gb = entry.size_bytes / 1e9
        print(f"  [{i}/{len(models)}] {entry.display_name} ({size_gb:.1f} GB) -- {status}")
        
        if not entry.is_downloaded:
            start = time.time()
            try:
                download_model(entry, use_http=args.http)
                elapsed = time.time() - start
                print(f"          [OK] Done in {elapsed:.0f}s -> {entry.local_path.name}")
            except Exception as e:
                failed = True
                print(f"          [FAIL] {e}")
        print()
    
    print("-" * 50)
    print("")
    print("Download summary:")
    for entry in models:
        icon = "[OK]" if entry.is_downloaded else "[--]"
        print(f"  {icon} {entry.display_name}")
    print("")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
