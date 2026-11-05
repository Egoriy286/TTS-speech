"""Microphone recorder and bilingual reading prompts for local voice cloning."""
import argparse
import json
import math
import os
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

PROMPTS = {
    "English": {
        "Объяснение идеи": "Hi! Today I'm working on a new project, and I'd like to explain the main idea clearly. Let's take a simple example, look at what changes, and see why the result makes sense.",
        "Разговорный": "I usually start my morning with a cup of tea and a short walk. Later, I check my notes, answer a few messages, and get back to work. What are your plans for tomorrow?",
    },
    "Russian": {
        "Объяснение идеи": "Привет! Сегодня я работаю над новым проектом и хочу понятно объяснить главную идею. Давайте возьмём простой пример, посмотрим, что меняется, и разберёмся, почему получается именно такой результат.",
        "Разговорный": "Обычно я начинаю утро с чашки чая и небольшой прогулки. Потом просматриваю свои заметки, отвечаю на несколько сообщений и возвращаюсь к работе. А какие у тебя планы на завтра?",
    },
}


MSFEM_PROMPTS = {
    "English": [
        "Imagine water moving through a piece of rock. Some regions let it pass easily, while others slow it down. These tiny differences can change the behavior of the whole system.",
        "A very fine mesh can describe those details, but solving a large problem on that mesh may be expensive. The multiscale finite element method uses a different strategy for the global calculation.",
        "We divide the domain into larger elements. Inside each one, we solve local problems on a fine mesh. Their solutions form special basis functions that reflect the material's small scale structure.",
        "We then use these basis functions to assemble a smaller global system on the coarse mesh. This can reduce the global computational cost, while keeping important information from the local material structure.",
    ],
    "Russian": [
        "Представьте, как вода проходит через кусок горной породы. Одни участки легко пропускают поток, а другие его замедляют. Эти небольшие различия могут менять поведение всей системы.",
        "Очень мелкая сетка позволяет описать такие детали, но решение большой задачи на этой сетке может стоить дорого. Многомасштабный метод конечных элементов предлагает другой подход к глобальному расчёту.",
        "Мы делим область на крупные элементы. Внутри каждого из них решаем локальные задачи на мелкой сетке. Полученные решения образуют специальные базисные функции, которые учитывают мелкую структуру материала.",
        "Затем с помощью этих базисных функций мы собираем меньшую глобальную систему на крупной сетке. Это позволяет уменьшить стоимость глобального расчёта и сохранить важную информацию о локальной структуре материала.",
    ],
}
for _language, _texts in MSFEM_PROMPTS.items():
    for _number, _text in enumerate(_texts, 1):
        PROMPTS[_language][f"MsFEM — часть {_number}"] = _text


