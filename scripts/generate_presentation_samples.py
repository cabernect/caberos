"""Write operator-testable samples without replacing existing workspace files.

From backend/: uv run python ../scripts/generate_presentation_samples.py --output-dir /path
"""

import argparse
import json
from pathlib import Path

from agentos.artifacts.formats import deck, pptx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[1] / "backend/tests/fixtures/artifacts"
    source = (fixtures / "shared-presentation.json").read_bytes()
    spec = json.loads(source)
    canonical = deck.build(spec, fixtures)
    outputs = {
        # The workspace source file — canonical spec with pinned image assets.
        "presentation-demo.deck.json": canonical,
        # Native editable PPTX rendered from the same spec.
        "presentation-demo.pptx": pptx.build(json.loads(canonical), fixtures),
        "ordinary-report.html": (fixtures / "ordinary-report.html").read_bytes(),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    existing = [name for name in outputs if (args.output_dir / name).exists()]
    if existing:
        parser.error(f"Refusing to overwrite existing samples: {', '.join(existing)}")
    for name, data in outputs.items():
        with (args.output_dir / name).open("xb") as stream:
            stream.write(data)
        print(args.output_dir / name)


if __name__ == "__main__":
    main()
