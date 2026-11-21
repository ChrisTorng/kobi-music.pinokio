"""Keep native model and synthesizer calls off the server's interpreter."""

from pathlib import Path
import sys

from .pipeline import Options
from .server import run_job


if __name__ == '__main__':
    job_folder, source, font = sys.argv[1:]
    options = Options.model_validate_json(sys.stdin.buffer.read())
    run_job(Path(job_folder), Path(source), Path(font) if font else None, options)
