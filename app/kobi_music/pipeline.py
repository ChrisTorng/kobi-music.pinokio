"""The same workflows serve the UI, HTTP API and command line."""

import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import kobi_bank, midi, sound

AUDIO = {'.wav', '.flac', '.mp3', '.m4a', '.aac', '.aif', '.aiff', '.ogg', '.opus'}
SCAN = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'}
MIDI = {'.mid', '.midi'}
SCORE = {'.musicxml', '.xml', '.mxl', '.mscz', '.mscx'}
TASKS = {'transcribe': AUDIO, 'scan': SCAN, 'quantize': MIDI, 'convert': MIDI | SCORE, 'render': MIDI | SCORE}
GRID = {'eighth': 2, 'sixteenth': 4, 'eighth-triplet': 3, 'sixteenth-triplet': 6, 'thirty-second': 8}
DATA = Path(os.environ.get('KOBI_MUSIC_DATA', Path(__file__).parents[1] / 'runtime')).resolve()
BUILTIN = DATA / 'banks' / sound.BUILTIN_NAME
MICROSCOPIC = DATA / 'banks' / kobi_bank.ARCHIVE


class Options(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    pages: str = Field(default='', max_length=48)
    detector: Literal['28m', '2m'] = '28m'
    device: Literal['auto', 'cuda', 'cpu'] = 'auto'
    grid: Literal['eighth', 'sixteenth', 'eighth-triplet', 'sixteenth-triplet', 'thirty-second'] | None = None
    strength: float = Field(default=1.0, ge=0, le=1)
    bpm: float | None = Field(default=None, ge=20, le=360)
    downbeat: float = Field(default=0, ge=0, le=3600)
    beats: list[float] | None = Field(default=None, min_length=2, max_length=12000)
    meter: str | None = Field(default=None, max_length=8)
    sheet: bool = False
    render: bool = False
    audio_format: Literal['wav', 'flac', 'mp3'] = 'wav'
    soundfont_bank: Literal['musescore', 'kobi-microscopic'] = 'musescore'
    soundfont_url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode='after')
    def timing_is_consistent(self):
        if self.bpm is not None and self.beats is not None:
            raise ValueError('Choose a fixed BPM or a list of beat times.')
        if self.downbeat and self.bpm is None:
            raise ValueError('A first downbeat in seconds requires a fixed BPM. A beat list already sets its own origin.')
        if self.beats and (self.beats[0] < 0 or any(not 60 / 360 <= end - start <= 3 for start, end in zip(self.beats, self.beats[1:]))):
            raise ValueError('Beat times must be increasing absolute quarter-note times with intervals from 20 to 360 BPM.')
        if self.meter and not re.fullmatch(r'(?:[1-9]|[12][0-9]|3[0-2])/(?:1|2|4|8|16|32)', self.meter):
            raise ValueError('Use a time signature such as 4/4 or 6/8.')
        return self


def musescore():
    configured = os.environ.get('KOBI_MUSESCORE')
    if configured and Path(configured).is_file():
        return configured
    installed = next((path for name in ('MuseScore4', 'MuseScore3', 'musescore', 'mscore') if (path := shutil.which(name))), None)
    if installed:
        return installed
    for folder in ('MuseScore 4', 'MuseScore 3'):
        exe = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / folder / 'bin' / (folder.replace(' ', '') + '.exe')
        if sys.platform == 'win32' and exe.is_file():
            return str(exe)
    if sys.platform == 'darwin':
        app = Path('/Applications/MuseScore 4.app/Contents/MacOS/mscore')
        if app.is_file():
            return str(app)
    return None


def run_command(command, log, *, timeout=1800):
    process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=timeout)
    if process.returncode:
        raise RuntimeError(f'{Path(command[0]).name} exited with code {process.returncode}. See the job log.')


def convert_score(source, destination, log):
    exe = musescore()
    if exe:
        env = os.environ.copy()
        if sys.platform.startswith('linux'):
            env.setdefault('QT_QPA_PLATFORM', 'offscreen')
        subprocess.run([exe, '-o', str(destination), str(source)], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240, check=True)
    elif source.suffix.lower() in {'.xml', '.musicxml'} and destination.suffix == '.mid':
        import verovio

        score = verovio.toolkit()
        if not score.loadFile(str(source)):
            raise ValueError('Verovio could not read this MusicXML.')
        destination.write_bytes(base64.b64decode(score.renderToMIDI()))
    else:
        raise RuntimeError('This conversion needs MuseScore Studio. Install it or set KOBI_MUSESCORE to its executable.')
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError('The score converter did not write an output. See the job log.')


