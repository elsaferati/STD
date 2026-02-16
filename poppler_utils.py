from __future__ import annotations

from pathlib import Path
import os
import subprocess
import uuid


def resolve_pdftoppm(poppler_path: str) -> str:
    if not poppler_path:
        raise ValueError("POPPLER_PATH is required for PDF conversion.")

    path = Path(poppler_path)
    if path.is_dir():
        binary = "pdftoppm.exe" if os.name == "nt" else "pdftoppm"
        candidate = path / binary
    else:
        candidate = path

    if not candidate.exists():
        raise FileNotFoundError(f"pdftoppm not found at: {candidate}")

    return str(candidate)


def pdf_to_images(
    pdf_path: Path, output_dir: Path, pdftoppm_path: str, max_pages: int, dpi: int
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    unique = uuid.uuid4().hex
    prefix = output_dir / f"{pdf_path.stem}_{unique}"

    cmd = [pdftoppm_path, "-png"]
    if dpi > 0:
        cmd.extend(["-r", str(dpi)])
    if max_pages > 0:
        cmd.extend(["-f", "1", "-l", str(max_pages)])
    cmd.extend([str(pdf_path), str(prefix)])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"pdftoppm failed ({result.returncode}): {result.stderr.strip()}"
        )

    images = list(output_dir.glob(f"{prefix.name}-*.png"))

    def _page_number(path: Path) -> int:
        stem = path.stem
        if "-" not in stem:
            return 0
        try:
            return int(stem.split("-")[-1])
        except ValueError:
            return 0

    images.sort(key=_page_number)
    return images
