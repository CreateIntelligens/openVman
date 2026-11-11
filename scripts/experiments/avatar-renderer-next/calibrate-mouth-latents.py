"""Calibrate the signed anatomical decode from labelled speech.

Inputs are only the retained audio model, this project's feature extractor and
syllable recordings synthesised on request. Targets are mouth poses authored in
PHONETIC_TARGETS below; SIGNS records which way each latent moves the mouth, as
checked by eye with single-channel interventions. No historical rig, morph
table, template or native render is read here or regressed against.

The corpus folder holds ``<voice>_<syllable>.wav`` (16 kHz mono PCM16). Output is
the fitted starting point for the decode in character-adapter.mjs, which was then
edited by hand; PROVENANCE lists the differences. The feature scales and the
three-step lag below are the retained model's contract, not fitted here.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort
from scipy.optimize import lsq_linear


ENGINE = Path(__file__).resolve().parents[3] / "frontend/shared/avatar-engine"
SCALES = np.array([0.24, 0.21, 0.24, 0.24, 0.24, 0.24], dtype=np.float32)
STEP_SAMPLES = 640
# The model's jaw channel trails the audio envelope by three 40 ms steps, the
# same delay the streaming controller compensates with its lookahead.
MODEL_LAG_STEPS = 3
CONTROLS = ("gap", "jaw", "round")

# Mouth-width ratios (gap, jaw) and a rounding scale (+1 pursed, -1 spread).
# Authored per viseme and adjusted by eye against the reference page; they only
# need to rank and scale visemes, and no displacement data is sampled for them.
PHONETIC_TARGETS = {
    "a": (0.24, 0.16, -0.05),
    "e": (0.05, 0.05, -0.05),
    "o": (0.09, 0.07, 0.60),
    "ei": (0.20, 0.11, -0.35),
    "ai": (0.27, 0.19, -0.25),
    "ao": (0.20, 0.14, 0.30),
    "i": (0.13, 0.04, -0.70),
    "y": (0.05, 0.03, 0.70),
    "u": (0.03, 0.03, 1.00),
    "bilabial": (0.00, 0.03, 0.00),
    "f": (0.00, 0.02, 0.15),
    "apical": (0.13, 0.015, -0.45),
    "retroflex": (0.10, 0.025, 0.05),
    "palatal": (0.15, 0.03, -0.60),
}
# Which way each latent may push a control; 0 leaves the sign to the corpus.
# Gap directions follow the interventions: c0..c2 open, c3..c5 close.
SIGNS = {
    "gap": (1, 1, 1, -1, -1, -1),
    "jaw": (1, 1, 0, 0, 0, 0),
    "round": (-1, 1, -1, 0, 0, 0),
}
# A closed mouth tolerates moving a little around rest without parting: speech
# only needs the gap decode to stay at or below zero through a closure.
HINGE_CLASSES = {"bilabial", "f"}
# Closures are the shortest and perceptually most important gestures.
WEIGHTS = {"bilabial": 3.0, "a": 1.5, "u": 1.5, "i": 1.5}
# (labelled class at envelope peaks, labelled class at envelope troughs).
SYLLABLES = {
    "a": ("a", None), "e": ("e", None), "o": ("o", None), "ei": ("ei", None),
    "ai": ("ai", None), "ao": ("ao", None), "i": ("i", None), "yu": ("y", None),
    "u": ("u", None),
    "ma": ("a", "bilabial"), "ba": ("a", "bilabial"), "pa": ("a", "bilabial"),
    "mi": ("i", "bilabial"), "bi": ("i", "bilabial"),
    "mu": ("u", "bilabial"), "bu": ("u", "bilabial"),
    "fa": ("a", "f"), "fu": ("u", "f"),
    "da": ("a", None), "la": ("a", None),
    "si": ("apical", None), "zi": ("apical", None),
    "shi": ("retroflex", None), "ri": ("retroflex", None),
    "qi": ("palatal", None), "xi": ("palatal", None),
}


def fbank(wav: Path) -> np.ndarray:
    """Use the shipped extractor so calibration and playback see equal features."""
    script = f"""
      import {{ readFileSync, writeFileSync }} from 'node:fs';
      const m = await import({json.dumps(str(ENGINE / 'inference/streaming-fbank.mjs'))});
      const Fbank = m.StreamingFbank || m.default;
      const pcm = new Int16Array(Uint8Array.from(readFileSync(process.argv[1])).buffer);
      const f = new Fbank(), frames = [];
      for (let o = 0; o < pcm.length; o += 640) for (const x of f.append(pcm.slice(o, o + 640))) frames.push(x);
      const flat = new Float32Array(frames.length * 80);
      frames.forEach((x, i) => flat.set(x, i * 80));
      writeFileSync(process.argv[2], Buffer.from(flat.buffer));
    """
    with wave.open(str(wav)) as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"{wav}: expected 16 kHz mono PCM16")
        pcm = stream.readframes(stream.getnframes())
    with tempfile.TemporaryDirectory() as folder:
        raw, out = Path(folder) / "pcm", Path(folder) / "out"
        raw.write_bytes(pcm)
        subprocess.run(
            ["node", "--input-type=module", "-e", script, str(raw), str(out)],
            check=True,
        )
        return np.fromfile(out, np.float32).reshape(-1, 80)


def infer(session, features: np.ndarray) -> np.ndarray:
    hidden = np.zeros(384, np.float32)
    cell = np.zeros(384, np.float32)
    rows = []
    for index in range(0, len(features) - 1, 2):
        pose, hidden, cell = session.run(None, {
            "audio_feature": features[index:index + 2].reshape(1, 160),
            "lstm_h": hidden, "lstm_c": cell,
        })
        rows.append(pose[0] * SCALES)
    return np.asarray(rows)


def envelope(wav: Path, steps: int) -> np.ndarray:
    with wave.open(str(wav)) as stream:
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), np.int16) / 32768
    values = np.array([
        np.sqrt((pcm[k * STEP_SAMPLES:(k + 1) * STEP_SAMPLES] ** 2).mean() + 1e-9)
        for k in range(steps)
    ])
    return np.convolve(values, [0.25, 0.5, 0.25], mode="same")


def extrema(values: np.ndarray, sign: int, floor: float):
    """Local extrema inside the voiced span, at least two steps apart."""
    picked = []
    for index in range(1, len(values) - 1):
        if sign * (values[index] - values[index - 1]) > 0 >= sign * (values[index + 1] - values[index]):
            if sign > 0 and values[index] < floor:
                continue
            if picked and index - picked[-1] < 2:
                continue
            picked.append(index)
    return picked


def label_frames(latents: np.ndarray, energy: np.ndarray, syllable: str):
    """Return {class: frames} using audio landmarks, never the latents themselves."""
    peak_class, trough_class = SYLLABLES[syllable]
    voiced = np.flatnonzero(energy > energy.max() * 0.25)
    if not len(voiced):
        return {}
    first, last = voiced[0], voiced[-1]
    result = {}
    peaks = [k for k in extrema(energy, 1, energy.max() * 0.35) if first <= k <= last]
    frames = [latents[k + MODEL_LAG_STEPS] for k in peaks if k + MODEL_LAG_STEPS < len(latents)]
    if frames:
        result[peak_class] = frames
    if trough_class:
        troughs = [k for k in extrema(energy, -1, 0) if first < k < last]
        frames = [latents[k + MODEL_LAG_STEPS] for k in troughs if k + MODEL_LAG_STEPS < len(latents)]
        if frames:
            result[trough_class] = frames
    return result


def rest_vector(session) -> np.ndarray:
    # Steady state on digital silence; a shorter pause never fully settles.
    frames = np.fromiter(iter(()), np.float32)
    silent = Path(tempfile.mkstemp(suffix=".wav")[1])
    try:
        with wave.open(str(silent), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\0\0" * 16000 * 10)
        frames = infer(session, fbank(silent))
    finally:
        silent.unlink()
    return np.median(frames[len(frames) // 2:], axis=0)


def fit_control(design, target, weight, signs, ridge, hinge=None, intercept=False, rounds=8):
    """Sign-constrained ridge; hinge rows only penalise a positive prediction."""
    columns = design.shape[1]
    scale = np.maximum(design.std(axis=0), 1e-6)
    extra = np.diag(ridge * scale) * np.sqrt(len(design))
    lower = [0.0 if sign > 0 else -np.inf for sign in signs]
    upper = [np.inf if sign >= 0 else 0.0 for sign in signs]
    # A closed mouth sits behind this margin: rest maps to zero, not to the edge.
    if intercept:
        lower, upper = lower + [-0.08], upper + [0.0]
    active = np.ones(len(design), bool)
    solution = None
    for _ in range(rounds):
        a = design[active] * weight[active, None]
        if intercept:
            a = np.hstack([a, weight[active, None]])
        b = target[active] * weight[active]
        pad = np.zeros((columns, a.shape[1]))
        pad[:, :columns] = extra
        solved = lsq_linear(np.vstack([a, pad]), np.concatenate([b, np.zeros(columns)]),
                            bounds=(lower, upper)).x
        solution = solved
        if hinge is None or not hinge.any():
            break
        offset = solved[-1] if intercept else 0.0
        predicted = design @ solved[:columns] + offset
        keep = ~hinge | (predicted > target)
        if (keep == active).all():
            break
        active = keep
    return solution


def fit(samples, rest, ridge):
    design = np.array([row["latent"] for row in samples]) - rest
    target = np.array([PHONETIC_TARGETS[row["class"]] for row in samples])
    weight = np.sqrt([WEIGHTS.get(row["class"], 1.0) for row in samples])
    hinge = np.array([row["class"] in HINGE_CLASSES for row in samples])
    rows, offsets = [], []
    for index, name in enumerate(CONTROLS):
        is_gap = name == "gap"
        solved = fit_control(design, target[:, index], weight, SIGNS[name], ridge,
                             hinge if is_gap else None, intercept=is_gap)
        rows.append(solved[:6])
        offsets.append(float(solved[6]) if is_gap else 0.0)
    return np.array(rows), np.array(offsets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ridge", type=float, default=0.002)
    # 明文模型不在公開 repo；由私人建置資料夾提供。
    parser.add_argument("--model", required=True, type=Path, help="plaintext model_audio.onnx")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
    rest = rest_vector(session)
    per_voice, manifest = {}, {}
    for wav in sorted(args.corpus.glob("*.wav")):
        voice, syllable = wav.stem.split("_", 1)
        if syllable not in SYLLABLES:
            continue
        manifest[wav.name] = hashlib.sha256(wav.read_bytes()).hexdigest()
        latents = infer(session, fbank(wav))
        for name, frames in label_frames(latents, envelope(wav, len(latents)), syllable).items():
            per_voice.setdefault(voice, {}).setdefault(name, []).extend(frames)
    samples = [
        {"voice": voice, "class": name, "latent": np.median(frames, axis=0).tolist(), "frames": len(frames)}
        for voice, classes in per_voice.items() for name, frames in classes.items()
    ]
    matrix, offsets = fit(samples, rest, args.ridge)
    # Leave-one-voice-out checks that the decode is not memorising a speaker.
    errors = {}
    for voice in per_voice:
        held = [row for row in samples if row["voice"] == voice]
        model_fit, model_offsets = fit([row for row in samples if row["voice"] != voice], rest, args.ridge)
        predicted = (np.array([row["latent"] for row in held]) - rest) @ model_fit.T + model_offsets
        truth = np.array([PHONETIC_TARGETS[row["class"]] for row in held])
        errors[voice] = np.abs(predicted - truth).mean(axis=0).round(4).tolist()
    classes = {}
    for name in PHONETIC_TARGETS:
        rows = np.array([row["latent"] for row in samples if row["class"] == name])
        if not len(rows):
            continue
        centre = np.median(rows, axis=0)
        classes[name] = {
            "voices": len(rows),
            "latentMedian": centre.round(2).tolist(),
            "latentSpread": rows.std(axis=0).round(2).tolist(),
            "target": PHONETIC_TARGETS[name],
            "decoded": (matrix @ (centre - rest) + offsets).round(3).tolist(),
        }
    report = {
        "inputs": {
            "model": {"path": args.model.name, "sha256": hashlib.sha256(args.model.read_bytes()).hexdigest()},
            "corpus": manifest,
            "excluded": ["historical rig", "morph table", "dental atlas", "native renders"],
        },
        "rest": rest.round(3).tolist(),
        "controls": CONTROLS,
        "decode": matrix.round(5).tolist(),
        "offsets": np.round(offsets, 5).tolist(),
        "signs": SIGNS,
        "ridge": args.ridge,
        "leaveOneVoiceOutMae": errors,
        "classes": classes,
    }
    (args.out / "mouth-calibration.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    np.set_printoptions(precision=4, suppress=True, linewidth=140)
    print("rest", rest)
    print("decode (gap, jaw, round) x (c0..c5)\n", matrix, "\noffsets", offsets)
    print("leave-one-voice-out MAE", errors)
    for name, row in classes.items():
        print(f"{name:10} voices={row['voices']} target={row['target']} decoded={row['decoded']} c={row['latentMedian']}")


if __name__ == "__main__":
    main()
