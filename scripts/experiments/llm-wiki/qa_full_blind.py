"""Run only main and the unchanged full-QA-vector candidate in isolation."""

from pathlib import Path

from hybrid_benchmark import hybrid_script
import main_wiki_benchmark as benchmark
from qa_full_evaluation import ARMS


def main():
    source = (Path(__file__).parent / 'hybrid_controls.py').read_text()
    benchmark.CLEAN_INDEX_ARMS = ARMS
    benchmark.SCRIPT = hybrid_script(benchmark.SCRIPT, source)
    benchmark.main()


if __name__ == '__main__':
    main()
