'use strict';

const WORKFLOWS = {
  transcribe: ['錄音轉多軌 MIDI', '保留原演奏時間，可另做量化、輸出樂譜或試聽。', '.wav,.flac,.mp3,.m4a,.aac,.aif,.aiff,.ogg,.opus'],
  scan: ['五線譜辨識', '從掃描譜建立 MusicXML 與 MIDI。PDF 頁碼留空會讀取全部頁面。', '.pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff'],
  quantize: ['MIDI 量化與排譜', '依原有速度或指定拍點校正音符。保留原本的音色與力度。', '.mid,.midi'],
  render: ['樂譜與 MIDI 轉音檔', '可載入 MusicXML、MuseScore 樂譜或 MIDI，選擇 SoundFont 後離線合成。', '.musicxml,.xml,.mxl,.mscz,.mscx,.mid,.midi'],
};
const STAGES = {
  Queued: '排隊中', Complete: '完成', Failed: '失敗',
  'Transcribing audio': '正在轉寫音符與分軌',
  'Reading staff notation': '正在辨識五線譜',
  'Exporting the score': '正在匯出樂譜',
  'Putting notes on the beat grid': '正在對齊拍格',
  'Engraving the MIDI as sheet music': '正在建立樂譜',
  'Converting score to MIDI': '正在匯出 MIDI',
  'Rendering audio with the SoundFont': '正在渲染音檔',
};
const find = (query) => document.querySelector(query);
const form = find('#job-form');
const input = find('#input-file');
const field = (name) => form.elements.namedItem(name);
const result = find('#result-body');
const status = find('#status');
const message = find('#form-message');
let task = 'transcribe';
let selectedJob = null;
let timer;

function setTask(name) {
  task = name;
  const [title, description, extensions] = WORKFLOWS[name];
  find('#tool-title').textContent = title;
  find('#tool-description').textContent = description;
  find('#formats').textContent = extensions.split(',').map((suffix) => suffix.slice(1).toUpperCase()).join(' · ');
  input.accept = extensions;
  input.value = '';
  find('#file-name').textContent = '選擇要處理的檔案';
  for (const button of document.querySelectorAll('[data-task]')) button.setAttribute('aria-current', String(button.dataset.task === task));
  find('#scan-options').hidden = task !== 'scan';
  const timing = find('#tempo-options');
  timing.hidden = !['transcribe', 'quantize'].includes(task);
  timing.open = task === 'quantize';
  field('grid').value = task === 'quantize' ? 'sixteenth' : '';
  field('render').checked = false;
  showRenderOptions();
}

function showRenderOptions() {
  const rendering = task === 'render' || field('render').checked;
  find('#also-audio').hidden = task === 'render';
  find('#render-options').hidden = !rendering;
  find('#font-file').hidden = !rendering || field('bank').value !== 'upload';
  find('#font-url').hidden = !rendering || field('bank').value !== 'url';
  field('soundfont').required = !find('#font-file').hidden;
  field('soundfont_url').required = !find('#font-url').hidden;
  field('soundfont_url').disabled = find('#font-url').hidden;
}

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map((issue) => issue.msg).join(' · ') : data.detail || response.statusText);
  return data;
}

function add(parent, name, text, className) {
  const child = document.createElement(name);
  if (text) child.textContent = text;
  if (className) child.className = className;
  parent.append(child);
  return child;
}

function showTracks(midi) {
  if (!midi.tracks.length) return;
  const table = add(result, 'table');
  table.setAttribute('aria-label', midi.name);
  const header = add(add(table, 'thead'), 'tr');
  for (const label of ['MIDI 聲部', '音符數', 'Velocity']) add(header, 'th', label);
  const body = add(table, 'tbody');
  for (const track of midi.tracks) {
    const row = add(body, 'tr');
    add(row, 'td', track.name || '未命名');
    add(row, 'td', String(track.notes));
    add(row, 'td', track.velocity_range.join('–'));
  }
  if (midi.tempos.length) add(result, 'p', `${midi.tempos[0].bpm} BPM · ${midi.tempos.length} 個速度事件`, 'hint');
}

