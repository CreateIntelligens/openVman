import sys
from pathlib import Path

_current = Path(__file__).resolve().parent
_embedding_dir = str(_current.parent)
if _embedding_dir not in sys.path:
    sys.path.insert(0, _embedding_dir)

for p in _current.parents:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
