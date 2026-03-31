const state = {
  snapshot: null,
  logs: [],
  activeView: 'loginView',
  viewTransitionTimer: null,
  navAnimationTimer: null,
};

const dom = {
  navButtons: Array.from(document.querySelectorAll('.nav-icon[data-view]')),
  views: Array.from(document.querySelectorAll('[data-view-panel]')),
  viewStage: document.querySelector('.view-stage'),

  phaseLabel: document.getElementById('phaseLabel'),
  phaseMeta: document.getElementById('phaseMeta'),
  metricPhaseValue: document.getElementById('metricPhaseValue'),
  metricPhaseMeta: document.getElementById('metricPhaseMeta'),
  metricSessionValue: document.getElementById('metricSessionValue'),
  metricSessionMeta: document.getElementById('metricSessionMeta'),
  metricSyncValue: document.getElementById('metricSyncValue'),
  metricSyncMeta: document.getElementById('metricSyncMeta'),
  metricLogValue: document.getElementById('metricLogValue'),
  metricLogMeta: document.getElementById('metricLogMeta'),
  qrShell: document.getElementById('qrShell'),
  qrImage: document.getElementById('qrImage'),
  qrPlaceholder: document.getElementById('qrPlaceholder'),
  loginBadge: document.getElementById('loginBadge'),
  loginTitle: document.getElementById('loginTitle'),
  loginDescription: document.getElementById('loginDescription'),
  channelValue: document.getElementById('channelValue'),
  sessionFileValue: document.getElementById('sessionFileValue'),
  qrExpireValue: document.getElementById('qrExpireValue'),
  updatedAtValue: document.getElementById('updatedAtValue'),
  detailChannelValue: document.getElementById('detailChannelValue'),
  detailSessionFileValue: document.getElementById('detailSessionFileValue'),
  detailSyncValue: document.getElementById('detailSyncValue'),
  detailLastLogValue: document.getElementById('detailLastLogValue'),
  detailQrExpireValue: document.getElementById('detailQrExpireValue'),
  detailUpdatedAtValue: document.getElementById('detailUpdatedAtValue'),
  detailLogFileValue: document.getElementById('detailLogFileValue'),
  detailStartedAtValue: document.getElementById('detailStartedAtValue'),
  refreshQrBtn: document.getElementById('refreshQrBtn'),
  passwordForm: document.getElementById('passwordForm'),
  passwordInput: document.getElementById('passwordInput'),
  passwordHint: document.getElementById('passwordHint'),
  logStatus: document.getElementById('logStatus'),
  logFileName: document.getElementById('logFileName'),
  logCountValue: document.getElementById('logCountValue'),
  lastLogAtValue: document.getElementById('lastLogAtValue'),
  logStream: document.getElementById('logStream'),
  summarySyncInterval: document.getElementById('summarySyncInterval'),
  summaryConfirmCycles: document.getElementById('summaryConfirmCycles'),
  summaryMaxScan: document.getElementById('summaryMaxScan'),
  summaryStartedAt: document.getElementById('summaryStartedAt'),
  feedbackBlock: document.getElementById('feedbackBlock'),
};

