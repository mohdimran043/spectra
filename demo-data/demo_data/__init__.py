"""SPECTRA synthetic enterprise demo dataset.

``demo_data`` is a *generator*, never a fixture dump: every file under the
output directory is produced by real writers (PyMuPDF, python-docx,
python-pptx, openpyxl, Pillow, ffmpeg, :mod:`wave`) so the corpus is genuinely
indexable by the production ingestion pipeline.

The package lives in the hyphenated ``demo-data`` directory, so import it with
``PYTHONPATH=demo-data`` (or after ``pip install -e .``, which lists
``demo-data`` in the root package discovery).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "1.0.0"
