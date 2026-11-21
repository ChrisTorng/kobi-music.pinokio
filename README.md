# Kobi Music Toolkit for Pinokio

An independent, local toolkit built on Dettato and Copista/Copisteria. The web interface, CLI and API use the same workflows. Recordings, scores and outputs stay on your machine.

| Workflow | Input | Outputs |
| --- | --- | --- |
| Transcribe | WAV, FLAC, MP3, M4A, AAC, AIFF, Ogg or Opus | Performance MIDI, track/velocity summary and pulse suggestions. Optionally quantize, engrave or render. |
| Scan | PDF or score image | MusicXML, annotated readings and MIDI. An empty PDF range reads all pages. Optionally render the score to audio. |
| Quantize | MIDI | A second MIDI on the selected grid. Optionally export MusicXML or a listening copy. |
| Convert | MusicXML, MuseScore or MIDI | Score-to-MIDI or MIDI-to-MusicXML, with a score preview. |
| Render | MusicXML, MuseScore or MIDI | WAV, FLAC or MP3. Score inputs also produce MIDI. |

## Pinokio

Download `https://github.com/ChrisTorng/kobi-music.pinokio` in Pinokio and select **Install**, then **Start**. The launcher uses the development bundle for Node, Git, uv and FFmpeg. The installer sets up a private Python 3.12 environment and chooses its own compatible PyTorch wheel. Copista weights are downloaded at install. Dettato weights are cached the first time you transcribe.

Install MuseScore Studio for `.mscz`, `.mscx` and MIDI-to-MusicXML. MusicXML-to-MIDI can fall back to Verovio. `KOBI_MUSESCORE` can point to a custom MuseScore executable. MuseScore 3 and 4 may interpret the same score's playback directions differently. FLAC and MP3 output need FFmpeg. The web server listens on loopback. On Pinokio, use the URL shown in its menu or `pterm status kobi-music.pinokio`.

## Timing and notation

- Dettato keeps source time as performance MIDI. The 120 BPM MIDI header is a time encoding, not the recording's tempo. The toolkit reports possible pulses separately. Harmonics such as half or double time can appear in the report. Choose the intended BPM, meter and first full downbeat before quantizing an audio transcription.
- For rubato or ritardando, pass a JSON list of absolute **quarter-note beat times**. The first entry defines the downbeat; successive intervals become MIDI tempo events. Use fixed BPM plus `--downbeat` for an even grid. Without a new grid or beat map, **Quantize** retains the MIDI tempo map. Strength can range from 0 to 1; choose eighths, sixteenths, triplets or thirty-seconds. Timing and MIDI velocities are separate.
- Native MuseScore files go directly to the MuseScore MIDI exporter and also get a separate MusicXML export. Numeric tempo instructions and playable repeats in a score can affect the rendered MIDI. A written `rit.` without timing information is not enough to recover a specific curve. MIDI import can produce editable notation, but repeat structure, pickup spelling, voices, slurs and expressive instructions need review. The toolkit does not infer repeats, lyrics, or fingering from recordings.
- Copista recognizes five-line notation, including dynamics, repeat signs and related symbols. Copisteria corrects the result in context. The toolkit doesn't scan numbered notation. This workflow doesn't run text OCR or align lyrics. Multi-page scans join pages with equal part counts by order and preserve the individual page files for review.

## SoundFonts

The default is **MuseScore General**, a GM SF3 bank based on FluidR3, available offline after installation. **Kobi Microscopic** is another built-in selection downloaded from Kobi's published archive. Its packed SFZ/Ogg renderer implements note ranges, tuning, layers, loops and volume envelopes. The SF2/SF3 engine is the choice for MIDI sustain, pitch bend and controller playback. You can upload an SF2/SF3 or give a direct public HTTPS URL. Local URL endpoints and private network addresses are excluded; use file upload for a private bank.

- [MuseScore General bank, sources and license](https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/)
- [Kobi GM banks, download and per-program attribution](https://kobi.music/research/a-general-midi-bank-in-20mb)

The original Kobi Microscopic archive contains its `ATTRIBUTION.md`. The download is made during installation and the audio assets aren't in this Git repository. Kobi Slim v2 has different attribution requirements and some samples with uncertain provenance. The app doesn't install that bank.

## CLI

Run `kobi-music` from `app/.venv` (`Scripts/kobi-music.exe` on Windows, `bin/kobi-music` on Linux). Commands write JSON to stdout and logs in the output directory. Choose a new or empty output directory.

```text
kobi-music capabilities
kobi-music transcribe recording.wav -o takes
kobi-music scan score.pdf -o scanned --render
kobi-music quantize performance.mid -o score --bpm 135 --meter 4/4 --downbeat 1.78 --sheet
kobi-music quantize performance.mid -o rubato --beats quarter-note-times.json --grid eighth-triplet --sheet
kobi-music convert score.mscz -o exports
kobi-music render score.musicxml -o listen --soundfont-bank kobi-microscopic
kobi-music render score.mid -o custom --soundfont my-bank.sf2 --audio-format flac
kobi-music render score.mid -o url --soundfont-url https://example.org/soundfont.sf2
```

## Agent HTTP API

`GET /docs` and `/openapi.json` describe the HTTP endpoints. `GET /v1/capabilities` lists supported operations and installed engines. `GET /v1/options-schema` returns the JSON schema for options, shared with the CLI `--options` file. `POST /v1/jobs` takes multipart fields `task`, `file`, `options` (JSON string), and optional `soundfont` (file). It returns a job ID. Poll `GET /v1/jobs/{id}` until `done` or `failed`, then download named outputs via `GET /v1/jobs/{id}/files/{name}`. Errors include a message and the `log.txt` endpoint. Recent jobs remain available after restart.

```sh
curl -F 'task=render' -F 'file=@score.musicxml' \
  -F 'options={"audio_format":"wav","soundfont_bank":"kobi-microscopic"}' \
  http://127.0.0.1:50883/v1/jobs
```

The example port is the default for `kobi-music serve`. Substitute the ready URL when Pinokio chooses a port.

## Upstream capabilities

See [Kobi tools and model notes](UPSTREAM.md) for the hosted Workspace, separate model stages, and the difference between note confidence, learned drum velocity and staff dynamics.
