"""Offline renderer for the published Kobi Microscopic bank's packed SFZ regions."""

from collections import defaultdict, deque
from functools import lru_cache
from io import BytesIO
import posixpath
import re
import shutil
import subprocess
from urllib.request import Request, urlopen
import wave
from zipfile import ZipFile

import mido
import numpy as np
import soundfile


ARCHIVE = 'kobi-microscopic.zip'
URL = 'https://kobi.music/media/soundbank/' + ARCHIVE
ROOT = 'kobi_microscopic/'


def download(target):
    partial = target.with_suffix('.partial')
    try:
        limit = 12 * 1024 * 1024
        curl = shutil.which('curl')
        if curl:
            subprocess.run([curl, '--fail', '--location', '--silent', '--show-error', '--max-time', '45',
                            '--max-filesize', str(limit), '--output', str(partial), URL], check=True)
            content = partial.read_bytes()
        else:
            request = Request(URL, headers={'User-Agent': 'Kobi-Music-Toolkit/0.1'})
            with urlopen(request, timeout=30) as response:
                content = response.read(limit + 1)
        if len(content) > 12 * 1024 * 1024:
            raise ValueError('The Microscopic bank exceeds the expected download size.')
        with ZipFile(BytesIO(content)) as archive:
            names = archive.namelist()
            if ROOT + 'ATTRIBUTION.md' not in names or sum(name.endswith('.sfz') for name in names) != 129:
                raise ValueError('The Microscopic archive has an unexpected format.')
        if not curl:
            partial.write_bytes(content)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def regions(archive, path):
    text = re.sub(r'//[^\n]*', '', archive.read(path).decode('utf-8'))
    parts = re.split(r'<(\w+)>', text)[1:]
    default_path = ''
    global_values = {}
    found = []
    for kind, data in zip(parts[::2], parts[1::2]):
        values = dict(re.findall(r'(\w+)=([^\s]+)', data))
        if kind == 'control':
            default_path = values.get('default_path', '')
        elif kind == 'global':
            global_values = values
        elif kind == 'region':
            region = {**global_values, **values}
            sample = posixpath.normpath(posixpath.join(posixpath.dirname(path), default_path, region['sample']))
            if not sample.startswith(ROOT):
                raise ValueError('Invalid Microscopic sample path.')
            region['sample'] = sample
            found.append(region)
    return found


def events(midi):
    programs = defaultdict(int)
    active = defaultdict(deque)
    time = 0.0
    for msg in midi:
        time += msg.time
        if msg.type == 'program_change':
            programs[msg.channel] = msg.program
        elif msg.type in ('note_on', 'note_off'):
            key = msg.channel, msg.note
            if msg.type == 'note_on' and msg.velocity:
                active[key].append((time, msg.velocity, -1 if msg.channel == 9 else programs[msg.channel]))
            elif active[key]:
                start, velocity, program = active[key].popleft()
                yield start, time - start, msg.note, velocity, program
    for (_channel, note), pending in active.items():
        for start, velocity, program in pending:
            yield start, time - start, note, velocity, program


def matching_regions(table, note, velocity, drums):
    layers = [region for region in table if int(region.get('lovel', 1)) <= velocity <= int(region.get('hivel', 127))]
    selected = [region for region in layers
                if int(region.get('lokey', region.get('key', 0))) <= note <= int(region.get('hikey', region.get('key', 127)))]
    if selected or drums or not layers:
        return selected
    root = min((int(region['pitch_keycenter']) for region in layers), key=lambda key: abs(note - key))
    return [region for region in layers if int(region['pitch_keycenter']) == root]


def add_voice(mix, bank, region, start, duration, note, velocity, rate):
    samples, src_rate = bank(region['sample'])
    offset = int(region.get('offset', 0))
    finish = min(len(samples), int(region.get('end', len(samples) - 1)) + 1)
    center = int(region.get('pitch_keycenter', region.get('key', note)))
    pitch = (note - center) * float(region.get('pitch_keytrack', 100)) / 100 + float(region.get('tune', 0)) / 100
    step = src_rate / rate * 2 ** (pitch / 12)
    release = min(1.0, float(region.get('ampeg_release', .15)))
    mode = region.get('loop_mode', 'no_loop')
    length = min(len(mix) - start, round((duration + release) * rate))
    if mode == 'one_shot':
        length = min(len(mix) - start, round(max(0, finish - offset - 1) / step))
    elif mode != 'loop_continuous':
        length = min(length, round(max(0, finish - offset - 1) / step))
    if length <= 0:
        return
    t = np.arange(length, dtype=np.float64) / rate
    positions = offset + step * rate * t
    if mode == 'loop_continuous':
        left, right = int(region['loop_start']), int(region['loop_end'])
        if right > left:
            past = positions > right
            positions[past] = left + (positions[past] - left) % (right - left + 1)
    indices = np.minimum(positions.astype(int), finish - 1)
    fraction = (positions - indices)[:, None]
    audio = samples[indices] * (1 - fraction) + samples[np.minimum(indices + 1, finish - 1)] * fraction
    sustain = float(region.get('ampeg_sustain', 100)) / 100
    decay = float(region.get('ampeg_decay', 0))
    envelope = np.ones(length)
    if decay > 0:
        envelope -= (1 - sustain) * np.clip((t - float(region.get('ampeg_hold', 0))) / decay, 0, 1)
    if mode != 'one_shot':
        envelope *= np.clip(1 - (t - duration) / max(.005, release), 0, 1)
    pan = float(region.get('pan', 0)) / 100
    gain = 10 ** (float(region.get('volume', 0)) / 20) * (velocity / 127) ** 1.5
    mix[start:start + length] += (envelope * gain)[:, None] * audio * np.array([min(1, 1 - pan), min(1, 1 + pan)])


def render(source, archive_path, destination, rate=44100):
    midi = mido.MidiFile(source)
    duration = midi.length
    if duration > 900:
        raise ValueError('Split MIDI longer than 15 minutes for the packed bank, or select an SF2/SF3 SoundFont.')
    mix = np.zeros((round((duration + 1) * rate), 2), dtype=np.float32)
    with ZipFile(archive_path) as archive:
        names = {int(path.rsplit('/', 1)[-1][:3]): path for path in archive.namelist()
                 if re.search(r'/GM/\d{3} .+\.sfz$', path)}
        names[-1] = ROOT + 'GM/Drums.sfz'
        instruments = {}

        @lru_cache(maxsize=32)
        def bank(sample):
            return soundfile.read(BytesIO(archive.read(sample)), dtype='float32', always_2d=True)

        for start, length, note, velocity, program in events(midi):
            if program not in instruments:
                instruments[program] = regions(archive, names[program])
            for region in matching_regions(instruments[program], note, velocity, program == -1):
                add_voice(mix, bank, region, round(start * rate), length, note, velocity, rate)
    peak = float(np.abs(mix).max())
    if not peak:
        raise ValueError('The selected bank produced no audible notes.')
    scale = min(.38, .95 / peak) * 32767
    with wave.open(str(destination), 'wb') as audio:
        audio.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        for start in range(0, len(mix), rate):
            audio.writeframesraw((mix[start:start + rate] * scale).astype('<i2').tobytes())
    return ['Kobi Microscopic playback uses the bank’s sample ranges, loops and envelopes. Use SF2/SF3 for MIDI sustain, controllers or pitch bend.']
