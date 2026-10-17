"""Local voice synthesis and explicit presentation / optional face animation engines."""
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path


def run(args, *, cwd=None, input=None, timeout=7200):
    result = subprocess.run([str(a) for a in args], cwd=cwd, input=input,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        # Internal diagnostic; callers expose a generic, actionable failure to clients.
        raise RuntimeError(result.stderr.decode(errors='replace')[-3000:])
    return result.stdout


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                           '-of', 'json', path], timeout=60))


def normalize_audio(source, dest):
    # Decode rather than trust extensions; enforce a maximum decoded duration.
    run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', source, '-vn', '-ac', '1',
         '-ar', '22050', '-t', '1801', '-c:a', 'pcm_s16le', dest], timeout=180)
    with wave.open(str(dest)) as wav:
        duration = wav.getnframes() / wav.getframerate()
    if not 1 <= duration <= 1800:
        raise ValueError('El audio debe durar entre 1 segundo y 30 minutos.')
    return duration


def stream_process(args, progress, *, input_text=None, timeout=1800):
    import tempfile
    import threading
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen([str(a) for a in args], stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=errors, text=True, bufsize=1)
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            if input_text is not None:
                proc.stdin.write(input_text)
                proc.stdin.close()
            for line in proc.stdout:
                progress(line.strip())
            if proc.wait():
                errors.seek(0)
                raise RuntimeError(errors.read().decode(errors='replace')[-3000:])
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def synthesize(script, dest, progress=lambda n, total: None):
    import textwrap
    model = Path(os.getenv('PIPER_MODEL', 'models/es_ES-davefx-medium.onnx')).resolve()
    if not model.is_file() or not Path(str(model) + '.json').is_file():
        raise ValueError('La voz no está instalada en el servidor.')
    chunks = [part for sentence in re.split(r'(?<=[.!?])\s+|\n+', script.strip())
              for part in textwrap.wrap(sentence, width=350) if part.strip()]
    helper = r"""
import sys,json,wave
import onnxruntime as ort
from piper.voice import PiperVoice
from piper.config import PiperConfig
model,dest=sys.argv[1:]
parts=json.load(sys.stdin)
options=ort.SessionOptions()
options.intra_op_num_threads=1
options.inter_op_num_threads=1
options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
voice=PiperVoice(session=ort.InferenceSession(model,sess_options=options,providers=['CPUExecutionProvider']),config=PiperConfig.from_dict(json.load(open(model+'.json'))))
with wave.open(dest,'wb') as out:
 out.setnchannels(1);out.setsampwidth(2);out.setframerate(voice.config.sample_rate)
 for i,part in enumerate(parts):
  for audio in voice.synthesize(part):
   out.writeframes(audio.audio_int16_bytes)
  print(i+1,flush=True)
"""
    def update(line):
        if line.isdigit():
            progress(int(line), len(chunks))
    stream_process([sys.executable, '-c', helper, model, dest], update, input_text=json.dumps(chunks), timeout=1800)


def presentation(image, audio, dest, duration, progress=lambda value: None):
    # Image presentation; progress comes from actual encoded timestamps.
    def update(line):
        if line.startswith('out_time_us='):
            try:
                progress(min(95, 25 + int(70 * int(line.split('=',1)[1]) / 1000000 / duration)))
            except ValueError:
                pass
    stream_process(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-filter_threads', '1',
         '-loop', '1', '-i', image, '-i', audio,
         '-vf', "scale=640:680:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0x172c60,setsar=1",
         '-c:v', 'libx264', '-threads', '1', '-preset', 'ultrafast', '-tune', 'stillimage', '-pix_fmt', 'yuv420p',
         '-r', '15', '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart',
         '-progress', 'pipe:1', '-nostats', dest], update, timeout=7200)


