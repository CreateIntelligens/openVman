"""Generate five source-faithful EUS notes without indexing them."""

from common import ROOT, mirror_check, run_container, write_json


def main():
    mirror_check("mirror_before.json")
    result = run_container({
        "operation": "generate",
        "source": (ROOT / "source_catalog.md").read_text(),
    }, "generation_checkpoint.json")
    notes = ROOT / "notes"
    notes.mkdir(exist_ok=True)
    for note in result["notes"]:
        (notes / note["filename"]).write_text(note["markdown"] + "\n")
    write_json("generation.json", result)


if __name__ == "__main__":
    main()
