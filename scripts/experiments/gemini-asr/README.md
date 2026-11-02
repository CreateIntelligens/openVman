# Gemini whole-file ASR experiment

Question: the kiosk only calls `POST /api/v1/asr/transcribe` (whole file). Its English mode uses
`openai`. Should a Gemini batch engine replace or back it up, and which one?

Result: the `gemini-live-batch` engine (A) shipped as an explicitly selectable batch engine
(`backend/app/gateway/gemini_live_batch.py`); B and A' did not and live on only in
`retired_engines.py` so this bench can rerun them.

| bench id | where | how |
|---|---|---|
| `gemini-live-batch` (A) | production | One Gemini Live session per request (`ASR_GEMINI_STREAM_MODEL`), clip sent unpaced, server VAD off, framed with `activityStart`/`activityEnd`. 0.3 s lead silence, no tail. |
| `gemini-live-batch-auto` (A') | `retired_engines.py` | Server VAD on, 0.5 s lead + 1 s tail, then `audioStreamEnd`. |
| `gemini` (B) | `retired_engines.py` | `generateContent` with the clip inline, `gemini-3.5-transcribe`: answers with an `audioTranscription` part, takes `generationConfig.audioTranscriptionConfig`, rejects `systemInstruction` (HTTP 400). |
| `gemini-llm` (B') | `retired_engines.py` | `generateContent`, `gemini-3.5-flash-lite`, strict verbatim instruction, temperature 0, JSON schema `{has_speech, text}`. |
| `openai` | production | `gpt-4o-mini-transcribe`, the comparison baseline. |

The first bench ran A with 0.5 s lead + 0.5 s tail; `live_probe.py padding` then picked 0.3 s
lead, no tail.

## How A decides it has the whole transcript

Probed against the live API on 2026-10-30 (single runs, q04 and a two-sentence clip):

- Sending faster than realtime is fine: Gemini processes the buffer at roughly 2.4× realtime.
- With server VAD and no trailing silence, `audioStreamEnd` never produced a final (only interims).
  With ≥1 s of trailing silence the final arrives, followed by `generationComplete` and
  `voiceActivity: ACTIVITY_END`. There is no `turnComplete`.
- Without leading silence auto VAD dropped the first words; manual mode kept them but misheard
  later ones. The `padding` grid: 0.1, 0.3 and 0.5 s lead correct on all clips, 0 and 0.2 s wrong
  on one or two. Tail silence changed nothing, so manual mode sends none.
- On silence or low noise, server VAD sends nothing at all; manual mode answers with
  `ACTIVITY_START`/`ACTIVITY_END` and no transcription within ~1 s.

Rule in `gemini_live_batch._collect_finals`: stop at `generationComplete`. If `ACTIVITY_END`
arrives first (silence), wait 0.5 s for a late final, then return `""`. A session that never
answers is not silence: `transcribe()`'s per-node budget cancels it and it counts as a timeout.

## Running

Credentials come from the running backend container, inline, never written to disk or printed:

```bash
eval "$(docker exec openvman-backend-1 sh -c 'env' | python3 -c '
import sys, shlex, re
for line in sys.stdin:
    k, _, v = line.rstrip("\n").partition("=")
    if re.fullmatch(r"GEMINI_API_KEY|WHISPER_API_KEY|OPENAI_API_KEY|ASR_OPENAI_[A-Z_]*|ASR_GEMINI_[A-Z_]*", k):
        print(f"export {k}={shlex.quote(v)}")
')"
python3 scripts/experiments/gemini-asr/bench.py run --reps 3          # all clips, all engines
python3 scripts/experiments/gemini-asr/bench.py run --only 'idx_*' --engines gemini,openai
python3 scripts/experiments/gemini-asr/bench.py report <results.json>  # rebuild the markdown
```

The OpenAI key is `WHISPER_API_KEY` (that is what `TTSRouterConfig.whisper_api_key` reads).
It runs on host Python with this worktree's `backend/` on `sys.path`; `anydoc` is stubbed.

Data lives outside the repo in `~/openvman-experiments/gemini-asr/` (override with
`GEMINI_ASR_DATA`):

- `audio/*.{wav,mp3,webm,m4a,ogg,flac}` with a same-name `.txt` reference. `audio/sources.json`
  assigns each clip a source group (`files` first, then `patterns`); anything unmatched counts as
  a real recording.
- `silence/` — generated on first run: 3 s digital silence, 3 s low pink noise, 1 s blank.
- `results/results_<stamp>.{json,md}` — every transcript and latency, plus the tables.

`bench.py generate-tts` recreates the `tts_*` edge-tts clips; it needs edge-tts ≥ 7.3 (7.2.7
gets HTTP 403 from the Bing endpoint).

Scoring: lowercase, hyphens to spaces, numbers 0–99 to words, punctuation stripped, then
word-level WER; exact match is WER 0. A clip is marked "bad source" (excluded from accuracy,
transcripts still shown) when every engine's median WER is above 0.5, it is shorter than 0.8 s,
or its mean level is below −45 dB. Latency is from the function call to its result, including
ffmpeg decode and the network round trip.

## Follow-up probes for A (`live_probe.py`)

`live_probe.py` talks to Gemini Live directly with the same messages and times each stage.
Subcommands: `stages` (per-stage latency, fresh session per clip), `reuse` (many clips in one
session, bleed check), `idle` / `idle2` (how long an idle or setup-only session stays usable,
silence keepalive), `pool` (single-use warm pool), `shared` (pool keyed by
`(api_key_id, project_id)`, `--mode single|reuse`, concurrent callers, optional session-pinned
layer), `padding` (lead/tail silence grid). Results go to `results/live_<cmd>_<stamp>.json`.
