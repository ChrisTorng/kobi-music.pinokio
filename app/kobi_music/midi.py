"""Transform MIDI timing without discarding programs, controllers or velocities."""

from bisect import bisect_right
from collections import defaultdict, deque
from math import ceil

import mido
import numpy as np


def tempo_clock(midi):
    changes = {0: 500000}
    tick = 0
    for message in mido.merge_tracks(midi.tracks):
        tick += message.time
        if message.type == 'set_tempo':
            changes[tick] = message.tempo
    ticks = sorted(changes)
    seconds = [0.0]
    for start, stop in zip(ticks, ticks[1:]):
        seconds.append(seconds[-1] + mido.tick2second(stop - start, midi.ticks_per_beat, changes[start]))

    def at(tick):
        i = bisect_right(ticks, tick) - 1
        return seconds[i] + mido.tick2second(tick - ticks[i], midi.ticks_per_beat, changes[ticks[i]])

    return at


def quantize(source, destination, *, division, strength, bpm=None, downbeat=0.0, beats=None, meter=None):
    original = mido.MidiFile(source)
    if original.type == 2:
        raise ValueError('Independent MIDI type-2 sequences have no common timeline.')
    clock = tempo_clock(original)
    reset_timing = bpm is not None or beats is not None
    resolution = 480 if reset_timing else original.ticks_per_beat
    step = resolution / division
    output = mido.MidiFile(type=1, ticks_per_beat=resolution)
    if reset_timing:
        anchors = beats or [downbeat, downbeat + 60 / bpm]
        intervals = [b - a for a, b in zip(anchors, anchors[1:])]
        starts = []
        for track in original.tracks:
            tick = 0
            for message in track:
                tick += message.time
                if message.type == 'note_on' and message.velocity:
                    starts.append(clock(tick))
                    break
        first_note = min(starts, default=anchors[0])
        pickup = max(0, ceil((anchors[0] - first_note) / intervals[0] - 1e-8))

        def map_tick(tick):
            seconds = clock(tick)
            i = min(len(intervals) - 1, max(0, bisect_right(anchors, seconds) - 1))
            return max(0, (i + (seconds - anchors[i]) / intervals[i] + pickup) * resolution)

        timing = [(0, mido.MetaMessage('set_tempo', tempo=round(intervals[0] * 1_000_000)))]
        if pickup:
            timing.append((pickup * resolution, mido.MetaMessage('marker', text='First full downbeat')))
        timing.extend((int((i + pickup) * resolution), mido.MetaMessage('set_tempo', tempo=round(interval * 1_000_000)))
                      for i, interval in enumerate(intervals[1:], 1) if abs(interval - intervals[i - 1]) > 1e-6)
    else:
        def map_tick(tick):
            return tick

        timing = []

    if meter:
        timing.append((0, mido.MetaMessage('time_signature', numerator=meter[0], denominator=meter[1])))
    if timing:
        append_track(output, timing)

    for track in original.tracks:
        events = []
        active = defaultdict(deque)
        tick = 0
        for message in track:
            tick += message.time
            if message.type == 'end_of_track' or (reset_timing and message.type == 'set_tempo'):
                continue
            if meter and message.type == 'time_signature':
                continue
            position = map_tick(tick)
            if message.type in ('note_on', 'note_off'):
                key = message.channel, message.note
                position += (round(position / step) * step - position) * strength
                if message.type == 'note_on' and message.velocity:
                    active[key].append(position)
                elif active[key]:
                    position = max(position, active[key].popleft() + max(1, step * strength))
            events.append((round(position), message))
        append_track(output, events)
    output.save(destination)


def append_track(midi, events):
    track = midi.add_track()
    previous = 0
    for tick, message in sorted(events, key=lambda event: event[0]):
        track.append(message.copy(time=tick - previous))
        previous = tick


def inspect(path):
    midi = mido.MidiFile(path)
    elapsed = 0.0
    tempo = []
    meter = []
    for message in midi:
        elapsed += message.time
        if message.type == 'set_tempo':
            tempo.append({'seconds': round(elapsed, 4), 'bpm': round(mido.tempo2bpm(message.tempo), 3)})
        elif message.type == 'time_signature':
            meter.append({'seconds': round(elapsed, 4), 'meter': f'{message.numerator}/{message.denominator}'})
    tracks = []
    for track in midi.tracks:
        notes = [message for message in track if message.type == 'note_on' and message.velocity]
        if notes:
            velocities = [note.velocity for note in notes]
            tracks.append({'name': track.name.rstrip('\x00'), 'notes': len(notes), 'velocity_range': [min(velocities), max(velocities)],
                           'programs': sorted({m.program for m in track if m.type == 'program_change'}),
                           'drums': any(note.channel == 9 for note in notes)})
    return {'seconds': round(elapsed, 3), 'tempos': tempo, 'meters': meter, 'tracks': tracks}


def pulse_suggestions(path):
    """Propose periodic pulses, with no assumptions about which beat starts a bar."""
    midi = mido.MidiFile(path)
    times = []
    drums = []
    elapsed = 0.0
    for msg in midi:
        elapsed += msg.time
        if elapsed > 300:
            break
        if msg.type == 'note_on' and msg.velocity:
            (drums if msg.channel == 9 else times).append(elapsed)
    events = drums if len(drums) >= 16 else times
    candidates = []
    if len(events) >= 16 and events[-1] - events[0] >= 8:
        hz = 200
        bins = np.bincount(np.rint(np.asarray(events) * hz).astype(int))
        signal = np.minimum(bins, 3).astype(float)
        signal -= signal.mean()
        freq = np.fft.rfft(signal, n=2 * len(signal))
        corr = np.fft.irfft(abs(freq) ** 2)
        lags = [lag for lag in range(round(60 * hz / 215), round(60 * hz / 45))
                if corr[lag] >= max(corr[lag - 1], corr[lag + 1]) and corr[lag] > 0]
        for lag in sorted(lags, key=lambda i: corr[i], reverse=True)[:5]:
            left, center, right = corr[lag - 1:lag + 2]
            curvature = left - 2 * center + right
            offset = .5 * (left - right) / curvature if curvature else 0
            candidates.append({'bpm': round(60 * hz / (lag + offset), 2), 'periodicity': round(float(center / corr[0]), 3)})
    return {'method': 'MIDI onset autocorrelation, first five minutes', 'source': 'drums' if events is drums else 'pitched notes',
            'candidates': candidates, 'downbeat': None, 'meter': None}
