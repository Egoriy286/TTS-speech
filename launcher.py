"""One-click local launcher. Bootstrap uses only the Python standard library."""
import argparse
import http.server
import importlib.util
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
PROJECTS = json.loads((ROOT / 'projects.json').read_text(encoding='utf-8'))
SIZES = json.loads((ROOT / 'model-sizes.json').read_text(encoding='utf-8'))
NAMES = {'recorder': 'Записать мой голос', 'qwen': 'Qwen3-TTS', 'cosy': 'CosyVoice 3', 'vox': 'VoxCPM2'}
PORTS = {'recorder': 7860, **{k: v['port'] for k, v in PROJECTS.items()}}
STATE = {k: {'message': 'Готов к запуску', 'busy': False, 'url': None, 'error': None} for k in NAMES}
INSTALL_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
CHILDREN = {}
NO_BROWSER = False


def update(engine, **values):
    with STATE_LOCK:
        STATE[engine].update(values)


def python_path(env):
    return env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def usable_python(path, modules=()):
    if not path.is_file():
        return False
    code = "import importlib.util,sys; assert sys.platform==" + repr(sys.platform)
    code += "; assert all(importlib.util.find_spec(x) is not None for x in " + repr(list(modules)) + ")"
    try:
        return subprocess.run([str(path), '-c', code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def uv_binary():
    candidate = ROOT / '.tools' / ('uv.exe' if os.name == 'nt' else 'uv')
    result = str(candidate) if candidate.is_file() else shutil.which('uv')
    if not result:
        raise RuntimeError('Запустите START-WINDOWS.cmd или START-MACOS.command: они установят uv.')
    return result


def environment():
    env = dict(os.environ)
    env.update(PYTHONUTF8='1', PYTORCH_ENABLE_MPS_FALLBACK='1', TOKENIZERS_PARALLELISM='false', GRADIO_ANALYTICS_ENABLED='False', SETUPTOOLS_SCM_PRETEND_VERSION_FOR_VOXCPM='0.0.0')
    env['PATH'] = str(ROOT / '.tools/bin') + os.pathsep + env.get('PATH', '')
    env['HF_HOME'] = str(ROOT / 'cache/huggingface')
    env['MODELSCOPE_CACHE'] = str(ROOT / 'cache/modelscope')
    env['MPLCONFIGDIR'] = str(ROOT / 'cache/matplotlib')
    env.pop('HF_HUB_OFFLINE', None)
    return env


def run(command, log, *, cwd=ROOT):
    result = subprocess.run([str(x) for x in command], cwd=cwd, env=environment(), stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('Команда завершилась с ошибкой. Подробности находятся в журнале ниже.')


def extract_source(archive, target):
    """Extract a GitHub source ZIP, dropping its single top-level directory."""
    target = Path(target)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            parts = PurePosixPath(member.filename).parts
            if len(parts) < 2:
                continue
            relative = Path(*parts[1:])
            out = (target / relative).resolve()
            if not out.is_relative_to(target.resolve()):
                raise ValueError('Недопустимый путь в архиве исходников.')
            if member.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as src, out.open('wb') as dst:
                    shutil.copyfileobj(src, dst)


def download_source(source, revision, target):
    cache = ROOT / 'cache/downloads'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (source.replace('/', '-') + '-' + revision + '.zip')
    if not archive.is_file():
        temporary = archive.with_suffix('.part')
        with urllib.request.urlopen(f'https://codeload.github.com/{source}/zip/{revision}', timeout=60) as src, temporary.open('wb') as dst:
            shutil.copyfileobj(src, dst)
        temporary.replace(archive)
    extract_source(archive, target)


def prepare_source(engine):
    p = PROJECTS[engine]
    folder = ROOT / p['folder']
    required = folder / ('cosyvoice/cli/cosyvoice.py' if engine == 'cosy' else 'pyproject.toml')
    if not required.is_file():
        update(engine, message='Скачиваю исходники проекта…')
        download_source(p['source'], p['revision'], folder)
    if engine == 'cosy':
        sub = p['submodule']
        if not (folder / sub['path'] / 'matcha').is_dir():
            download_source(sub['source'], sub['revision'], folder / sub['path'])
        frontend = folder / 'cosyvoice/cli/frontend.py'
        content = frontend.read_text(encoding='utf-8')
        if 'COSYVOICE_DISABLE_TEXT_FRONTEND' not in content:
            anchor = '        # NOTE compatible when no text frontend tool is avaliable\n'
            if content.count(anchor) != 1:
                raise RuntimeError('Изменилась версия CosyVoice: не удалось настроить локальный режим.')
            addition = "        if os.environ.get('COSYVOICE_DISABLE_TEXT_FRONTEND') == '1':\n            self.text_frontend = ''\n            return\n"
            frontend.write_text(content.replace(anchor, addition + anchor), encoding='utf-8')
        processor = folder / 'cosyvoice/dataset/processor.py'
        content = processor.read_text(encoding='utf-8')
        if '\nimport pyworld as pw\n' in content:
            content = content.replace('\nimport pyworld as pw\n', '\n')
            start = content.index('def compute_f0(')
            index = content.index('    for sample in data:', start)
            content = content[:index] + '    import pyworld as pw  # Optional training-only dependency.\n\n' + content[index:]
            processor.write_text(content, encoding='utf-8')
    return folder


def prepare_env(engine, log):
    modules = ['gradio', 'numpy', 'scipy', 'soundfile']
    if engine != 'recorder':
        modules += ['torch', 'huggingface_hub', {'qwen': 'qwen_tts', 'vox': 'voxcpm', 'cosy': 'hyperpyyaml'}[engine]]
    if engine == 'recorder':
        existing = python_path(ROOT / 'Qwen3-TTS/.venv')
        if usable_python(existing, modules):
            return existing
        env = ROOT / ('.recorder-venv-windows' if os.name == 'nt' else '.recorder-venv-macos')
        version, folder = '3.12', None
    else:
        folder = prepare_source(engine)
        version = PROJECTS[engine]['python']
        env = folder / ('.venv-windows' if os.name == 'nt' else '.venv')
        # Do not replace an environment copied from another OS or machine.
        if env.exists() and not usable_python(python_path(env)):
            env = folder / ('.venv-windows-local' if os.name == 'nt' else '.venv-macos-local')
    python = python_path(env)
    if usable_python(python, modules):
        return python
    update(engine, message='Устанавливаю Python и зависимости. Первый запуск займёт время…')
    uv = uv_binary()
    if not usable_python(python):
        run([uv, 'venv', '--python', version, env], log)
    base = [uv, 'pip', 'install', '--python', python]
    if engine == 'recorder':
        run(base + ['gradio>=6,<7', 'numpy', 'scipy', 'soundfile'], log)
    elif engine == 'cosy':
        requirements = ROOT / 'requirements' / ('cosyvoice-windows.txt' if os.name == 'nt' else 'cosyvoice-macos.txt')
        run(base + ['-r', requirements, '--build-constraint', ROOT / 'requirements/build.txt'], log)
    else:
        run(base + ['-e', folder], log)
    return python


def prepare_ffmpeg(python, log):
    env = environment()
    if shutil.which('ffmpeg', path=env['PATH']):
        return
    run([uv_binary(), 'pip', 'install', '--python', python, 'imageio-ffmpeg==0.6.0'], log)
    exe = subprocess.check_output([str(python), '-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'], env=env, text=True).strip()
    target = ROOT / '.tools/bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, target)
    if os.name != 'nt':
        target.chmod(0o755)


def weights_ready(engine):
    if engine == 'recorder':
        return True
    p = PROJECTS[engine]
    folder = ROOT / 'models' / p['model_dir']
    return all((folder / name).is_file() for name in p['required_files']) and all((folder / name).is_file() and (folder / name).stat().st_size == size for name, size in SIZES[p['model_dir']].items())


def prepare_weights(engine, python, log):
    if weights_ready(engine):
        return
    update(engine, message='Скачиваю веса модели (несколько ГБ). Не закрывайте окно запуска…')
    p = PROJECTS[engine]
    ignores = ['llm.rl.pt', 'flow.decoder.estimator.fp32.onnx', 'speech_tokenizer_v3.batch.onnx', 'asset/*'] if engine == 'cosy' else []
    code = 'from huggingface_hub import snapshot_download; snapshot_download(repo_id=' + repr(p['model']) + ', revision=' + repr(p['model_revision']) + ', local_dir=' + repr(str(ROOT / 'models' / p['model_dir'])) + ', ignore_patterns=' + repr(ignores) + ', max_workers=2)'
    run([python, '-u', '-c', code], log)
    if not weights_ready(engine):
        raise RuntimeError('Веса скачаны не полностью. Повторите запуск, чтобы продолжить загрузку.')


def running_app(engine):
    url = f'http://127.0.0.1:{PORTS[engine]}'
    try:
        with urllib.request.urlopen(url + '/config', timeout=1) as response:
            title = json.load(response).get('title', '')
        expected = {'recorder': 'Запись моего голоса', 'qwen': 'Qwen3-TTS', 'cosy': 'CosyVoice', 'vox': 'VoxCPM'}[engine]
        return url if expected in title else None
    except (OSError, ValueError):
        return None


def start_worker(engine):
    log_path = ROOT / 'logs' / ('launcher-' + engine + '.log')
    try:
        existing = running_app(engine)
        if existing:
            update(engine, message='Уже запущено', url=existing)
            if not NO_BROWSER:
                webbrowser.open(existing)
            return
        with INSTALL_LOCK, log_path.open('a', encoding='utf-8') as log:
            python = prepare_env(engine, log)
            prepare_ffmpeg(python, log)
            prepare_weights(engine, python, log)
            update(engine, message='Открываю программу…')
            args = [python, '-u', ROOT / ('record_voice.py' if engine == 'recorder' else 'voice_app.py')]
            if engine != 'recorder':
                args += ['--engine', engine]
            args += ['--no-browser']
            child = subprocess.Popen([str(x) for x in args], cwd=ROOT, env=environment(), stdout=log, stderr=subprocess.STDOUT)
            CHILDREN[engine] = child
        for _ in range(120):
            if child.poll() is not None:
                raise RuntimeError('Программа завершилась при запуске. Смотрите журнал ниже.')
            url = running_app(engine)
            if url:
                update(engine, message='Работает', url=url)
                if not NO_BROWSER:
                    webbrowser.open(url)
                return
            time.sleep(.5)
        raise RuntimeError('Программа не ответила за минуту. Подробности находятся в журнале.')
    except Exception as exc:
        update(engine, message='Не удалось запустить', error=str(exc))
    finally:
        update(engine, busy=False)


def request_start(engine):
    if engine not in NAMES:
        raise ValueError('Неизвестная программа')
    with STATE_LOCK:
        if STATE[engine]['busy']:
            return
        STATE[engine].update(busy=True, message='Подготовка…', error=None)
    threading.Thread(target=start_worker, args=(engine,), daemon=True).start()


HTML = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TTS-speech</title>
<style>body{font:17px system-ui;margin:40px auto;padding:0 24px;max-width:820px;background:#f5f6fa;color:#172033}h1{margin-bottom:8px}.card{background:white;border:1px solid #dce0e8;border-radius:14px;padding:20px;margin:16px 0}button{background:#214fc6;color:white;border:0;border-radius:8px;padding:12px 20px;font:inherit;cursor:pointer}button:disabled{opacity:.55;cursor:wait}a{color:#214fc6;margin-left:16px}p{line-height:1.5}.status{margin-top:12px;color:#526078}pre{white-space:pre-wrap;font-size:12px;max-height:230px;overflow:auto}summary{cursor:pointer}footer{font-size:14px;color:#526078;margin:30px 0}</style>
<h1>TTS-speech</h1><p>Запишите свой голос, затем озвучьте новый текст на английском или русском.</p>
<div id="apps"></div><footer>Первый запуск скачивает необходимые компоненты. Затем программа использует локальные модели. Запускайте одну модель синтеза за раз. Для остановки откройте окно запуска и нажмите Ctrl+C.</footer>
<script>
const names={recorder:'0 · Записать мой голос',qwen:'1 · Qwen3-TTS',cosy:'2 · CosyVoice 3',vox:'3 · VoxCPM2'};
const about={recorder:'Тексты для чтения, микрофон, прослушивание и сохранение образцов.',qwen:'Рекомендуется для первого теста вашего голоса.',cosy:'Ещё одна модель для сравнения звучания.',vox:'Клонирование голоса с сохранением манеры речи.'};
for(const [key,name] of Object.entries(names)){const card=document.createElement('div');card.className='card';card.innerHTML=`<h2>${name}</h2><p>${about[key]}</p><button id="b-${key}">Открыть</button><a id="a-${key}" hidden target="_blank" rel="noopener">Перейти в программу</a><div class="status" id="s-${key}"></div><details><summary>Журнал запуска</summary><pre id="l-${key}"></pre></details>`;document.getElementById('apps').append(card);document.getElementById('b-'+key).onclick=async()=>{try{const r=await fetch('/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({engine:key})});if(!r.ok)throw Error(await r.text());await refresh()}catch(e){document.getElementById('s-'+key).textContent=e.message}}}
async function refresh(){try{const r=await fetch('/state');const data=await r.json();for(const [key,s] of Object.entries(data.apps)){document.getElementById('b-'+key).disabled=s.busy;document.getElementById('s-'+key).textContent=s.message+(s.error?' — '+s.error:'');const a=document.getElementById('a-'+key);a.hidden=!s.url;if(s.url)a.href=s.url;document.getElementById('l-'+key).textContent=s.log||''}}catch(e){}}
refresh();setInterval(refresh,1500);
</script></html>'''


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, value, status=200, content_type='application/json; charset=utf-8'):
        data = value.encode('utf-8') if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            return self.reply(HTML, content_type='text/html; charset=utf-8')
        if self.path == '/state':
            with STATE_LOCK:
                apps = {key: dict(value) for key, value in STATE.items()}
            for engine, state in apps.items():
                log = ROOT / 'logs' / ('launcher-' + engine + '.log')
                if log.is_file():
                    with log.open('rb') as f:
                        f.seek(max(0, log.stat().st_size - 5000))
                        state['log'] = f.read().decode('utf-8', errors='replace')
            return self.reply({'product': 'TTS-speech', 'apps': apps})
        self.reply({'error': 'Not found'}, 404)

    def do_POST(self):
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if self.path != '/start' or (origin and origin not in allowed):
            return self.reply({'error': 'Forbidden'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 1024:
                raise ValueError('Недопустимый запрос')
            request_start(json.loads(self.rfile.read(length))['engine'])
            self.reply({'ok': True})
        except (ValueError, KeyError, TypeError) as exc:
            self.reply({'error': str(exc)}, 400)


def main():
    global NO_BROWSER
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', choices=NAMES)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--check', action='store_true', help='Check launcher files without installing models')
    parser.add_argument('--port', type=int, default=7859)
    args = parser.parse_args()
    NO_BROWSER = args.no_browser
    for folder in ['logs', 'samples', 'generated', 'cache', '.tools/bin']:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    if args.check:
        for name in ['record_voice.py', 'voice_app.py', 'voice_samples.py']:
            compile((ROOT / name).read_text(encoding='utf-8'), name, 'exec')
        assert set(PROJECTS) == {'qwen', 'cosy', 'vox'}
        print('Launcher check OK:', platform.system(), platform.machine(), sys.version.split()[0])
        return
    url = f'http://127.0.0.1:{args.port}'
    try:
        with urllib.request.urlopen(url + '/state', timeout=1) as r:
            already = json.load(r).get('product') == 'TTS-speech'
    except (OSError, ValueError):
        already = False
    if already:
        if args.start:
            request = urllib.request.Request(url + '/start', data=json.dumps({'engine': args.start}).encode(), headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(request, timeout=5).close()
        if not NO_BROWSER:
            webbrowser.open(url)
        return
    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    if args.start:
        request_start(args.start)
    print('TTS-speech:', url, flush=True)
    if not NO_BROWSER:
        webbrowser.open(url)
    def stop(*_):
        raise KeyboardInterrupt
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for child in list(CHILDREN.values()):
            if child.poll() is None:
                child.terminate()


if __name__ == '__main__':
    main()
