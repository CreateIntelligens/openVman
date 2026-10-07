import sys
from pathlib import Path

_current = Path(__file__).resolve().parent
_embedding_dir = str(_current.parent)
if _embedding_dir not in sys.path:
    sys.path.insert(0, _embedding_dir)

# 由外往內插到最前面，最近的上層目錄排第一：worktree 放在 repo 的 .worktree/ 底下時，
# 才不會 import 到外層主目錄的 brain.embedding。
for p in reversed(_current.parents):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
