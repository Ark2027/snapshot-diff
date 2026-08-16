"""Compare two versions of a dataset that share no primary key."""
from .core import Correction, DiffResult, KeyField, compare
from .io import load

__version__ = "1.0.0"
__all__ = ["Correction", "DiffResult", "KeyField", "compare", "load"]
