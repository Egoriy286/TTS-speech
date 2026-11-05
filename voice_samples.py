"""Read locally saved voice samples without loading any speech model."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLES_DIR = ROOT / "samples"


def saved_samples():
    records = []
    for path in SAMPLES_DIR.glob("*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            audio = (SAMPLES_DIR / item["audio_file"]).resolve()
            if audio.parent != SAMPLES_DIR.resolve() or not audio.is_file():
                continue
            if item["language"] not in ("English", "Russian"):
                continue
            records.append({**item, "id": path.stem, "audio_path": str(audio)})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(records, key=lambda r: r.get("created_at", ""), reverse=True)


def sample_choices():
    return [
        (f"{r['language']} · {r.get('created_at', '')[:19].replace('T', ' ')} · {r.get('title', 'Мой голос')}", r["id"])
        for r in saved_samples()
    ]


def sample_values(sample_id):
    for item in saved_samples():
        if item["id"] == sample_id:
            return item["audio_path"], item.get("transcript", ""), item["language"]
    return None, "", "English"
