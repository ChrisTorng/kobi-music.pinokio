# Kobi Workspace and the local toolkit

The two earlier launchers wrapped one operation each. Kobi's [Workspace](https://kobi.music/workspace) connects operations in reusable workflows. Its [node reference](https://kobi.music/workspace/learn/nodes), [flow format](https://kobi.music/workspace/learn/flows), [HTTP API](https://kobi.music/workspace/learn/api) and [MCP agent setup](https://kobi.music/workspace/learn/agents) document the hosted service. The local toolkit implements independent UI, HTTP and CLI workflows, with no Kobi account needed.

| Component | What it does |
| --- | --- |
| Dettato transcriber | Estimates pitch and note start/end in performed time, including simultaneous notes. The pipeline estimates tuning relative to A440. |
| Dettato evidence repairer | Uses the transcriber's evidence to change note boundaries, remove false notes and recover missed notes. |
| Dettato grouper | Infers instrument tracks and GM labels; similar timbres, overlapping notes and vocals can be assigned to the wrong track. |
| Dettato drums | Estimates drum-kit and orchestral percussion hits and velocity with a dedicated head. The open pipeline runs it only when the source rate is at least 40 kHz. Upsampling a low-rate recording doesn't restore lost information. |
| Copista | Its 28.7M and 1.94M detectors find staff symbols. Upstream calls them mini and micro in the hosted UI. The detectors are shared with Copisteria. |
| Copisteria | Approximately 2M additional parameters read the detector evidence in context, including note durations, voices, measures, repeats, articulations and dynamics. Separate OCR text boxes may supply titles, part names and expressions. The local reader doesn't create those boxes. |

Dettato's pitched velocity in the checked open revision comes from the note-onset confidence used by the system. That is different from estimating the player's force or extracting a written `p` or `f`. Audio loudness also depends on the instrument, microphone and mix. Copista dynamics are visual markings on a score and can be read as notation. A MIDI `note-on` velocity field stores a value; its existence alone doesn't say how that value was obtained.

The hosted audio-to-MIDI node documents **Dettato Micro** (6M), 10 instrument families and beat alignment enabled by default. The pinokio toolkit runs the open Dettato pipeline and exposes its beat handling separately. The hosted **Find beats** emits beats, bars and time signatures. **Beat align** builds a grid from MIDI, and **Fit MIDI to beats** applies a beat map. **Dehumanize** follows alignment and regularizes passages and chords while aiming to preserve grace notes. That is a distinct stage after note recognition. The public workflow documentation describes behavior, without specifying whether the hosted refinement uses learned components. Here the explicit MIDI quantizer is deterministic and releases no claim of parity with the hosted refinement.

The hosted Workspace also covers document→score, score→MIDI, MIDI→sheet music with optional experimental chord symbols, part-books, batch/ZIP workflows, browser previews and automation chaining. Local PDF/image→score→MIDI→audio, MIDI→score and configurable beat-grid workflows cover the single-workflow paths. Jobs expose intermediate artifacts so an Agent can chain further processing.

## Other Kobi research

- [The GM bank](https://kobi.music/research/a-general-midi-bank-in-20mb) assembles and compresses several sample libraries into 128 programs and a drum kit. The two published archives are packed SFZ/Ogg, with an index for fetching individual notes by byte range. Kobi compiled and compressed these banks. The underlying recordings have multiple sources. The toolkit supports Microscopic directly and standard SF2/SF3 separately.
- [Babymaker](https://github.com/kobimusic/babymaker) blends sample timbres in the DCT domain, including attack, tone and decay. Kobi used timbre variations to broaden Dettato's training data. This is a separate sample-design workflow.
- [Kobi's earlier MIDI generation research](https://kobi.music/research) includes Maestro and symbolic MIDI generation. It addresses composing material, separate from transcription and playback.

Sources: [Dettato and reproducible benchmarks](https://github.com/kobimusic/dettato), [pitched repair and velocity implementation](https://github.com/kobimusic/dettato/blob/9b724251794f2bbd5eaa43e54734e5a251829130/src/dettato/evidence/repair.py), [drum model](https://github.com/kobimusic/dettato/blob/9b724251794f2bbd5eaa43e54734e5a251829130/src/dettato/drums/model.py), [Copisteria architecture](https://github.com/kobimusic/copisteria/blob/main/docs/ARCHITECTURE.md), [Copista benchmark](https://kobi.music/research/copista).