def sadtalker(image, audio, dest, job_dir, progress):
    root = Path(os.getenv('SADTALKER_DIR', '')).resolve()
    python = os.getenv('SADTALKER_PYTHON', '')
    if not python or not (root / 'inference.py').is_file():
        raise ValueError('SadTalker no está configurado. Instala su entorno y modelos; consulta LEEME.md.')
    segments = job_dir / 'segments'
    segments.mkdir(exist_ok=True)
    # Bound model memory by generating successive segments; do not feed 10 minutes at once.
    run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', audio, '-f', 'segment',
         '-segment_time', '30', '-c:a', 'pcm_s16le', segments / '%04d.wav'])
    audios = sorted(segments.glob('*.wav'))
    videos = []
    for i, chunk in enumerate(audios):
        result = job_dir / f'face-{i:04d}'
        result.mkdir(exist_ok=True)
        args = [python, root / 'inference.py', '--driven_audio', chunk.resolve(),
                '--source_image', image.resolve(), '--result_dir', result.resolve(),
                '--preprocess', 'full', '--still', '--size', '256']
        if os.getenv('SADTALKER_CPU', '1') == '1':
            args += ['--cpu']
        run(args, cwd=root, timeout=14400)
        # SadTalker writes the final result directly into result_dir; don't select temporary crop files.
        found = sorted(result.glob('*.mp4'), key=lambda p: p.stat().st_mtime)
        if not found:
            raise RuntimeError('SadTalker no produjo un archivo MP4.')
        part = segments / f'{i:04d}.mp4'
        run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-i', found[-1], '-i', chunk,
             '-map', '0:v:0', '-map', '1:a:0', '-vf', 'scale=512:768:force_original_aspect_ratio=decrease,pad=512:768:(ow-iw)/2:(oh-ih)/2,setsar=1',
             '-r', '25', '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p',
             '-c:a', 'aac', '-ar', '22050', '-ac', '1', '-shortest', part])
        videos.append(part)
        progress(25 + int(65 * (i+1) / len(audios)))
    listing = segments / 'concat.txt'
    listing.write_text(''.join("file '" + p.name + "'\n" for p in videos))
    run(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-f', 'concat', '-safe', '1', '-i', listing,
         '-c', 'copy', '-movflags', '+faststart', dest])

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, Request, Response
import hashlib
import base64
from collections import OrderedDict
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError



ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('VIDEO_DATA', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
TOKEN = os.getenv('VIDEO_API_TOKEN', '')
Image.MAX_IMAGE_PIXELS = 20_000_000
log = logging.getLogger('global-video')


def db():
    con = sqlite3.connect(DATA / 'jobs.sqlite', timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, title TEXT, engine TEXT, status TEXT, progress INTEGER, message TEXT, created REAL, duration REAL)')
        c.execute("UPDATE jobs SET status='failed', message='Servidor reiniciado durante la generación. Crea un nuevo trabajo.' WHERE status='processing'")


def change(job, **values):
    allowed = {'status', 'progress', 'message', 'duration'}
    if not values.keys() <= allowed:
        raise ValueError('Invalid fields')
    with db() as c:
        c.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', [*values.values(), job])


def get(job):
    if not re.fullmatch(r'[a-f0-9]{32}', job):
        raise HTTPException(404, 'Trabajo no encontrado')
    with db() as c:
        row = c.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Trabajo no encontrado')
    return dict(row)


def process(job):
    folder = DATA / job['id']
    try:
        change(job['id'], status='processing', progress=5, message='Cargando la voz española…')
        raw = folder / 'input-audio'
        if not raw.exists():
            raw = folder / 'speech.wav'
            synthesize((folder / 'script.txt').read_text(), raw, lambda n,total: change(job['id'], progress=5 + int(19*n/total), message=f'Creando narración: fragmento {n} de {total}.'))
        change(job['id'], message='Preparando el audio…')
        duration = normalize_audio(raw, folder / 'audio.wav')
        change(job['id'], duration=duration, progress=25, message='Generando el archivo MP4…')
        if job['engine'] == 'sadtalker':
            sadtalker(folder / 'image.png', folder / 'audio.wav', folder / 'video.mp4', folder,
                      lambda v: change(job['id'], progress=v))
        else:
            presentation(folder / 'image.png', folder / 'audio.wav', folder / 'video.mp4', duration, lambda n: change(job['id'], progress=n, message='Generando el archivo MP4…'))
        change(job['id'], progress=98, message='Verificando audio y video…')
        actual = float(probe(folder / 'video.mp4')['format']['duration'])
        if abs(actual - duration) > max(2, duration * .02):
            raise RuntimeError('La duración del video no coincide con el audio.')
        change(job['id'], status='completed', progress=100, message='Video listo para descargar.', duration=actual)
    except ValueError as e:
        change(job['id'], status='failed', message=str(e))
    except Exception:
        log.exception('Job failed: %s', job['id'])
        change(job['id'], status='failed', message='No se pudo generar el video. Revisa los registros del servidor y la instalación del motor.')


async def worker():
    while True:
        with db() as c:
            row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
        if row:
            await asyncio.to_thread(process, dict(row))
        else:
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app):
    if len(TOKEN) < 24 or TOKEN.startswith('REPLACE_'):
        raise RuntimeError('Configura VIDEO_API_TOKEN con un valor aleatorio de al menos 24 caracteres.')
    init_db()
    task = asyncio.create_task(worker())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title='Global Video Server', lifespan=lifespan)