let stream;

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatDateTime(value) {
  if (!value) {
    return '--';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString('zh-CN', { hour12: false });
}

function setBadgeTheme(element, tone) {
  element.classList.remove('is-success', 'is-warn', 'is-danger');
  if (tone) {
    element.classList.add(tone);
  }
}

function setStreamStatus(text, mode) {
  dom.logStatus.textContent = text;
  dom.logStatus.classList.remove('is-online', 'is-warn', 'is-error');
  if (mode) {
    dom.logStatus.classList.add(mode);
  }
}

function phaseTone(phase) {
  if (phase === 'running' || phase === 'authorized') {
    return 'is-success';
  }
  if (phase === 'awaiting_qr' || phase === 'awaiting_password' || phase === 'reconnecting') {
    return 'is-warn';
  }
  if (phase === 'error' || phase === 'stopped') {
    return 'is-danger';
  }
  return '';
}

function animateNavButton(targetButton) {
  if (!targetButton) {
    return;
  }
  if (state.navAnimationTimer) {
    window.clearTimeout(state.navAnimationTimer);
  }
  dom.navButtons.forEach((button) => {
    button.classList.remove('is-activating');
  });
  targetButton.classList.add('is-activating');
  state.navAnimationTimer = window.setTimeout(() => {
    targetButton.classList.remove('is-activating');
  }, 520);
}

function cleanupViews() {
  dom.views.forEach((view) => {
    if (view.id !== state.activeView) {
      view.classList.remove('active', 'entering', 'leaving', 'is-exiting');
      view.setAttribute('aria-hidden', 'true');
    }
  });
}

function setActiveView(viewId, options = {}) {
  const { immediate = false, animateButton = false } = options;
  const nextView = dom.views.find((view) => view.id === viewId);
  if (!nextView) {
    return;
  }

  const currentView = dom.views.find((view) => view.id === state.activeView && view.classList.contains('active'));
  state.activeView = viewId;

  dom.navButtons.forEach((button) => {
    const active = button.dataset.view === viewId;
    button.classList.toggle('active', active);
    button.setAttribute('aria-current', active ? 'true' : 'false');
    if (active && animateButton) {
      animateNavButton(button);
    }
  });

  if (state.viewTransitionTimer) {
    window.clearTimeout(state.viewTransitionTimer);
    state.viewTransitionTimer = null;
  }

  if (immediate || !currentView || currentView === nextView) {
    dom.viewStage?.style.removeProperty('height');
    dom.views.forEach((view) => {
      const active = view.id === viewId;
      view.classList.toggle('active', active);
      view.classList.remove('entering', 'leaving', 'is-exiting');
      view.setAttribute('aria-hidden', active ? 'false' : 'true');
    });
    return;
  }

  const currentHeight = currentView.offsetHeight;
  nextView.classList.remove('leaving', 'is-exiting');
  nextView.classList.add('entering');
  nextView.setAttribute('aria-hidden', 'false');
  const nextHeight = nextView.offsetHeight;

  currentView.classList.add('leaving');
  currentView.setAttribute('aria-hidden', 'true');
  if (dom.viewStage) {
    dom.viewStage.style.height = `${currentHeight}px`;
  }

  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      currentView.classList.remove('active');
      currentView.classList.add('is-exiting');
      nextView.classList.add('active');
      if (dom.viewStage) {
        dom.viewStage.style.height = `${nextHeight}px`;
      }
    });
  });

  state.viewTransitionTimer = window.setTimeout(() => {
    nextView.classList.remove('entering');
    currentView.classList.remove('leaving', 'is-exiting');
    cleanupViews();
    if (dom.viewStage) {
      dom.viewStage.style.removeProperty('height');
    }
    state.viewTransitionTimer = null;
  }, 460);
}

function bindNavigation() {
  dom.navButtons.forEach((button) => {
    button.addEventListener('click', () => {
      setActiveView(button.dataset.view, { animateButton: true });
    });
  });
}


function updateLoginPanel(snapshot) {
  const phase = snapshot.phase || 'starting';
  const tone = phaseTone(phase);
  setBadgeTheme(dom.loginBadge, tone);
  dom.loginBadge.textContent = snapshot.phase_label || '状态未知';

  const channelValue = snapshot.channel_id ?? '--';
  const sessionFileValue = snapshot.session_file || '--';
  const qrExpire = formatDateTime(snapshot.qr_expires_at);
  const updatedAt = formatDateTime(snapshot.updated_at);

  dom.channelValue.textContent = channelValue;
  dom.sessionFileValue.textContent = sessionFileValue;
  dom.qrExpireValue.textContent = qrExpire;
  dom.updatedAtValue.textContent = updatedAt;
  dom.detailChannelValue.textContent = channelValue;
  dom.detailSessionFileValue.textContent = sessionFileValue;
  dom.detailQrExpireValue.textContent = qrExpire;
  dom.detailUpdatedAtValue.textContent = updatedAt;

  dom.refreshQrBtn.disabled = phase !== 'awaiting_qr';
  dom.refreshQrBtn.textContent = phase === 'awaiting_qr' ? '刷新二维码' : '二维码未就绪';
  dom.passwordForm.classList.toggle('hidden', phase !== 'awaiting_password');
  dom.passwordHint.textContent = snapshot.last_error || '仅在账号开启 Telegram 两步验证时需要输入。';

  if (phase === 'awaiting_qr' && snapshot.qr_image) {
    dom.qrShell.classList.add('has-image');
    dom.qrImage.src = snapshot.qr_image;
    dom.qrPlaceholder.textContent = '等待扫码';
    dom.loginTitle.textContent = '请使用手机 Telegram 扫码';
    dom.loginDescription.textContent = '二维码会自动刷新。管理员无需打开控制台，即可在此页面完成首次登录或重新登录。';
    return;
  }

  dom.qrShell.classList.remove('has-image');
  dom.qrImage.removeAttribute('src');

  if (phase === 'awaiting_password') {
    dom.qrPlaceholder.textContent = '等待输入两步验证密码';
    dom.loginTitle.textContent = '账号已开启 Telegram 两步验证';
    dom.loginDescription.textContent = '请输入账号密码继续完成登录。密码仅用于当前登录校验，不会展示在日志中。';
    return;
  }

  if (phase === 'running' || phase === 'authorized' || phase === 'initializing') {
    dom.qrPlaceholder.textContent = '当前会话已可用';
    dom.loginTitle.textContent = '当前 Telegram 会话已连接';
    dom.loginDescription.textContent = '服务会持续监听频道并同步 TelDrive。若会话失效，页面会自动重新进入扫码登录状态。';
    return;
  }

  if (phase === 'reconnecting') {
    dom.qrPlaceholder.textContent = '等待重连 Telegram';
    dom.loginTitle.textContent = '连接中断，系统正在尝试自动重连';
    dom.loginDescription.textContent = '重连完成后会自动恢复监听。若会话失效，将自动重新生成登录二维码。';
    return;
  }

  if (phase === 'error' || phase === 'stopped') {
    dom.qrPlaceholder.textContent = '服务状态异常';
    dom.loginTitle.textContent = '请检查运行日志';
    dom.loginDescription.textContent = snapshot.last_error || '服务已停止或发生异常，请根据日志定位问题。';
    return;
  }

  dom.qrPlaceholder.textContent = '等待生成登录二维码';
  dom.loginTitle.textContent = '服务初始化中';
  dom.loginDescription.textContent = '正在准备后台服务与 Telegram 连接。';
}

