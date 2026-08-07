"""Configure pytest path for the url-pdf-service."""

import sys
from pathlib import Path

# Add the service root to sys.path so `from app.xxx import ...` works
sys.path.insert(0, str(Path(__file__).parent.parent))
