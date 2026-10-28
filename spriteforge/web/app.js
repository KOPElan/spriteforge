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

  var selectedFile = null;
  var jobId = null;
  var pollTimer = null;
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
      if (job.status === 'completed') {
        clearInterval(pollTimer);
        setStatus('完成：共 ' + (job.frame_count || 0) + ' 帧', 100);
        showResult(job);
      } else if (job.status === 'failed') {
        clearInterval(pollTimer);
        showError('生成失败：' + (job.error || '未知错误') +
          '。常见原因：缺少 ffmpeg（请安装并加入 PATH）、模型首次下载失败（请检查网络后重试）。');
      }
    } catch (err) {
      clearInterval(pollTimer);
      showError('查询任务失败：' + err.message);
    }
  }

  document.getElementById('params-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    clearError();
    if (!selectedFile) { showError('请先导入视频。'); return; }
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
    startBtn.disabled = true;
    resultCard.hidden = true;
    stopAnim();
    setStatus('正在上传…', 0);
    try {
      var res = await fetch('/api/jobs', { method: 'POST', body: form });
      var data = await res.json().catch(function () { return {}; });
      if (!res.ok) throw new Error(data.detail || ('上传失败（' + res.status + '）'));
      jobId = data.id;
      setStatus('任务已创建：' + jobId + '，排队中…', 0);
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(poll, 1500);
      poll();
    } catch (err) {
      showError(err.message);
      startBtn.disabled = false;
    }
  });
})();
