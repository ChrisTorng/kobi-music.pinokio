"""Loopback UI and versioned API for tool callers."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .pipeline import DATA, TASKS, Options, capabilities, execute
from .sound import MAX_FONT_BYTES, check_font

STATIC = Path(__file__).parent / 'static'
JOBS = DATA / 'jobs'


@asynccontextmanager
async def lifespan(app):
    JOBS.mkdir(parents=True, exist_ok=True)
    for state in JOBS.glob('*/job.json'):
        job = read_state(state.parent)
        if job['status'] in {'queued', 'running'}:
            save_state(state.parent, dict(job, status='failed', error='Interrupted by an application restart.'))
    with ThreadPoolExecutor(max_workers=1) as executor:
        app.state.worker = executor
        yield


app = FastAPI(title='Kobi Music Toolkit', version='0.1.0', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1'])
app.mount('/assets', StaticFiles(directory=STATIC), name='assets')


@app.middleware('http')
async def local_forms(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and origin:
        parsed = urlsplit(origin)
        if parsed.scheme != 'http' or parsed.netloc != request.url.netloc:
            return JSONResponse({'detail': 'Open the toolkit locally to submit a job.'}, status_code=403)
    return await call_next(request)


@app.get('/', include_in_schema=False)
def home():
    return FileResponse(STATIC / 'index.html')


@app.get('/v1/capabilities')
def get_capabilities():
    return capabilities()


@app.get('/v1/options-schema')
def options_schema():
    return Options.model_json_schema()


def read_state(folder):
    return json.loads((folder / 'job.json').read_text(encoding='utf-8'))


def save_state(folder, state):
    path = folder / 'job.next'
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(5):
        try:
            path.replace(folder / 'job.json')
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.025)


def job_folder(job_id):
    if re.fullmatch(r'[0-9a-f]{32}', job_id) and (JOBS / job_id / 'job.json').is_file():
        return JOBS / job_id
    raise HTTPException(404, 'Unknown job.')


async def save_upload(upload, target, maximum):
    size = 0
    with target.open('wb') as destination:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > maximum:
                raise HTTPException(413, f'File exceeds {maximum // (1024 * 1024)} MiB.')
            destination.write(chunk)
    if size == 0:
        raise HTTPException(400, 'The uploaded file is empty.')


@app.post('/v1/jobs', status_code=202)
async def start_job(task: str = Form(...), file: UploadFile = File(...),
                    options: str = Form('{}'), soundfont: UploadFile | None = File(None)):
    original = Path((file.filename or 'input').replace('\\', '/')).name
    extension = Path(original).suffix.lower()
    if task not in TASKS or extension not in TASKS[task]:
        raise HTTPException(400, 'This operation does not accept the uploaded file type.')
    try:
        settings = Options.model_validate_json(options)
    except ValidationError as error:
        raise HTTPException(422, json.loads(error.json(include_context=False))) from error
    if soundfont and settings.soundfont_url:
        raise HTTPException(400, 'Choose an uploaded SoundFont or a URL.')
    job_id = uuid4().hex
    folder = JOBS / job_id
    folder.mkdir()
    source = folder / ('input' + extension)
    font = None
    try:
        await save_upload(file, source, 512 * 1024 * 1024)
        if soundfont:
            suffix = Path(soundfont.filename or '').suffix.lower()
            if suffix not in {'.sf2', '.sf3'}:
                raise HTTPException(400, 'Upload an SF2 or SF3 SoundFont.')
            font = folder / ('soundfont' + suffix)
            await save_upload(soundfont, font, MAX_FONT_BYTES)
            check_font(font)
    except (HTTPException, ValueError) as error:
        shutil.rmtree(folder)
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(400, str(error)) from error
    job = {'id': job_id, 'task': task, 'source': original, 'status': 'queued', 'stage': 'Queued', 'files': []}
    save_state(folder, job)
    app.state.worker.submit(work, folder, source, font, settings)
    return job


def work(folder, source, font, options):
    try:
        with (folder / 'worker.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([sys.executable, '-m', 'kobi_music.job_worker', str(folder), str(source),
                                     str(font) if font else ''], input=options.model_dump_json().encode('utf-8'),
                                    stdout=log, stderr=subprocess.STDOUT, timeout=3600, check=False)
        if result.returncode:
            raise RuntimeError(f'Worker exited with code {result.returncode}. See the job log.')
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        worker_log = folder / 'worker.log'
        with (folder / 'log.txt').open('a', encoding='utf-8') as log:
            if worker_log.is_file():
                log.write(worker_log.read_text(encoding='utf-8', errors='replace'))
            log.write(f'\n{error}\n')
        save_state(folder, dict(read_state(folder), status='failed', stage='Failed', error=str(error)))


def run_job(folder, source, font, options):
    job = read_state(folder)

    def progress(stage):
        job.update(status='running', stage=stage)
        save_state(folder, job)

    try:
        with (folder / 'log.txt').open('w', encoding='utf-8') as log:
            report = execute(job['task'], source, folder / 'results', options, font=font, log=log, progress=progress)
        job.update(report, status='done', stage='Complete')
    except Exception as error:
        import traceback

        with (folder / 'log.txt').open('a', encoding='utf-8') as log:
            traceback.print_exc(file=log)
        job.update(status='failed', stage='Failed', error=str(error))
    save_state(folder, job)


@app.get('/v1/jobs')
def recent_jobs():
    folders = sorted(JOBS.glob('*/job.json'), key=lambda path: path.parent.stat().st_ctime, reverse=True)[:25]
    return [read_state(path.parent) for path in folders]


@app.get('/v1/jobs/{job_id}')
def job_status(job_id: str):
    return read_state(job_folder(job_id))


@app.get('/v1/jobs/{job_id}/files/{name}')
def artifact(job_id: str, name: str):
    folder = job_folder(job_id)
    folder_out = (folder / 'results').resolve()
    state = read_state(folder)
    path = folder / 'log.txt' if name == 'log.txt' else (folder_out / name).resolve()
    if name != 'log.txt' and (name not in state['files'] or not path.is_relative_to(folder_out)):
        raise HTTPException(404, 'Unknown artifact.')
    if not path.is_file():
        raise HTTPException(404, 'Artifact unavailable.')
    inline = path.suffix in {'.wav', '.mp3', '.flac', '.svg', '.txt'}
    return FileResponse(path, filename=None if inline else path.name,
                        headers={'Content-Security-Policy': 'sandbox; default-src \'none\''} if path.suffix == '.svg' else None)
