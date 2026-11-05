"""Local voice cloning UI; launch with each project's own Python environment."""
import argparse
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from voice_samples import sample_choices, sample_values

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HOME", str(ROOT / "cache" / "huggingface"))
os.environ.setdefault("MODELSCOPE_CACHE", str(ROOT / "cache" / "modelscope"))
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "cache" / "matplotlib"))
ENGINES = {
    "qwen": ("Qwen3-TTS", "Qwen3-TTS-1.7B-Base", 7861),
    "cosy": ("CosyVoice", "CosyVoice3", 7862),
    "vox": ("VoxCPM", "VoxCPM2", 7863),
}
_model = None
_lock = threading.Lock()


def load_model(engine):
    global _model
    if _model is not None:
        return _model
    import torch
    torch.set_num_threads(min(8, os.cpu_count() or 4))
    folder, model_name, _ = ENGINES[engine]
    model_path = ROOT / "models" / model_name
    if not model_path.is_dir():
        raise RuntimeError("Не найдена папка модели: " + str(model_path))
    if engine == "qwen":
        from qwen_tts import Qwen3TTSModel
        device = "cuda:0" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
        _model = Qwen3TTSModel.from_pretrained(
            str(model_path), device_map=device, dtype=torch.float32,
            attn_implementation="sdpa",
        )
    elif engine == "vox":
        from voxcpm import VoxCPM
        _model = VoxCPM.from_pretrained(
            str(model_path), load_denoiser=False, optimize=False, device="auto",
        )
    else:
        project = ROOT / folder
        sys.path.insert(0, str(project))
        sys.path.insert(0, str(project / "third_party" / "Matcha-TTS"))
        os.environ["COSYVOICE_DISABLE_TEXT_FRONTEND"] = "1"
        from cosyvoice.cli.cosyvoice import AutoModel
        _model = AutoModel(model_dir=str(model_path), fp16=False)
    return _model


def synthesize(engine, audio, transcript, text, language):
    import numpy as np
    import soundfile as sf
    if not text or not text.strip():
        raise ValueError("Введите текст для озвучки.")
    if not audio:
        raise ValueError("Загрузите или запишите образец голоса.")
    info = sf.info(audio)
    if not 2 <= info.duration <= 30:
        raise ValueError("Используйте образец длиной от 2 до 30 секунд.")
    transcript = (transcript or "").strip()
    if engine == "cosy" and not transcript:
        raise ValueError("Для CosyVoice укажите точную расшифровку образца.")
    with _lock:
        model = load_model(engine)
        if engine == "qwen":
            wavs, sr = model.generate_voice_clone(
                text=text.strip(), language=language, ref_audio=audio,
                ref_text=transcript or None, x_vector_only_mode=not bool(transcript),
                max_new_tokens=2048,
            )
            wav = wavs[0]
        elif engine == "vox":
            kwargs = {"prompt_wav_path": audio, "prompt_text": transcript} if transcript else {"reference_wav_path": audio}
            wav = model.generate(text=text.strip(), **kwargs)
            sr = model.tts_model.sample_rate
        else:
            import torch
            chunks = list(model.inference_zero_shot(
                text.strip(), "You are a helpful assistant.<|endofprompt|>" + transcript,
                audio, stream=False, text_frontend=False,
            ))
            if not chunks:
                raise RuntimeError("Модель не вернула аудио.")
            wav = torch.cat([chunk["tts_speech"] for chunk in chunks], dim=1).squeeze(0).cpu().numpy()
            sr = model.sample_rate
        wav = np.asarray(wav).squeeze()
        if not wav.size or not np.isfinite(wav).all():
            raise RuntimeError("Модель вернула пустое или повреждённое аудио.")
        out_dir = ROOT / "generated"
        out_dir.mkdir(exist_ok=True)
        out = out_dir / (engine + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".wav")
        sf.write(out, wav, sr, subtype="PCM_16")
        return str(out), str(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=ENGINES, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--text", default="Hello! This is a short voice cloning test.")
    parser.add_argument("--reference")
    parser.add_argument("--transcript", default="希望你以后能够做的比我还好呦。")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        ref = args.reference or str(ROOT / "CosyVoice" / "asset" / "zero_shot_prompt.wav")
        print(synthesize(args.engine, ref, args.transcript, args.text, "English"), flush=True)
        return
    import gradio as gr
    title, _, port = ENGINES[args.engine]
    choices = sample_choices()
    initial_id = choices[0][1] if choices else None
    initial_audio, initial_transcript, initial_language = sample_values(initial_id)
    with gr.Blocks(title=title + " — мой голос") as demo:
        gr.Markdown("# " + title + " — мой голос\nЗагрузите 5–20 секунд чистой речи, введите текст и нажмите «Создать голосовое». При первой генерации модель загружается в память.")
        with gr.Row():
            saved_sample = gr.Dropdown(choices=choices, value=initial_id, label="Сохранённый образец вашего голоса", scale=4)
            refresh_samples = gr.Button("Обновить образцы", scale=1)
        audio = gr.Audio(value=initial_audio, sources=["upload", "microphone"], type="filepath", label="Образец вашего голоса")
        transcript = gr.Textbox(value=initial_transcript, label="Точная расшифровка образца", placeholder="Что именно произнесено в записи. Для CosyVoice — обязательно.")
        text = gr.Textbox(label="Текст для озвучки", lines=5, placeholder="Введите текст на английском или русском.")
        language = gr.Dropdown(["English", "Russian", "Auto"], value=initial_language, label="Язык (для Qwen; остальные определяют его по тексту)")
        saved_sample.change(sample_values, [saved_sample], [audio, transcript, language], api_name=False)

        def refresh_saved_samples():
            available = sample_choices()
            selected = available[0][1] if available else None
            return gr.update(choices=available, value=selected), *sample_values(selected)

        refresh_samples.click(refresh_saved_samples, [], [saved_sample, audio, transcript, language], api_name=False)
        button = gr.Button("Создать голосовое", variant="primary")
        output = gr.Audio(label="Результат", type="filepath")
        download = gr.File(label="Скачать WAV")
        button.click(lambda a, r, t, l: synthesize(args.engine, a, r, t, l), [audio, transcript, text, language], [output, download])
        gr.Markdown("Файлы сохраняются в папку **generated**. Для завершения работы закройте окно Terminal или нажмите Ctrl+C. Запускайте по одной модели, чтобы хватало памяти.")
    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=port,
        inbrowser=not args.no_browser, share=False, show_error=True,
    )


if __name__ == "__main__":
    main()
