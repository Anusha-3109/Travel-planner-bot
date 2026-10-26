"""Download the TravelPlanner dataset files from Hugging Face.

Run once before starting the app:  python -m backend.travel_data.download

TravelPlanner (Xie et al., 2024, https://huggingface.co/datasets/osunlp/TravelPlanner)
is released under CC-BY-4.0. Its reference data is a snapshot of US flights,
restaurants, attractions and accommodations for March 2022.
"""

import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download

from backend import config

REPO_ID = "osunlp/TravelPlanner"
FILES = (
    "train.csv",
    "validation.csv",
    "test.csv",
    "train_ref_info.jsonl",
    "validation_ref_info.jsonl",
    "test_ref_info.jsonl",
)


def download(target_dir: Path = config.TRAVELPLANNER_DIR) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in FILES:
        target = target_dir / name
        # Copy out of the Hugging Face cache: Windows often can't create the cache's symlinks.
        shutil.copyfile(hf_hub_download(REPO_ID, name, repo_type="dataset"), target)
        paths.append(target)
    return paths


if __name__ == "__main__":
    for path in download():
        print(f"{path.relative_to(config.ROOT_DIR)}  {path.stat().st_size / 1e6:.1f} MB")