function updateSummary(snapshot) {
  const phaseLabel = snapshot.phase_label || '服务启动中';
  const updatedAt = formatDateTime(snapshot.updated_at);
  const lastLogAt = formatDateTime(snapshot.last_log_at);
  const syncValue = snapshot.sync_enabled
    ? `${snapshot.sync_interval} 秒 / 已开启`
    : '已关闭';

  dom.phaseLabel.textContent = phaseLabel;
  dom.phaseMeta.textContent = snapshot.last_error || `最近更新时间：${updatedAt}`;
  dom.metricPhaseValue.textContent = phaseLabel;
  dom.metricPhaseMeta.textContent = `最近更新时间：${updatedAt}`;
  dom.metricSessionValue.textContent = snapshot.authorized ? '已授权' : '未授权';
  dom.metricSessionMeta.textContent = snapshot.needs_password
    ? '等待管理员输入两步验证密码'
    : (snapshot.authorized ? '当前可直接执行业务同步' : '首次登录或会话失效时会显示二维码');
  dom.metricSyncValue.textContent = snapshot.sync_enabled
    ? `${snapshot.sync_interval} 秒轮询`
    : '删除同步已关闭';
  dom.metricSyncMeta.textContent = snapshot.sync_enabled
    ? `确认周期 ${snapshot.confirm_cycles} 次`
    : '仅保留消息监听，不执行删除同步';
  dom.metricLogValue.textContent = `${snapshot.log_count || 0} 条`;
  dom.metricLogMeta.textContent = snapshot.last_log_at
    ? `最近日志：${lastLogAt}`
    : '等待首条系统日志';

  dom.logFileName.textContent = snapshot.log_file || 'runtime.log';
  dom.logCountValue.textContent = snapshot.log_count || 0;
  dom.lastLogAtValue.textContent = lastLogAt;
  dom.summarySyncInterval.textContent = syncValue;
  dom.summaryConfirmCycles.textContent = `${snapshot.confirm_cycles ?? '--'} 次`;
  dom.summaryMaxScan.textContent = `${snapshot.max_scan_messages ?? '--'} 条`;
  dom.summaryStartedAt.textContent = formatDateTime(snapshot.service_started_at);
  dom.feedbackBlock.textContent = snapshot.last_error || '当前暂无异常，系统会在此展示二维码刷新、密码校验、连接恢复等关键提示。';

  dom.detailSyncValue.textContent = syncValue;
  dom.detailLastLogValue.textContent = lastLogAt;
  dom.detailLogFileValue.textContent = snapshot.log_file || 'runtime.log';
  dom.detailStartedAtValue.textContent = formatDateTime(snapshot.service_started_at);

  setBadgeTheme(dom.loginBadge, phaseTone(snapshot.phase));
}

