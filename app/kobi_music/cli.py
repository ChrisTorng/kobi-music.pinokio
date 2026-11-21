"""Agent-friendly commands with a JSON result on stdout."""

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from .pipeline import GRID, TASKS, Options, capabilities, execute


def main():
    parser = argparse.ArgumentParser(prog='kobi-music')
    commands = parser.add_subparsers(dest='task', required=True)
    commands.add_parser('capabilities', help='List formats, operations and available engines')
    serve = commands.add_parser('serve', help='Start the local web UI and OpenAPI server')
    serve.add_argument('--port', type=int, default=50883)
    for task in TASKS:
        sub = commands.add_parser(task)
        sub.add_argument('source', type=Path)
        sub.add_argument('-o', '--output', type=Path, required=True)
        sub.add_argument('--options', type=Path, help='JSON options, same schema as the HTTP API')
        if task == 'scan':
            sub.add_argument('--pages')
            sub.add_argument('--detector', choices=['28m', '2m'])
        if task in {'transcribe', 'scan'}:
            sub.add_argument('--device', choices=['auto', 'cuda', 'cpu'])
        if task in {'transcribe', 'quantize'}:
            sub.add_argument('--grid', choices=GRID)
            sub.add_argument('--strength', type=float)
            sub.add_argument('--bpm', type=float)
            sub.add_argument('--downbeat', type=float)
            sub.add_argument('--beats', type=Path, help='JSON array of absolute quarter-note times in seconds')
            sub.add_argument('--meter')
            sub.add_argument('--sheet', action='store_true', default=None)
        sub.add_argument('--render', action='store_true', default=None)
        sub.add_argument('--audio-format', choices=['wav', 'flac', 'mp3'])
        font = sub.add_mutually_exclusive_group()
        font.add_argument('--soundfont', type=Path)
        font.add_argument('--soundfont-url')
        font.add_argument('--soundfont-bank', choices=['musescore', 'kobi-microscopic'])
    args = parser.parse_args()
    if args.task == 'capabilities':
        print(json.dumps(capabilities()))
        return 0
    if args.task == 'serve':
        import uvicorn

        uvicorn.run('kobi_music.server:app', host='127.0.0.1', port=args.port)
        return 0
    try:
        opts = json.loads(args.options.read_text(encoding='utf-8')) if args.options else {}
        opts.update({key: value for key, value in vars(args).items() if key in Options.model_fields and value is not None and key != 'beats'})
        if getattr(args, 'beats', None):
            opts['beats'] = json.loads(args.beats.read_text(encoding='utf-8'))
        settings = Options.model_validate(opts)
        source, output = args.source.resolve(), args.output.resolve()
        if output.exists() and any(output.iterdir()):
            raise ValueError('Choose a new or empty output folder.')
        output.mkdir(parents=True, exist_ok=True)
        font = args.soundfont.resolve() if args.soundfont else None
        with TemporaryDirectory(prefix='kobi-music-') as scratch, (output / 'log.txt').open('w', encoding='utf-8') as log:
            report = execute(args.task, source, output, settings, font=font, log=log, scratch=Path(scratch),
                             progress=lambda stage: print(stage, file=sys.stderr))
        report['output'] = str(output)
        (output / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=True))
        return 0
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
