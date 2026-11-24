"""Files used by the pinned Docling layout and accurate table models."""
from pathlib import Path

LAYOUT_DIR = Path("docling-project--docling-layout-heron")
TABLE_DIR = Path("docling-project--docling-models/model_artifacts/tableformer")
LAYOUT_FILES = tuple(LAYOUT_DIR / name for name in ("config.json", "preprocessor_config.json", "model.safetensors"))
PDF_FILES = (*LAYOUT_FILES, TABLE_DIR / "accurate/tm_config.json", TABLE_DIR / "accurate/tableformer_accurate.safetensors")


def missing_files(root: Path | None, required=PDF_FILES) -> list[str]:
    missing = []
    for name in required:
        try:
            if root and (root / name).is_file() and (root / name).stat().st_size > 0:
                continue
        except OSError:
            pass
        missing.append(name.as_posix())
    return missing
