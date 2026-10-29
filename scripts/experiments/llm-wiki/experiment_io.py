"""Keep private experiment outputs outside checkouts and away from inputs."""

from pathlib import Path
import subprocess


def repository_roots():
    checkout = Path(__file__).resolve().parents[3]
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=checkout,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return {checkout, (checkout / common).resolve().parent}


def validate_output(path, *, inputs=(), roots=None):
    """Validate before reading private inputs or making remote requests."""
    target = Path(path).resolve()
    for root in repository_roots() if roots is None else roots:
        root = Path(root).resolve()
        if target == root or root in target.parents:
            raise ValueError("Experiment outputs must stay outside repositories")
    for source in inputs:
        source = Path(source).resolve()
        same_file = target.exists() and source.exists() and target.samefile(source)
        if target == source or same_file:
            raise ValueError("Output must not overwrite an experiment input")
    return target
