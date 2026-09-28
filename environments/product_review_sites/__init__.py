"""Independent generated product-review sites; no shared harness mutation."""
from .generate import generate_reviews
from .runtime import Runtime

__all__ = ['generate_reviews', 'Runtime']