function showJob(job) {
  result.replaceChildren();
  status.textContent = STAGES[job.stage] || job.stage;
  status.dataset.state = job.status;
  const path = `/v1/jobs/${job.id}/files/`;
  if (job.status === 'failed') {
    add(result, 'p', job.error, 'failure');
    add(result, 'a', '查看處理日誌').href = path + 'log.txt';
    return;
  }
  if (job.status !== 'done') {
    add(result, 'p', job.source, 'empty');
    return;
  }
  for (const name of job.files.filter((file) => /\.(wav|mp3|flac)$/.test(file))) {
    const player = add(result, 'audio');
    player.src = path + encodeURIComponent(name);
    player.controls = true;
    player.preload = 'metadata';
    player.setAttribute('aria-label', name);
  }
  if (job.files.includes('score-preview.svg')) {
    const preview = add(add(result, 'div', null, 'sheet-preview'), 'img');
    preview.src = path + 'score-preview.svg';
    preview.alt = '樂譜第一頁預覽';
  }
  if (job.midi?.length) showTracks(job.midi[0]);
  const downloads = add(result, 'ul', null, 'files');
  for (const name of job.files) {
    const link = add(add(downloads, 'li'), 'a', name);
    link.href = path + encodeURIComponent(name);
    link.download = name;
  }
  for (const warning of job.warnings || []) add(result, 'p', warning, 'warning');
}

async function refreshHistory() {
  const jobs = await request('/v1/jobs');
  const list = find('#history-list');
  list.replaceChildren();
  for (const job of jobs.slice(0, 12)) {
    const row = add(add(list, 'li'), 'button', job.source);
    row.type = 'button';
    row.title = job.source;
    add(row, 'small', STAGES[job.stage] || job.stage);
    row.addEventListener('click', () => selectJob(job.id));
  }
}

async function selectJob(id) {
  clearTimeout(timer);
  selectedJob = id;
  try {
    const job = await request(`/v1/jobs/${id}`);
    if (selectedJob !== id) return;
    showJob(job);
    if (job.status === 'running' || job.status === 'queued') timer = setTimeout(() => selectJob(id), 1250);
    else refreshHistory().catch(() => {});
  } catch (error) {
    if (selectedJob === id) status.textContent = error.message;
  }
}

for (const button of document.querySelectorAll('[data-task]')) button.addEventListener('click', () => setTask(button.dataset.task));
for (const name of ['bank', 'render']) field(name).addEventListener('change', showRenderOptions);
field('bpm').addEventListener('input', () => { field('downbeat').disabled = !field('bpm').value; });
input.addEventListener('change', () => { find('#file-name').textContent = input.files[0]?.name || '選擇要處理的檔案'; });

const dropzone = find('#dropzone');
dropzone.addEventListener('dragover', (event) => { event.preventDefault(); dropzone.classList.add('active'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('active'));
dropzone.addEventListener('drop', (event) => {
  event.preventDefault();
  dropzone.classList.remove('active');
  const file = event.dataTransfer.files[0];
  if (file) {
    const contents = new DataTransfer();
    contents.items.add(file);
    input.files = contents.files;
    input.dispatchEvent(new Event('change'));
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  message.hidden = true;
  const button = find('#submit');
  button.disabled = true;
  button.textContent = '送出中…';
  try {
    const options = { render: field('render').checked, audio_format: field('audio_format').value };
    const data = new FormData();
    data.set('task', task);
    data.set('file', input.files[0]);
    if (task === 'scan') {
      options.pages = field('pages').value;
      options.detector = field('detector').value;
    }
    if (task === 'transcribe' || task === 'quantize') {
      const number = (name) => field(name).value === '' ? null : Number(field(name).value);
      options.grid = field('grid').value || null;
      options.strength = number('strength') === null ? 1 : number('strength') / 100;
      options.bpm = number('bpm');
      options.downbeat = options.bpm ? (number('downbeat') || 0) : 0;
      options.meter = field('meter').value.trim() || null;
      options.sheet = field('sheet').checked;
      try { options.beats = field('beats').value.trim() ? JSON.parse(field('beats').value) : null; }
      catch { throw new Error('拍點請輸入 JSON 數字陣列，例如 [0, 0.5, 1.0]。'); }
    }
    if (task === 'render' || options.render) {
      if (field('bank').value === 'kobi-microscopic') options.soundfont_bank = 'kobi-microscopic';
      if (field('bank').value === 'url') options.soundfont_url = field('soundfont_url').value;
      if (field('bank').value === 'upload') data.set('soundfont', field('soundfont').files[0]);
    }
    data.set('options', JSON.stringify(options));
    const job = await request('/v1/jobs', { method: 'POST', body: data });
    selectJob(job.id);
    refreshHistory().catch(() => {});
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.textContent = '開始處理';
    button.disabled = false;
  }
});

setTask(task);
refreshHistory().catch(() => {});
request('/v1/capabilities').then(({ builtin_banks }) => {
  field('bank').querySelector('[value="kobi-microscopic"]').disabled = !builtin_banks['kobi-microscopic'];
}).catch(() => {});