def preview_score(source, destination):
    import verovio

    score = verovio.toolkit()
    score.setOptions({'pageWidth': 1600, 'pageHeight': 2200, 'scale': 40, 'adjustPageHeight': True})
    if score.loadFile(str(source)) and score.getPageCount():
        destination.write_text(score.renderToSVG(1), encoding='utf-8')


def scan_score(source, scratch, outputs, options, log, warnings):
    from PIL import Image

    if source.suffix.lower() == '.pdf':
        import pymupdf

        with pymupdf.open(source) as doc:
            page_range = options.pages.strip()
            if page_range and not re.fullmatch(r'[1-9][0-9]*(?:-[1-9][0-9]*)?', page_range):
                raise ValueError('Use a PDF page or range such as 2 or 2-5. Blank reads all pages.')
            start, _, stop = page_range.partition('-')
            first, last = (int(start), int(stop or start)) if start else (1, len(doc))
            if not 1 <= first <= last <= len(doc):
                raise ValueError(f'The PDF has {len(doc)} page(s). Choose a range inside the document.')
            pages = []
            for page_index in range(first, last + 1):
                page = doc[page_index - 1]
                scale = min(3.0, 2800 / max(page.rect.width, page.rect.height))
                path = scratch / f'page-{page_index:04d}.png'
                page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(path)
                pages.append(path)
    else:
        path = scratch / 'page-0001.png'
        with Image.open(source) as image:
            image.convert('RGB').save(path)
        pages = [path]

    import torch

    device = ('cuda' if torch.cuda.is_available() else 'cpu') if options.device == 'auto' else options.device
    if device == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable. Use Auto or CPU.')
    # Pass file paths through a list file to stay within Windows command-line limits on long PDFs.
    page_list = scratch / 'pages.json'
    page_list.write_text(json.dumps([str(path) for path in pages]), encoding='utf-8')
    run_command([sys.executable, '-m', 'kobi_music.scan_worker', str(page_list), str(outputs), device, options.detector], log)

    valid = [path for path in sorted(outputs.glob('page-*.musicxml')) if ET.parse(path).find('./part/measure') is not None]
    if not valid:
        raise ValueError('No readable five-line staff was found. Numbered notation (jianpu) needs a separate reader.')
    if len(valid) < len(pages):
        warnings.append(f'{len(pages) - len(valid)} page(s) contained no readable staves.')
    if len(valid) > 1:
        combined = outputs / 'score.musicxml'
        if join_pages(valid, combined):
            warnings.append('Page scores were joined by part order. Review system changes, repeats and ties across page breaks.')
            return [combined]
        warnings.append('Pages contain different part layouts. Individual-page scores are available for playback.')
    return valid


def join_pages(files, output):
    root = ET.parse(files[0]).getroot()
    header = root.findall('./part')
    for path in files[1:]:
        page = ET.parse(path).getroot()
        parts = page.findall('./part')
        if len(parts) != len(header):
            return False
        for part, continuation in zip(header, parts):
            for measure in continuation.findall('measure'):
                part.append(deepcopy(measure))
    for part in header:
        for number, measure in enumerate(part.findall('measure'), start=1):
            measure.set('number', str(number))
    ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)
    return True


