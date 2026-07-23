const state = { devices: [], selectedDevice: null, taskId: null, pollTimer: null };
const $ = (selector) => document.querySelector(selector);
const testGrid = $('#test-grid');

function formatCapacity(bytes) { return `${(bytes / 1024 ** 4).toFixed(2)} TiB`; }
function displayNumber(value, suffix = '') { return value == null ? '—' : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`; }
function setMessage(message, error = false) { const target = $('#form-message'); target.textContent = message; target.style.color = error ? '#b42318' : '#667085'; }

async function scanDevices() {
  const button = $('#scan-button'); button.disabled = true; button.textContent = '正在扫描…';
  try {
    const response = await fetch('/api/devices');
    if (!response.ok) throw new Error((await response.json()).detail || '扫描失败');
    state.devices = await response.json(); renderDevices();
  } catch (error) { $('#device-list').textContent = `扫描失败：${error.message}`; }
  finally { button.disabled = false; button.textContent = '重新扫描'; }
}

function renderDevices() {
  const list = $('#device-list'); list.className = 'device-list'; list.innerHTML = '';
  for (const device of state.devices) {
    const fragment = $('#device-template').content.cloneNode(true);
    const card = fragment.querySelector('.device-card'); const input = fragment.querySelector('input');
    fragment.querySelector('.device-name').textContent = device.name;
    fragment.querySelector('.device-meta').textContent = `${formatCapacity(device.size_bytes)} · ${device.model || '未知型号'} · ${device.temperature_c == null ? '温度未知' : `${device.temperature_c.toFixed(1)} °C`}`;
    const safe = device.safe_to_test;
    fragment.querySelector('.device-state').textContent = safe ? '可测试' : '不可测试';
    fragment.querySelector('.device-reason').textContent = safe ? `序列号：${device.serial || '未知'}` : (device.safety_message || '安全检查未通过');
    input.value = device.name; input.disabled = !safe;
    if (!safe) card.classList.add('unsafe');
    input.addEventListener('change', () => selectDevice(device)); list.appendChild(fragment);
  }
}

function selectDevice(device) {
  state.selectedDevice = device; $('#config-panel').classList.remove('disabled');
  $('#selected-device-text').textContent = `已选择 ${device.name}（${formatCapacity(device.size_bytes)}，${device.model || 'NVMe SSD'}）`;
  $('#confirm-device').textContent = device.name; updateWriteConfirmation();
  $('#config-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function selectedTest() { return document.querySelector('input[name="test"]:checked').value; }
function updateWriteConfirmation() { const write = selectedTest().includes('write'); $('#write-confirm').classList.toggle('hidden', !write); }

function parseExtraOptions() {
  const options = {}; const lines = $('#extra-options').value.split('\n').map((line) => line.trim()).filter(Boolean);
  for (const line of lines) {
    const index = line.indexOf('='); if (index < 1) throw new Error(`额外参数格式错误：${line}`);
    const key = line.slice(0, index).trim(); const raw = line.slice(index + 1).trim();
    if (raw === 'true') options[key] = true; else if (raw === 'false') options[key] = false;
    else if (raw !== '' && !Number.isNaN(Number(raw))) options[key] = Number(raw); else options[key] = raw;
  }
  return options;
}

async function startTest() {
  if (!state.selectedDevice) return;
  const testName = selectedTest(); const isWrite = testName.includes('write');
  if (isWrite && !$('#confirm-destructive').checked) { setMessage('请先确认写入测试会清空目标盘数据。', true); return; }
  try {
    const fioOptions = {
      runtime_seconds: Number($('#runtime').value), ramp_time_seconds: Number($('#ramp').value),
      iodepth: Number($('#iodepth').value), numjobs: Number($('#numjobs').value),
      ioengine: $('#ioengine').value.trim(), direct: $('#direct').checked, ...parseExtraOptions(),
    };
    if (fioOptions.ramp_time_seconds > fioOptions.runtime_seconds) throw new Error('预热时长不能大于测试时长。');
    const response = await fetch('/api/tests', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_name: state.selectedDevice.name, test_name: testName, confirm_destructive: isWrite, fio_options: fioOptions }) });
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || '创建任务失败');
    state.taskId = data.id; $('#result-panel').classList.remove('disabled'); $('#task-id').textContent = `任务 #${data.id}`; $('#task-state').textContent = '任务已创建，正在准备执行…'; $('#progress-wrap').classList.remove('hidden'); $('#progress-fill').style.width = '0%'; $('#progress-percent').textContent = '0%'; $('#metric-grid').classList.add('hidden'); $('#error-box').classList.add('hidden'); setMessage(`已创建任务 #${data.id}`); $('#result-panel').scrollIntoView({ behavior: 'smooth', block: 'start' }); pollResult();
  } catch (error) { setMessage(error.message, true); }
}

async function pollResult() {
  if (!state.taskId) return; clearTimeout(state.pollTimer);
  try {
    const response = await fetch(`/api/results/${state.taskId}`); const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '查询任务失败');
    const progressText = `${data.progress_percent}%（${data.elapsed_seconds}/${data.total_seconds} 秒）`;
    $('#task-state').textContent = data.status === 'queued' ? '任务排队中…' : data.status === 'running' ? `fio ${data.progress_phase}…` : data.status === 'completed' ? '测试完成' : '测试失败';
    $('#progress-label').textContent = data.progress_phase; $('#progress-percent').textContent = progressText; $('#progress-detail').textContent = data.status === 'running' ? '测试正在运行，请勿关闭服务器上的服务。' : '正在等待后台任务开始。'; $('#progress-fill').style.width = `${data.progress_percent}%`;
    if (data.status === 'completed' && data.result) { showMetrics(data.result); $('#progress-wrap').classList.add('hidden'); return; }
    if (data.status === 'failed') { $('#progress-wrap').classList.add('hidden'); $('#error-box').textContent = data.error_message || '任务执行失败'; $('#error-box').classList.remove('hidden'); return; }
    state.pollTimer = setTimeout(pollResult, 2500);
  } catch (error) { $('#error-box').textContent = `无法查询任务：${error.message}`; $('#error-box').classList.remove('hidden'); }
}

function showMetrics(result) {
  $('#metric-iops').textContent = displayNumber(result.iops); $('#metric-bw').textContent = displayNumber(result.bw_mib_s, ' MiB/s');
  $('#metric-latency').textContent = displayNumber(result.latency_avg_us, ' μs'); $('#metric-p99').textContent = displayNumber(result.latency_p99_us, ' μs');
  $('#metric-user-cpu').textContent = displayNumber(result.cpu_user_pct, ' %'); $('#metric-system-cpu').textContent = displayNumber(result.cpu_system_pct, ' %'); $('#metric-grid').classList.remove('hidden');
}

$('#scan-button').addEventListener('click', scanDevices); $('#start-button').addEventListener('click', startTest);
testGrid.addEventListener('change', (event) => { if (event.target.name === 'test') { document.querySelectorAll('.test-card').forEach((card) => card.classList.toggle('selected', card.contains(event.target))); updateWriteConfirmation(); } });
scanDevices();
