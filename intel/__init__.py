"""TaxKernel Intelligence Layer.

This package is intentionally free of import-time side effects: importing
``intel`` must never open the database, read a key, touch the network, or
load a model. Modules do their work when their functions are called.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
