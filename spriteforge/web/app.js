/* spriteforge Web UI: upload -> poll -> preview (sheet / animation / grid) -> export.
   No build step, no framework. Animation uses the individual frame PNGs
   (not the sheet), so what you see is exactly what Unity will get per frame. */
(function () {
  'use strict';
  var fileInput = document.getElementById('file-input');
  var dropzone = document.getElementById('dropzone');
  var pickBtn = document.getElementById('pick-btn');
  var fileInfo = document.getElementById('file-info');
  var sourcePreview = document.getElementById('source-preview');
  var startBtn = document.getElementById('start-btn');
  var retryBtn = document.getElementById('retry-btn');
  var retryHint = document.getElementById('retry-hint');
  var statusText = document.getElementById('status-text');
  var progressBar = document.getElementById('progress-bar');
  var errorBox = document.getElementById('error');
  var resultCard = document.getElementById('result-card');
  var sheetImg = document.getElementById('sheet-img');
  var animImg = document.getElementById('anim-img');
  var playBtn = document.getElementById('play-btn');
  var pauseBtn = document.getElementById('pause-btn');
  var scrubber = document.getElementById('scrubber');
  var frameLabel = document.getElementById('frame-label');
  var frameGrid = document.getElementById('frame-grid');
  var historyGrid = document.getElementById('history-grid');
  var refreshHistoryBtn = document.getElementById('refresh-history-btn');
  var historySelectAll = document.getElementById('history-select-all');
  var historyDeleteSelectedBtn = document.getElementById('history-delete-selected-btn');
  var resetParamsBtn = document.getElementById('reset-params-btn');
  var PARAMS_KEY = 'spriteforge-params';
  var historyPrefillDone = false;
  var historyJobs = [];
  var modalFrameNames = [];
  var modalFrameIndex = 0;
  var modalAnimTimer = null;
  var modalAnimFps = 12;
  var modalJobId = null;

  var selectedFile = null;
  var jobId = null;
  var pollTimer = null;
  // Elapsed timer: ticks every second independently of the 1.5s poll,
  // so the progress card keeps visibly moving even while the backend
  // percentage is stuck (e.g. at 20% during a first-time model download).
  var elapsedTimer = null;
  var elapsedStart = null;
  var frameNames = [];
  var frameIndex = 0;
  var animTimer = null;
  var animFps = 12;

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = false;
  }
  function clearError() {
    errorBox.textContent = '';
    errorBox.hidden = true;
  }
  function setStatus(text, progress) {
    statusText.textContent = text;
    progressBar.style.width = (progress || 0) + '%';
  }
  function formatElapsed(ms) {
    var total = Math.max(0, Math.floor(ms / 1000));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    return h > 0 ? h + ':' + pad(m) + ':' + pad(s) : pad(m) + ':' + pad(s);
  }
  function updateElapsed() {
    if (!elapsedStart) return;
    document.getElementById('elapsed-text').textContent =
      '已用时 ' + formatElapsed(Date.now() - elapsedStart);
  }
  function startElapsed() {
    stopElapsed();
    elapsedStart = Date.now();
    updateElapsed();
    elapsedTimer = setInterval(updateElapsed, 1000);
  }
  function stopElapsed() {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
  }
  function setStep(step) {
    var el = document.getElementById('status-step');
    el.textContent = step ? ' · ' + step : '';
  }
  function readFormParams() {
    return {
      fps: document.getElementById('fps').value,
      columns: document.getElementById('columns').value,
      spacing: document.getElementById('spacing').value,
      model: document.getElementById('model').value,
      max_size: document.getElementById('max-size').value,
      target_size: document.getElementById('target-size').value.trim(),
      temporal_smoothing: document.getElementById('smoothing').checked,
      despill: document.getElementById('despill').checked,
      despill_strength: document.getElementById('despill-strength').value,
      despill_color: document.getElementById('despill-color').value,
      despill_custom_color: document.getElementById('despill-custom-color').value
    };
  }
  function applyParams(p) {
    if (!p || typeof p !== 'object') return;
    function setValue(id, v) {
      if (v === undefined || v === null) return;
      document.getElementById(id).value = v;
    }
    function setChecked(id, v) {
      if (v === undefined || v === null) return;
      document.getElementById(id).checked = (v === true || v === 'true' || v === 1 || v === '1');
    }
    setValue('fps', p.fps);
    setValue('columns', p.columns);
    setValue('spacing', p.spacing);
    setValue('max-size', p.max_size);
    setValue('target-size', p.target_size === null ? '' : p.target_size);
    setValue('despill-strength', p.despill_strength);
    setValue('despill-custom-color', p.despill_custom_color);
    setChecked('smoothing', p.temporal_smoothing);
    setChecked('despill', p.despill);
    if (p.despill_color) {
      var colorEl = document.getElementById('despill-color');
      var colorFound = false;
      for (var j = 0; j < colorEl.options.length; j++) {
        if (colorEl.options[j].value === p.despill_color) { colorFound = true; break; }
      }
      if (colorFound) colorEl.value = p.despill_color;
    }
    updateDespillCustomRow();
    if (p.model) {
      var modelEl = document.getElementById('model');
      var found = false;
      for (var i = 0; i < modelEl.options.length; i++) {
        if (modelEl.options[i].value === p.model) { found = true; break; }
      }
      if (found) modelEl.value = p.model;
    }
  }
  function updateDespillGroup() {
    // Group state: inner controls are disabled while despill is off,
    // and the custom colour picker only appears when the backdrop
    // itself is set to "custom" (and despill is on).
    var on = document.getElementById('despill').checked;
    document.getElementById('despill-color').disabled = !on;
    document.getElementById('despill-strength').disabled = !on;
    document.getElementById('despill-custom-color').disabled = !on;
    var row = document.getElementById('despill-custom-color-row');
    if (row) row.hidden = !on || document.getElementById('despill-color').value !== 'custom';
  }
  // Kept name for callers below; it now updates the whole group.
  function updateDespillCustomRow() { updateDespillGroup(); }
  document.getElementById('despill-color').addEventListener('change', updateDespillGroup);
  document.getElementById('despill').addEventListener('change', updateDespillGroup);
  function saveLastParams() {
    try { localStorage.setItem(PARAMS_KEY, JSON.stringify(readFormParams())); } catch (e) {}
  }
  function loadLastParamsFromStorage() {
    try {
      var raw = localStorage.getItem(PARAMS_KEY);
      if (!raw) return false;
      applyParams(JSON.parse(raw));
      return true;
    } catch (e) { return false; }
  }
  function resetParams() {
    applyParams({
      fps: '12', columns: '6', spacing: '4', model: 'birefnet-general',
      max_size: '720', target_size: '', temporal_smoothing: true,
      despill: true, despill_strength: '1.0',
      despill_color: 'green', despill_custom_color: '#00ff00'
    });
    // Save the defaults too, so a later page load (and the history
    // fallback below) does not bring the old params back.
    saveLastParams();
  }
  if (resetParamsBtn) resetParamsBtn.addEventListener('click', resetParams);
  function formatTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleString();
  }
  function updateHistorySelection() {
    if (!historyGrid) return;
    var boxes = historyGrid.querySelectorAll('.history-select');
    var checked = 0;
    boxes.forEach(function (b) { if (b.checked) checked++; });
    if (historyDeleteSelectedBtn) {
      historyDeleteSelectedBtn.disabled = checked === 0;
      historyDeleteSelectedBtn.textContent = checked ? '删除选中（' + checked + '）' : '删除选中';
    }
    if (historySelectAll) {
      historySelectAll.checked = boxes.length > 0 && checked === boxes.length;
    }
  }
  async function deleteHistoryJobs(ids) {
    if (!ids.length) return;
    if (!confirm('确定删除选中的 ' + ids.length + ' 个任务吗？原视频、单帧和合图都会一起删掉，无法恢复。')) return;
    try {
      var res = await fetch('/api/jobs/batch-delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: ids })
      });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok) throw new Error(data.detail || ('删除失败（' + res.status + '）'));
      if (data.failed && data.failed.length) {
        showError('部分删除失败：' + data.failed.map(function (f) { return f.id + '（' + (f.error || '未知错误') + '）'; }).join('；'));
      }
      if (jobId && ids.indexOf(jobId) >= 0) resultCard.hidden = true;
      loadHistory();
    } catch (err) {
      showError(err.message);
    }
  }
  function stopModalAnim() { if (modalAnimTimer) { clearInterval(modalAnimTimer); modalAnimTimer = null; } }
  function showModalFrame(i) {
    if (!modalFrameNames.length || !modalJobId) return;
    modalFrameIndex = (i + modalFrameNames.length) % modalFrameNames.length;
    document.getElementById('preview-modal-anim').src =
      '/api/jobs/' + modalJobId + '/frames/' + encodeURIComponent(modalFrameNames[modalFrameIndex]);
    document.getElementById('preview-modal-scrubber').value = modalFrameIndex;
    document.getElementById('preview-modal-frame-label').textContent =
      (modalFrameIndex + 1) + ' / ' + modalFrameNames.length;
  }
  function playModalAnim() {
    stopModalAnim();
    modalAnimTimer = setInterval(function () { showModalFrame(modalFrameIndex + 1); }, 1000 / Math.max(modalAnimFps, 1));
  }
  function closePreviewModal() {
    stopModalAnim();
    document.getElementById('preview-modal').hidden = true;
  }
  async function openPreviewModal(job) {
    var r = await fetch('/api/jobs/' + job.id);
    if (!r.ok) { showError('查看失败（' + r.status + '）'); return; }
    var full = await r.json();
    modalJobId = full.id;
    modalFrameNames = full.frames || [];
    modalAnimFps = (full.params && full.params.fps) || 12;
    document.getElementById('preview-modal-title').textContent =
      formatTime(full.created_at) + ' · ' + full.id + ' · ' + (full.frame_count || 0) + ' 帧';
    document.getElementById('preview-modal-sheet').src = '/api/jobs/' + full.id + '/sprite.png';
    document.getElementById('preview-modal-dl-zip').href = '/api/jobs/' + full.id + '/export.zip';
    document.getElementById('preview-modal-dl-sprite').href = '/api/jobs/' + full.id + '/sprite.png';
    document.getElementById('preview-modal-scrubber').max = Math.max(modalFrameNames.length - 1, 0);
    document.getElementById('preview-modal').hidden = false;
    if (modalFrameNames.length) { showModalFrame(0); playModalAnim(); }
  }
  document.getElementById('preview-modal-close').addEventListener('click', closePreviewModal);
  document.getElementById('preview-modal-backdrop').addEventListener('click', closePreviewModal);
  document.getElementById('preview-modal-play').addEventListener('click', playModalAnim);
  document.getElementById('preview-modal-pause').addEventListener('click', stopModalAnim);
  document.getElementById('preview-modal-scrubber').addEventListener('input', function () {
    stopModalAnim(); showModalFrame(parseInt(this.value, 10) || 0);
  });
  async function loadHistory() {
    if (!historyGrid) return;
    try {
      var res = await fetch('/api/jobs');
      if (!res.ok) throw new Error('历史加载失败（' + res.status + '）');
      var data = await res.json();
      var jobs = data.jobs || [];
      historyJobs = jobs;
      // First history load only, and only if this browser has no saved
      // params: fall back to the most recent history job, so a new
      // browser / device still starts from the last used params.
      // Later refreshes must not overwrite what the user is editing.
      if (!historyPrefillDone) {
        historyPrefillDone = true;
        try {
          if (!localStorage.getItem(PARAMS_KEY) && jobs.length && jobs[0].params) {
            applyParams(jobs[0].params);
          }
        } catch (e) {}
      }
      historyGrid.innerHTML = '';
      if (!jobs.length) {
        historyGrid.textContent = '暂无历史记录。';
        updateHistorySelection();
        return;
      }
      jobs.forEach(function (job) {
        var card = document.createElement('div');
        card.className = 'history-card';
        var params = job.params || {};
        var check = document.createElement('input');
        check.type = 'checkbox';
        check.className = 'history-select';
        check.dataset.id = job.id;
        check.addEventListener('change', updateHistorySelection);
        card.appendChild(check);
        if (job.status === 'completed') {
          var thumb = document.createElement('img');
          thumb.src = '/api/jobs/' + job.id + '/sprite.png';
          thumb.alt = 'Sprite Sheet 预览';
          thumb.loading = 'lazy';
          thumb.addEventListener('click', function () { openPreviewModal(job); });
          card.appendChild(thumb);
        } else {
          var noPreview = document.createElement('p');
          noPreview.className = 'hint';
          noPreview.textContent = job.status === 'failed' ? '生成失败，无预览图' : '进行中，无预览图';
          card.appendChild(noPreview);
        }
        var title = document.createElement('p');
        title.textContent = formatTime(job.created_at) + ' · ' + job.id +
          ' · ' + job.status + ' · ' + (job.frame_count || 0) + ' 帧' +
          ' · 模型 ' + (params.model || '—') +
          ' · fps ' + (params.fps || '—') +
          (params.filename ? ' · ' + params.filename : '');
        card.appendChild(title);
        if (job.status === 'failed' && job.error) {
          var err = document.createElement('p');
          err.className = 'error';
          err.textContent = job.error;
          card.appendChild(err);
        }
        if (job.status === 'completed') {
          var previewBtn = document.createElement('button');
          previewBtn.type = 'button';
          previewBtn.textContent = '预览';
          previewBtn.addEventListener('click', function () { openPreviewModal(job); });
          card.appendChild(previewBtn);
          var dlZip = document.createElement('a');
          dlZip.href = '/api/jobs/' + job.id + '/export.zip';
          dlZip.download = 'spriteforge-export.zip';
          dlZip.textContent = '下载 ZIP';
          card.appendChild(dlZip);
        }
        var delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.textContent = '删除';
        delBtn.addEventListener('click', function () { deleteHistoryJobs([job.id]); });
        card.appendChild(delBtn);
        historyGrid.appendChild(card);
      });
      updateHistorySelection();
    } catch (err) {
      historyGrid.textContent = err.message;
    }
  }
  if (refreshHistoryBtn) refreshHistoryBtn.addEventListener('click', loadHistory);
  if (historySelectAll) historySelectAll.addEventListener('change', function () {
    var boxes = historyGrid.querySelectorAll('.history-select');
    boxes.forEach(function (b) { b.checked = historySelectAll.checked; });
    updateHistorySelection();
  });
  if (historyDeleteSelectedBtn) historyDeleteSelectedBtn.addEventListener('click', function () {
    var boxes = historyGrid.querySelectorAll('.history-select:checked');
    var ids = [];
    boxes.forEach(function (b) { ids.push(b.dataset.id); });
    deleteHistoryJobs(ids);
  });
  function switchTab(name) {
    var isHistory = name === 'history';
    document.getElementById('tab-generate').hidden = isHistory;
    document.getElementById('tab-history').hidden = !isHistory;
    document.getElementById('tab-btn-generate').classList.toggle('active', !isHistory);
    document.getElementById('tab-btn-history').classList.toggle('active', isHistory);
    document.getElementById('tab-btn-generate').setAttribute('aria-selected', !isHistory ? 'true' : 'false');
    document.getElementById('tab-btn-history').setAttribute('aria-selected', isHistory ? 'true' : 'false');
    if (isHistory) loadHistory();
  }
  document.getElementById('tab-btn-generate').addEventListener('click', function () { switchTab('generate'); });
  document.getElementById('tab-btn-history').addEventListener('click', function () { switchTab('history'); });
  function showRetry(show) {
    // Retry reuses the already-selected file and current form params,
    // so it only makes sense while that file is still in memory.
    var ok = !!show && !!selectedFile;
    retryBtn.hidden = !ok;
    retryHint.hidden = !ok;
  }
  function setFile(file) {
    if (!file) return;
    selectedFile = file;
    fileInfo.textContent = '已选择：' + file.name + '（' + (file.size / 1048576).toFixed(1) + ' MB）';
    if (sourcePreview.src) URL.revokeObjectURL(sourcePreview.src);
    sourcePreview.src = URL.createObjectURL(file);
    sourcePreview.hidden = false;
    startBtn.disabled = false;
  }

  pickBtn.addEventListener('click', function () { fileInput.click(); });
  fileInput.addEventListener('change', function () { setFile(fileInput.files[0]); });
  dropzone.addEventListener('click', function (e) {
    if (e.target !== pickBtn) fileInput.click();
  });
  dropzone.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
  });
  ['dragover', 'dragenter'].forEach(function (ev) {
    dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.add('drag'); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    dropzone.addEventListener(ev, function (e) { e.preventDefault(); dropzone.classList.remove('drag'); });
  });
  dropzone.addEventListener('drop', function (e) {
    if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
  });

  function frameUrl(name) { return '/api/jobs/' + jobId + '/frames/' + encodeURIComponent(name); }
  function showFrame(i) {
    if (!frameNames.length) return;
    frameIndex = (i + frameNames.length) % frameNames.length;
    animImg.src = frameUrl(frameNames[frameIndex]);
    scrubber.value = frameIndex;
    frameLabel.textContent = (frameIndex + 1) + ' / ' + frameNames.length;
    var thumbs = frameGrid.querySelectorAll('img');
    thumbs.forEach(function (img, j) { img.classList.toggle('active', j === frameIndex); });
  }
  function stopAnim() { if (animTimer) { clearInterval(animTimer); animTimer = null; } }
  function playAnim() {
    stopAnim();
    animTimer = setInterval(function () { showFrame(frameIndex + 1); }, 1000 / Math.max(animFps, 1));
  }
  playBtn.addEventListener('click', playAnim);
  pauseBtn.addEventListener('click', stopAnim);
  scrubber.addEventListener('input', function () { stopAnim(); showFrame(parseInt(scrubber.value, 10) || 0); });

  function showResult(job) {
    frameNames = job.frames || [];
    animFps = (job.params && job.params.fps) || 12;
    sheetImg.src = '/api/jobs/' + jobId + '/sprite.png';
    document.getElementById('dl-sprite').href = '/api/jobs/' + jobId + '/sprite.png';
    document.getElementById('dl-index').href = '/api/jobs/' + jobId + '/index.json';
    document.getElementById('dl-zip').href = '/api/jobs/' + jobId + '/export.zip';
    frameGrid.innerHTML = '';
    frameNames.forEach(function (name, i) {
      var img = document.createElement('img');
      img.src = frameUrl(name);
      img.alt = name;
      img.loading = 'lazy';
      img.addEventListener('click', function () { stopAnim(); showFrame(i); });
      frameGrid.appendChild(img);
    });
    scrubber.max = Math.max(frameNames.length - 1, 0);
    resultCard.hidden = false;
    showFrame(0);
    playAnim();
  }

  async function poll() {
    try {
      var res = await fetch('/api/jobs/' + jobId);
      if (!res.ok) throw new Error('查询任务失败（' + res.status + '）');
      var job = await res.json();
      setStatus('任务 ' + jobId + '：' + job.status + '（' + job.progress + '%）', job.progress);
      setStep(job.message || '');
      if (job.status === 'completed') {
        clearInterval(pollTimer);
        stopElapsed();
        updateElapsed();
        setStatus('完成：共 ' + (job.frame_count || 0) + ' 帧', 100);
        setStep('完成');
        startBtn.disabled = false;
        showRetry(false);
        showResult(job);
        loadHistory();
      } else if (job.status === 'failed') {
        clearInterval(pollTimer);
        stopElapsed();
        updateElapsed();
        setStep('生成失败');
        showError('生成失败：' + (job.error || '未知错误') +
          '。常见原因：缺少 ffmpeg（请安装并加入 PATH）、模型首次下载失败（请检查网络后重试）。');
        // Terminal state: the start button must become usable again,
        // and retry offers one-click regeneration with the same file.
        // loadHistory() here only refreshes other jobs: failed jobs
        // are deleted on the server and filtered out of history.
        startBtn.disabled = false;
        showRetry(true);
        loadHistory();
      }
    } catch (err) {
      clearInterval(pollTimer);
      stopElapsed();
      setStep('查询失败，计时已停止');
      showError('查询任务失败：' + err.message);
      startBtn.disabled = false;
      showRetry(true);
    }
  }

  async function startJob() {
    clearError();
    showRetry(false);
    if (!selectedFile) { showError('请先导入视频。'); return; }
    saveLastParams();
    var form = new FormData();
    form.append('file', selectedFile);
    form.append('fps', document.getElementById('fps').value);
    form.append('columns', document.getElementById('columns').value);
    form.append('spacing', document.getElementById('spacing').value);
    form.append('model', document.getElementById('model').value);
    form.append('max_size', document.getElementById('max-size').value);
    form.append('target_size', document.getElementById('target-size').value.trim());
    form.append('temporal_smoothing', document.getElementById('smoothing').checked ? 'true' : 'false');
    form.append('despill', document.getElementById('despill').checked ? 'true' : 'false');
    form.append('despill_strength', document.getElementById('despill-strength').value);
    form.append('despill_color', document.getElementById('despill-color').value);
    form.append('despill_custom_color', document.getElementById('despill-custom-color').value);
    startBtn.disabled = true;
    resultCard.hidden = true;
    stopAnim();
    startElapsed();
    setStatus('正在上传…', 0);
    setStep('正在上传视频');
    try {
      var res = await fetch('/api/jobs', { method: 'POST', body: form });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok) throw new Error(data.detail || ('上传失败（' + res.status + '）'));
      jobId = data.id;
      setStatus('任务已创建：' + jobId + '，排队中…', 0);
      setStep('排队中');
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(poll, 1500);
      poll();
    } catch (err) {
      stopElapsed();
      setStep('上传失败');
      showError(err.message);
      startBtn.disabled = false;
      showRetry(true);
    }
  }

  document.getElementById('params-form').addEventListener('submit', function (e) {
    e.preventDefault();
    startJob();
  });
  retryBtn.addEventListener('click', function () { startJob(); });
  loadLastParamsFromStorage();
  updateDespillCustomRow();
  loadHistory();
})();