function renderLogs() {
  if (!state.logs.length) {
    dom.logStream.innerHTML = '<div class="log-empty">等待系统写入第一条活动日志...</div>';
    return;
  }

  const shouldStick = dom.logStream.scrollTop + dom.logStream.clientHeight >= dom.logStream.scrollHeight - 48;
  dom.logStream.innerHTML = state.logs
    .slice(-300)
    .map((entry) => `
      <article class="log-row" data-level="${escapeHtml(entry.level)}">
        <div class="log-meta">
          <span>${escapeHtml(entry.level)}</span>
          <time>${escapeHtml(formatDateTime(entry.timestamp))}</time>
        </div>
        <div class="log-message">${escapeHtml(entry.message)}</div>
      </article>
    `)
    .join('');

  if (shouldStick) {
    dom.logStream.scrollTop = dom.logStream.scrollHeight;
  }
}

function renderSnapshot() {
  if (!state.snapshot) {
    return;
  }
  updateSummary(state.snapshot);
  updateLoginPanel(state.snapshot);
}

function applyEvent(payload) {
  if (!payload || !payload.type) {
    return;
  }

  if (payload.type === 'state') {
    state.snapshot = payload.payload;
    renderSnapshot();
    return;
  }

  if (payload.type === 'log') {
    state.logs.push(payload.payload);
    if (state.logs.length > 800) {
      state.logs = state.logs.slice(-800);
    }
    if (state.snapshot) {
      state.snapshot.log_count = (state.snapshot.log_count || 0) + 1;
      state.snapshot.last_log_at = payload.payload.timestamp;
      renderSnapshot();
    }
    renderLogs();
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : null;
  if (!response.ok) {
    throw new Error(data?.detail || '请求失败');
  }
  return data;
}

async function loadBootstrap() {
  const data = await requestJson('/api/bootstrap');
  state.snapshot = data.state;
  state.logs = data.logs || [];
  renderSnapshot();
  renderLogs();
}

function connectStream() {
  if (stream) {
    stream.close();
  }
  stream = new EventSource('/api/stream');
  setStreamStatus('实时流连接中', 'is-warn');

  stream.onopen = () => {
    setStreamStatus('实时流已连接', 'is-online');
  };

  stream.onmessage = (event) => {
    try {
      applyEvent(JSON.parse(event.data));
    } catch (error) {
      console.error(error);
    }
  };

  stream.onerror = () => {
    setStreamStatus('实时流重连中', 'is-error');
  };
}

dom.refreshQrBtn.addEventListener('click', async () => {
  if (dom.refreshQrBtn.disabled) {
    return;
  }

  dom.refreshQrBtn.disabled = true;
  dom.refreshQrBtn.textContent = '刷新中...';
  dom.feedbackBlock.textContent = '正在请求生成新的登录二维码...';
  try {
    await requestJson('/api/login/refresh', { method: 'POST', body: '{}' });
    dom.feedbackBlock.textContent = '二维码刷新请求已提交，新的二维码生成后会自动显示。';
  } catch (error) {
    dom.feedbackBlock.textContent = error.message;
  } finally {
    updateLoginPanel(state.snapshot || {});
  }
});

dom.passwordForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const password = dom.passwordInput.value;
  if (!password.trim()) {
    dom.passwordHint.textContent = '请输入两步验证密码。';
    return;
  }

  const submitButton = dom.passwordForm.querySelector('button[type="submit"]');
  const defaultText = submitButton.textContent;
  submitButton.disabled = true;
  submitButton.textContent = '提交中...';
  dom.passwordHint.textContent = '正在提交密码，请稍候...';
  dom.feedbackBlock.textContent = '正在校验两步验证密码...';
  try {
    await requestJson('/api/login/password', {
      method: 'POST',
      body: JSON.stringify({ password }),
    });
    dom.passwordInput.value = '';
    dom.passwordHint.textContent = '密码已提交，等待 Telegram 完成校验。';
    dom.feedbackBlock.textContent = '密码已提交，系统正在等待 Telegram 返回登录结果。';
  } catch (error) {
    dom.passwordHint.textContent = error.message;
    dom.feedbackBlock.textContent = error.message;
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = defaultText;
  }
});

(async () => {
  bindNavigation();
  setActiveView(state.activeView, { immediate: true });

  try {
    await loadBootstrap();
  } catch (error) {
    dom.feedbackBlock.textContent = error.message;
  }
  connectStream();
})();