def save_recording(audio, transcript, language, title, *, samples_dir=None):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    if not audio:
        raise ValueError("Сначала нажмите на микрофон, прочитайте текст и остановите запись.")
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("Укажите текст, который вы произнесли в записи.")
    if language not in PROMPTS:
        raise ValueError("Выберите английский или русский язык.")
    data, source_rate = sf.read(audio, dtype="float32", always_2d=True)
    if not len(data) or not np.isfinite(data).all():
        raise ValueError("В записи нет корректного звука. Попробуйте записать ещё раз.")
    duration = len(data) / source_rate
    if not 2 <= duration <= 30:
        raise ValueError(f"Запись длится {duration:.1f} с. Нужен образец от 2 до 30 секунд. Прочитайте один абзац и нажмите «Стоп».")
    mono = data.mean(axis=1)
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(data)))
    if rms < 0.0001:
        raise ValueError("Почти не слышно голоса. Проверьте выбранный микрофон и запишите ещё раз.")
    if source_rate < 16000:
        raise ValueError("Слишком низкая частота записи. Выберите другой микрофон или загрузите WAV с частотой не ниже 16 кГц.")
    warnings = []
    if peak >= 0.99:
        warnings.append("Есть риск перегруза: попробуйте говорить немного тише или отодвинуть микрофон.")
    if rms < 0.01:
        warnings.append("Запись тихая: попробуйте приблизить микрофон.")
    if duration < 5:
        warnings.append("Для первого образца лучше прочитать весь абзац: примерно 10–20 секунд.")
    target_rate = 24000
    if source_rate != target_rate:
        divisor = math.gcd(source_rate, target_rate)
        mono = resample_poly(mono, target_rate // divisor, source_rate // divisor)
    folder = Path(samples_dir) if samples_dir is not None else ROOT / "samples"
    folder.mkdir(parents=True, exist_ok=True)
    created = datetime.now().astimezone()
    prefix = "english" if language == "English" else "russian"
    stem = f"{prefix}_{created.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    wav = folder / (stem + ".wav")
    text_file = folder / (stem + ".txt")
    meta_file = folder / (stem + ".json")
    sf.write(wav, mono, target_rate, subtype="PCM_16")
    text_file.write_text(transcript + "\n", encoding="utf-8")
    metadata = {
        "audio_file": wav.name, "transcript_file": text_file.name,
        "transcript": transcript, "language": language, "title": title,
        "created_at": created.isoformat(timespec="seconds"),
        "duration_seconds": round(len(mono) / target_rate, 3),
        "sample_rate": target_rate, "channels": 1,
        "source_sample_rate": source_rate, "peak": peak, "rms": rms,
        "warnings": warnings,
    }
    meta_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = f"**Сохранено.** {duration:.1f} с · {language} · WAV, 24 кГц, моно.\n\nФайлы: **samples/{stem}.wav** и **.txt**.\n\nОткройте «1 — Qwen3-TTS.command»: образец появится в списке сохранённых записей. Если программа уже открыта, нажмите «Обновить образцы»."
    if warnings:
        status += "\n\n" + "\n\n".join(warnings)
    return str(wav), [str(wav), str(text_file)], status


def build_app():
    import gradio as gr

    with gr.Blocks(title="Запись моего голоса") as demo:
        gr.Markdown("# Запись моего голоса\nСначала запишите **английский** образец, затем при желании — **русский**. Одного абзаца достаточно для первого теста клонирования.")
        with gr.Row():
            language = gr.Dropdown(choices=[("Английский", "English"), ("Русский", "Russian")], value="English", label="Язык записи")
            title = gr.Dropdown(choices=list(PROMPTS["English"]), value="Объяснение идеи", label="Текст для чтения")
        transcript = gr.Textbox(value=PROMPTS["English"]["Объяснение идеи"], lines=5, label="Прочитайте этот текст вслух", info="Говорите своим обычным голосом и с привычным акцентом. Если произнесли другие слова, исправьте текст перед сохранением.")
        gr.Markdown("**1.** Сядьте в тихом месте. Держите микрофон примерно в 15–25 см от лица.\n\n**2.** Нажмите значок микрофона / **Record**, разрешите доступ и прочитайте абзац. Затем нажмите **Stop**.\n\n**3.** Прослушайте запись и нажмите **«Сохранить образец»**. Записывайте каждый язык отдельно, до 30 секунд за один дубль.")
        audio = gr.Audio(sources=["microphone", "upload"], type="filepath", format="wav", label="Ваш микрофон — запись и прослушивание", editable=True)
        save = gr.Button("Сохранить образец", variant="primary")
        status = gr.Markdown("Запись сохранится только после нажатия кнопки. Всё остаётся на этом компьютере.")
        saved = gr.Audio(label="Сохранённый образец", type="filepath", interactive=False)
        files = gr.File(label="WAV и точная расшифровка", file_count="multiple")

        def change_prompt(lang, kind):
            return PROMPTS[lang][kind], None, None, [], "Прочитайте новый текст и сохраните отдельный образец."

        for component in (language, title):
            component.change(change_prompt, [language, title], [transcript, audio, saved, files, status], api_name=False)

        def save_ui(a, t, lang, kind):
            try:
                return save_recording(a, t, lang, kind)
            except ValueError as exc:
                raise gr.Error(str(exc)) from exc

        save.click(save_ui, [audio, transcript, language, title], [saved, files, status], api_name="save_sample")
    return demo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()
    build_app().queue(default_concurrency_limit=1).launch(server_name="127.0.0.1", server_port=args.port, inbrowser=not args.no_browser, share=False, show_error=True)


if __name__ == "__main__":
    main()
