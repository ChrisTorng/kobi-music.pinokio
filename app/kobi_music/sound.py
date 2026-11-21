"""Fetch and render local SoundFont assets."""

from contextlib import closing
from http.client import HTTPSConnection
from ipaddress import ip_address
from pathlib import Path
import socket
import wave
from urllib.parse import quote, urljoin, urlsplit

import mido
import numpy as np


MAX_FONT_BYTES = 256 * 1024 * 1024
BUILTIN_URL = 'https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/MuseScore_General.sf3'
BUILTIN_NAME = 'MuseScore_General.sf3'


def check_font(path):
    with path.open('rb') as handle:
        header = handle.read(12)
    if header[:4] != b'RIFF' or header[8:12] != b'sfbk':
        raise ValueError('The SoundFont must be a valid .sf2 or .sf3 file.')
    if path.stat().st_size > MAX_FONT_BYTES:
        raise ValueError('SoundFont exceeds 256 MiB.')


def download_font(url, target):
    temporary = target.with_suffix('.partial')
    try:
        for _ in range(5):
            address = urlsplit(url)
            if (address.scheme != 'https' or not address.hostname or address.username or address.password
                    or address.port not in (None, 443)):
                raise ValueError('Use a direct public HTTPS URL for a SoundFont.')
            host = address.hostname.encode('idna').decode('ascii')
            ips = tuple(dict.fromkeys(result[4][0] for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
            if not ips or any(not ip_address(ip).is_global for ip in ips):
                raise ValueError('SoundFont URLs must resolve to public addresses.')
            path = quote(address.path or '/', safe="/%!$&'()*+,;=:@")
            query = quote(address.query, safe="/%!$&'()*+,;=:@?")
            if query:
                path += '?' + query
            with closing(HTTPSConnection(host, 443, timeout=30)) as connection:
                def connect(_address, timeout, source_address):
                    last = None
                    for ip in ips:
                        try:
                            return socket.create_connection((ip, 443), timeout, source_address)
                        except OSError as error:
                            last = error
                    raise last

                connection._create_connection = connect
                connection.request('GET', path, headers={'User-Agent': 'Kobi-Music-Toolkit/0.1', 'Accept-Encoding': 'identity'})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308) and response.getheader('Location'):
                    url = urljoin(url, response.getheader('Location'))
                    continue
                if response.status != 200:
                    raise ValueError(f'SoundFont server replied with HTTP {response.status}.')
                size = 0
                with temporary.open('wb') as file:
                    while block := response.read(1024 * 1024):
                        size += len(block)
                        if size > MAX_FONT_BYTES:
                            raise ValueError('SoundFont exceeds 256 MiB.')
                        file.write(block)
                check_font(temporary)
                temporary.replace(target)
                return target
        raise ValueError('The SoundFont URL redirects too many times.')
    finally:
        temporary.unlink(missing_ok=True)


def render(midi_path, font_path, output, *, rate=44100):
    from tinysoundfont import Synth

    check_font(font_path)
    midi = mido.MidiFile(midi_path)
    if midi.length > 3600:
        raise ValueError('Split MIDI longer than one hour before rendering.')
    synth = Synth(gain=-8, samplerate=rate)
    font_id = synth.sfload(str(font_path))
    fallbacks = set()
    used = {message.channel for track in midi.tracks for message in track if message.type == 'note_on' and message.velocity}
    default_program = next((program for program in range(128) if synth.sfpreset_name(font_id, 0, program)), 0)
    for channel in used:
        try:
            synth.program_select(channel, font_id, 0, 0 if channel == 9 else default_program, channel == 9)
        except RuntimeError:
            fallbacks.add(f'Channel {channel + 1} has no matching preset in the SoundFont.')
            synth.program_select(channel, font_id, 0, default_program)

    with wave.open(str(output), 'wb') as wav:
        wav.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))

        def emit(frames):
            while frames > 0:
                block = min(frames, rate)
                samples = np.frombuffer(synth.generate_simple(block), dtype=np.float32)
                pcm = (np.clip(samples, -1, 1) * 32767).astype('<i2')
                wav.writeframesraw(pcm.tobytes())
                frames -= block

        elapsed = 0.0
        written = 0
        for message in midi:
            elapsed += message.time
            frame = round(elapsed * rate)
            emit(frame - written)
            written = frame
            channel = getattr(message, 'channel', None)
            if channel not in used:
                continue
            if message.type == 'note_on' and message.velocity:
                synth.noteon(channel, message.note, message.velocity)
            elif message.type in ('note_on', 'note_off'):
                synth.noteoff(channel, message.note)
            elif message.type == 'program_change':
                try:
                    synth.program_change(channel, message.program, channel == 9)
                except RuntimeError:
                    fallbacks.add(f'Channel {channel + 1} program {message.program + 1} used the previous preset.')
            elif message.type == 'control_change':
                synth.control_change(channel, message.control, message.value)
            elif message.type == 'pitchwheel':
                synth.pitchbend(channel, message.pitch + 8192)
        synth.notes_off()
        emit(rate)
    return sorted(fallbacks)
