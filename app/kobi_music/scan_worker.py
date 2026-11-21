"""Run one model per detector job in a separate process to release GPU memory."""

import json
import os
from pathlib import Path
import sys


def main(pages, output, device, detector):
    os.environ['COPISTERIA_DETECTOR'] = detector
    from copisteria import pipeline

    model = pipeline.read.load_model(str(pipeline.EVIDENCE), device)
    for path in json.loads(pages.read_text(encoding='utf-8')):
        result = pipeline.run_page(Path(path), model, output, device)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]), *sys.argv[3:])