def execute(task, source, results, options, *, font=None, log, scratch=None, progress=lambda _stage: None):
    if source.suffix.lower() not in TASKS[task]:
        raise ValueError(f'File type {source.suffix or "(none)"} cannot be used for {task}.')
    results.mkdir(parents=True, exist_ok=True)
    scratch = scratch or results.parent / 'work'
    scratch.mkdir(exist_ok=True)
    warnings = []
    midi_files = []
    scores = []
    if task == 'transcribe':
        progress('Transcribing audio')
        from dettato.pipeline import transcribe

        res = transcribe(str(source), device=None if options.device == 'auto' else options.device)
        if not res.tracks:
            raise ValueError('Dettato found no playable notes.')
        raw = results / 'performance.mid'
        res.save_midi(str(raw))
        midi_files = [raw]
        summary = res.summary()
        summary['source'] = source.name
        summary['velocity'] = {'pitched': 'onset confidence proxy', 'drums': 'learned estimate when available'}
        (results / 'transcription.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        (results / 'beat-suggestions.json').write_text(json.dumps(midi.pulse_suggestions(raw), indent=2), encoding='utf-8')
    elif task == 'scan':
        progress('Reading staff notation')
        scores = scan_score(source, scratch, results, options, log, warnings)
    elif source.suffix.lower() in MIDI:
        midi_files = [source]
    elif source.suffix.lower() in {'.xml', '.musicxml'}:
        scores = [source]
    else:
        progress('Exporting the score')
        xml = results / 'score.musicxml'
        convert_score(source, xml, log)
        scores = [xml]
        # Read the native score again for MIDI so playback settings survive the MusicXML export.
        output = results / 'score.mid'
        convert_score(source, output, log)
        midi_files = [output]

    if task in {'transcribe', 'quantize'} and (task == 'quantize' or options.grid or options.bpm or options.beats or options.meter):
        progress('Putting notes on the beat grid')
        edited = results / 'quantized.mid'
        midi.quantize(midi_files[0], edited, division=GRID[options.grid or 'sixteenth'], strength=options.strength,
                      bpm=options.bpm, downbeat=options.downbeat, beats=options.beats,
                      meter=tuple(map(int, options.meter.split('/'))) if options.meter else None)
        midi_files = [edited]
    if (options.sheet or task == 'convert') and not scores:
        progress('Engraving the MIDI as sheet music')
        xml = results / 'score.musicxml'
        convert_score(midi_files[0], xml, log)
        scores = [xml]
        warnings.append('MIDI engraving estimates voice layout and notation. Check pickup, slurs, dynamics and repeats in the score editor.')
    if scores and not midi_files:
        progress('Converting score to MIDI')
        for index, score in enumerate(scores, 1):
            output = results / ('score.mid' if len(scores) == 1 else f'score-{index:02d}.mid')
            try:
                convert_score(score, output, log)
            except (RuntimeError, subprocess.SubprocessError) as exc:
                if task != 'scan' or options.render:
                    raise
                warnings.append(f'MusicXML was saved. MIDI export failed: {exc}')
                break
            midi_files.append(output)
    if scores:
        preview_score(scores[0], results / 'score-preview.svg')

    if options.render or task == 'render':
        progress('Rendering audio with the SoundFont')
        packed = options.soundfont_bank == 'kobi-microscopic'
        if (font and options.soundfont_url) or (packed and (font or options.soundfont_url)):
            raise ValueError('Choose one built-in bank, local SoundFont or SoundFont URL.')
        bank = MICROSCOPIC if packed else (font or (sound.download_font(options.soundfont_url, scratch / 'selected.sf3') if options.soundfont_url else BUILTIN))
        if not bank.is_file():
            raise ValueError('The built-in SoundFont is missing. Run Pinokio Install or choose a SoundFont.')
        for index, source_midi in enumerate(midi_files, 1):
            label = 'audio' if len(midi_files) == 1 else f'audio-{index:02d}'
            wav = (results if options.audio_format == 'wav' else scratch) / f'{label}.wav'
            renderer = kobi_bank.render if packed else sound.render
            warnings.extend(renderer(source_midi, bank, wav))
            if options.audio_format != 'wav':
                run_command(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(wav), str(results / f'{label}.{options.audio_format}')], log)

    return {'files': sorted(path.name for path in results.iterdir() if path.is_file()), 'warnings': warnings,
            'midi': [{'name': path.name, **midi.inspect(path)} for path in midi_files]}


def capabilities():
    return {'operations': {task: sorted(inputs) for task, inputs in TASKS.items()}, 'grid': list(GRID),
            'musescore': bool(musescore()), 'builtin_banks': {'musescore': BUILTIN.is_file(), 'kobi-microscopic': MICROSCOPIC.is_file()},
            'soundfont_types': ['.sf2', '.sf3'], 'audio_formats': ['wav', 'flac', 'mp3']}