origins = [v.strip() for v in os.getenv('VIDEO_ALLOWED_ORIGINS', '').split(',') if v.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST'], allow_headers=['Authorization'])


LOGIN_USER = os.getenv('LOGIN_USERNAME', 'jairo')
PASSWORD_HASH = os.getenv('LOGIN_PASSWORD_HASH', '')
COOKIE = '__Host-global_session'
SESSION_SECONDS = 8 * 3600
attempts = OrderedDict()


def same_origin(request):
    origin = request.headers.get('origin')
    if origin and origin != 'https://' + request.headers.get('host', ''):
        raise HTTPException(403, 'Origen no permitido')


def signature(payload):
    key = (TOKEN + PASSWORD_HASH).encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def valid_session(value):
    try:
        payload, sig = value.rsplit('.', 1)
        username, expiry, nonce = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return (hmac.compare_digest(sig, signature(payload)) and username == LOGIN_USER
                and time.time() < expiry <= time.time() + SESSION_SECONDS + 60)
    except (ValueError, TypeError, json.JSONDecodeError):
        return False


def auth(request: Request, authorization: str = Header(default='')):
    # Server integrations retain their separate secret; it is never sent to the browser.
    if authorization and hmac.compare_digest(authorization, 'Bearer ' + TOKEN):
        return
    if not valid_session(request.cookies.get(COOKIE, '')):
        raise HTTPException(401, 'Inicia sesión para continuar.')
    if request.method not in ('GET', 'HEAD'):
        same_origin(request)


@app.post('/api/login')
def login(request: Request, response: Response, username: str = Form(...), password: str = Form(...)):
    same_origin(request)
    address = request.client.host if request.client else 'unknown'
    now = time.time()
    count, until = attempts.get(address, (0, now + 300))
    if now > until:
        count, until = 0, now + 300
    if count >= 5:
        raise HTTPException(429, 'Demasiados intentos. Espera cinco minutos.')
    attempts[address] = (count + 1, until)
    attempts.move_to_end(address)
    if len(attempts) > 10000:
        attempts.popitem(last=False)
    if len(password) > 256 or len(username) > 160:
        raise HTTPException(401, 'Usuario o contraseña incorrectos.')
    try:
        rounds, salt, expected = PASSWORD_HASH.split('$')
        supplied = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        correct = hmac.compare_digest(supplied, expected)
    except (ValueError, TypeError):
        raise HTTPException(503, 'El acceso está pendiente de configuración.')
    if len(password) > 256 or not (hmac.compare_digest(username, LOGIN_USER) and correct):
        raise HTTPException(401, 'Usuario o contraseña incorrectos.')
    attempts.pop(address, None)
    payload = base64.urlsafe_b64encode(json.dumps([LOGIN_USER, int(now) + SESSION_SECONDS, secrets.token_hex(16)]).encode()).decode().rstrip('=')
    response.set_cookie(COOKIE, payload + '.' + signature(payload), max_age=SESSION_SECONDS,
                        secure=True, httponly=True, samesite='strict', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return {'username': LOGIN_USER}


@app.get('/api/session', dependencies=[Depends(auth)])
def session(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return {'username': LOGIN_USER}


@app.post('/api/logout')
def logout(request: Request, response: Response):
    same_origin(request)
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='strict', path='/')
    return {'ok': True}


@app.get('/')
def index():
    return FileResponse(ROOT / 'index.html')


@app.get('/avatar')
def avatar():
    return FileResponse(ROOT / 'instructor.png')


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/api/capabilities', dependencies=[Depends(auth)])
def capabilities():
    model = Path(os.getenv('PIPER_MODEL', ROOT / 'models/es_ES-davefx-medium.onnx'))
    face_root = os.getenv('SADTALKER_DIR', '')
    return {'voice_installed': model.is_file() and Path(str(model)+'.json').is_file(),
            'sadtalker_configured': bool(face_root and (Path(face_root)/'inference.py').is_file() and os.getenv('SADTALKER_PYTHON')),
            'max_audio_minutes': 30,
            'notice': 'SadTalker requiere instalación independiente. Anima el rostro, no el cuerpo completo. No hay garantía de detección de rostros de caricatura.'}


async def save_upload(file, path, limit):
    size = 0
    with path.open('wb') as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, 'Archivo demasiado grande')
            out.write(chunk)
    if size == 0:
        raise HTTPException(422, 'El archivo está vacío')


@app.post('/api/jobs', status_code=202, dependencies=[Depends(auth)])
async def create(title: str = Form('Capacitación'), script: str = Form(''),
                 engine: str = Form('presentation'), image: UploadFile | None = File(None),
                 audio: UploadFile | None = File(None)):
    if engine not in ('presentation', 'sadtalker'):
        raise HTTPException(422, 'Motor desconocido')
    if len(title) > 160 or len(script) > 24000 or (not audio and not script.strip()):
        raise HTTPException(422, 'Introduce un guion (máximo 24000 caracteres) o un audio.')
    if engine == 'sadtalker' and not capabilities()['sadtalker_configured']:
        raise HTTPException(409, 'Instala y configura SadTalker antes de seleccionar animación facial.')
    if audio is None and not capabilities()['voice_installed']:
        raise HTTPException(409, 'Descarga la voz Piper o sube tu narración en audio.')
    with db() as c:
        pending = c.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','processing')").fetchone()[0]
    if pending >= 5:
        raise HTTPException(429, 'Hay cinco trabajos pendientes. Espera a que terminen.')
    job = secrets.token_hex(16)
    folder = DATA / job
    folder.mkdir()
    try:
        if image:
            await save_upload(image, folder / 'source', 10 * 1024 * 1024)
            try:
                with Image.open(folder / 'source') as im:
                    im = im.convert('RGB')
                    im.thumbnail((1920,1920))
                    im.save(folder / 'image.png')
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                raise HTTPException(422, 'Imagen no válida')
            (folder / 'source').unlink()
        else:
            (folder / 'image.png').write_bytes((ROOT / 'instructor.png').read_bytes())
        if audio:
            await save_upload(audio, folder / 'input-audio', 100 * 1024 * 1024)
        (folder / 'script.txt').write_text(script.strip())
        with db() as c:
            c.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                      (job,title,engine,'queued',0,'En cola',time.time(),None))
        return {'id': job, 'status': 'queued', 'status_url': f'/api/jobs/{job}'}
    except Exception:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        raise


@app.get('/api/jobs', dependencies=[Depends(auth)])
def list_jobs():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 30')]


@app.get('/api/jobs/{job}', dependencies=[Depends(auth)])
def status(job: str):
    return get(job)


@app.get('/api/jobs/{job}/video', dependencies=[Depends(auth)])
def video(job: str):
    if get(job)['status'] != 'completed':
        raise HTTPException(409, 'El video todavía no está listo')
    path = DATA / job / 'video.mp4'
    if not path.is_file():
        raise HTTPException(404, 'Archivo no encontrado')
    return FileResponse(path, media_type='video/mp4', filename=f'global-video-{job[:8]}.mp4')
