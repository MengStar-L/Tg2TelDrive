const state = {
  snapshot: null,
  logs: [],
  config: null,
  authRequired: false,
  authenticated: false,
  bootstrapLoaded: false,
  activeView: 'loginView',
  viewTransitionTimer: null,
  navAnimationTimer: null,
  configSectionTimers: new WeakMap(),
};


const CONFIG_SECTION_STORAGE_KEY = 'tel2teldrive-config-sections';
const CONFIG_SECTION_ANIMATION_DURATION = 340;

const CONFIG_SECTION_BODY_PADDING_BOTTOM = '20px';
const reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');



const dom = {
  appShell: document.getElementById('appShell'),
  accessLock: document.getElementById('accessLock'),
  accessLockForm: document.getElementById('accessLockForm'),
  accessLockInput: document.getElementById('accessLockInput'),
  accessLockHint: document.getElementById('accessLockHint'),
  accessLockBadge: document.getElementById('accessLockBadge'),
  accessLockDescription: document.getElementById('accessLockDescription'),
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
  configForm: document.getElementById('configForm'),
  configFields: Array.from(document.querySelectorAll('[data-config-path]')),
  configSections: Array.from(document.querySelectorAll('[data-config-section]')),
  configStatus: document.getElementById('configStatus'),

  configHint: document.getElementById('configHint'),
  configSaveNote: document.getElementById('configSaveNote'),
  saveConfigBtn: document.getElementById('saveConfigBtn'),
  reloadConfigBtn: document.getElementById('reloadConfigBtn'),
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

function getNestedValue(target, path) {
  return path.split('.').reduce((current, key) => (current == null ? undefined : current[key]), target);
}

function setNestedValue(target, path, value) {
  const keys = path.split('.');
  const lastKey = keys.pop();
  let current = target;
  keys.forEach((key) => {
    if (!current[key] || typeof current[key] !== 'object') {
      current[key] = {};
    }
    current = current[key];
  });
  current[lastKey] = value;
}

function setBadgeTheme(element, tone) {
  element.classList.remove('is-success', 'is-warn', 'is-danger');
  if (tone) {
    element.classList.add(tone);
  }
}

function setStatusChip(element, mode) {
  element.classList.remove('is-online', 'is-warn', 'is-error');
  if (mode) {
    element.classList.add(mode);
  }
}

function setStreamStatus(text, mode) {
  dom.logStatus.textContent = text;
  setStatusChip(dom.logStatus, mode);
}

function toggleAccessLock(visible) {
  dom.accessLock?.classList.toggle('hidden', !visible);
  dom.appShell?.classList.toggle('is-locked', visible);
  if (visible) {
    setStreamStatus('等待页面解锁', 'is-warn');
  }
}

function applyAuthStatus(payload) {
  state.authRequired = Boolean(payload?.auth_required);
  state.authenticated = !state.authRequired || Boolean(payload?.authenticated);
  toggleAccessLock(state.authRequired && !state.authenticated);

  if (state.authRequired) {
    dom.accessLockBadge.textContent = state.authenticated ? '已解锁' : '访问受保护';
    setBadgeTheme(dom.accessLockBadge, state.authenticated ? 'is-success' : 'is-warn');
    dom.accessLockDescription.textContent = state.authenticated
      ? '页面已解锁，当前可正常查看控制台信息。'
      : '该页面已开启密码锁，解锁后才可查看运行状态、日志和配置。';
  }
}

async function loadAuthStatus() {
  const payload = await requestJson('/api/auth/status');
  applyAuthStatus(payload);
  if (state.authRequired && !state.authenticated) {
    dom.accessLockInput.value = '';
    dom.accessLockHint.textContent = '请输入配置文件中的前端访问密码。';
    window.setTimeout(() => dom.accessLockInput.focus(), 0);
  }
  return state.authenticated;
}

async function initializeDashboard(options = {}) {
  const { force = false } = options;
  const authenticated = await loadAuthStatus();
  if (!authenticated) {
    return false;
  }

  if (force || !state.bootstrapLoaded) {
    await loadBootstrap();
    state.bootstrapLoaded = true;
  }
  connectStream();
  return true;
}

function phaseTone(phase) {

  if (phase === 'running' || phase === 'authorized') {
    return 'is-success';
  }
  if (phase === 'awaiting_qr' || phase === 'awaiting_password' || phase === 'reconnecting' || phase === 'awaiting_config') {
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

function readConfigSectionState() {
  try {
    return JSON.parse(window.localStorage.getItem(CONFIG_SECTION_STORAGE_KEY) || '{}');
  } catch {
    return {};
  }
}

function writeConfigSectionState(value) {
  try {
    window.localStorage.setItem(CONFIG_SECTION_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Ignore storage errors.
  }
}

function persistConfigSectionState(section, expanded) {
  const sectionKey = section.dataset.configSection;
  if (!sectionKey) {
    return;
  }
  const nextState = readConfigSectionState();
  nextState[sectionKey] = expanded;
  writeConfigSectionState(nextState);
}

function clearConfigSectionTimer(section) {
  const activeTimer = state.configSectionTimers.get(section);
  if (activeTimer) {
    window.clearTimeout(activeTimer);
    state.configSectionTimers.delete(section);
  }
}

function setConfigSectionExpanded(section, expanded, options = {}) {
  const { immediate = false, persist = true } = options;
  const body = section.querySelector('.config-section-body');
  const toggle = section.querySelector('.config-section-toggle');
  const collapsedPaddingBottom = '0px';
  const expandedPaddingBottom = CONFIG_SECTION_BODY_PADDING_BOTTOM;

  clearConfigSectionTimer(section);
  section.dataset.expanded = expanded ? 'true' : 'false';
  if (toggle) {
    toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }

  if (!body) {
    section.open = expanded;
    if (persist) {
      persistConfigSectionState(section, expanded);
    }
    return;
  }

  if (immediate || reducedMotionQuery.matches) {
    section.classList.remove('is-expanding', 'is-collapsing');
    section.open = expanded;
    body.style.overflow = 'hidden';
    body.style.height = expanded ? 'auto' : '0px';
    body.style.opacity = expanded ? '1' : '0';
    body.style.paddingBottom = expanded ? expandedPaddingBottom : collapsedPaddingBottom;
    if (persist) {
      persistConfigSectionState(section, expanded);
    }
    return;
  }

  section.classList.toggle('is-expanding', expanded);
  section.classList.toggle('is-collapsing', !expanded);
  section.open = true;
  body.style.overflow = 'hidden';

  if (expanded) {
    body.style.paddingBottom = expandedPaddingBottom;
    body.style.height = collapsedPaddingBottom;
    body.style.opacity = '0';
    const endHeight = body.scrollHeight;
    body.offsetHeight;

    window.requestAnimationFrame(() => {
      body.style.height = `${endHeight}px`;
      body.style.opacity = '1';
    });
  } else {
    const startHeight = body.getBoundingClientRect().height;
    body.style.height = `${startHeight}px`;
    body.style.opacity = '1';
    body.style.paddingBottom = collapsedPaddingBottom;
    body.offsetHeight;

    window.requestAnimationFrame(() => {
      body.style.height = collapsedPaddingBottom;
      body.style.opacity = '0';
    });
  }

  const timer = window.setTimeout(() => {
    section.classList.remove('is-expanding', 'is-collapsing');
    section.open = expanded;
    body.style.height = expanded ? 'auto' : collapsedPaddingBottom;
    body.style.opacity = expanded ? '1' : '0';
    body.style.paddingBottom = expanded ? expandedPaddingBottom : collapsedPaddingBottom;
    state.configSectionTimers.delete(section);
    if (persist) {
      persistConfigSectionState(section, expanded);
    }
  }, CONFIG_SECTION_ANIMATION_DURATION);

  state.configSectionTimers.set(section, timer);
}




function syncConfigSections(config) {
  const storedState = readConfigSectionState();
  const meta = config?.meta || {};
  const missingFields = new Set(Array.isArray(meta.missing_fields) ? meta.missing_fields : []);
  const forceOpenAll = Boolean(meta.config_error);

  dom.configSections.forEach((section) => {
    const sectionKey = section.dataset.configSection;
    const requiredLabels = (section.dataset.requiredLabels || '')
      .split('|')
      .map((label) => label.trim())
      .filter(Boolean);
    const shouldForceOpen = forceOpenAll || requiredLabels.some((label) => missingFields.has(label));
    const defaultOpen = section.hasAttribute('open');
    const storedOpen = storedState[sectionKey];
    const nextOpen = shouldForceOpen || (typeof storedOpen === 'boolean' ? storedOpen : defaultOpen);
    setConfigSectionExpanded(section, nextOpen, { immediate: true, persist: false });
  });
}

function bindConfigSections() {
  dom.configSections.forEach((section) => {
    const toggle = section.querySelector('.config-section-toggle');
    setConfigSectionExpanded(section, section.open, { immediate: true, persist: false });
    if (!toggle) {
      return;
    }
    toggle.addEventListener('click', (event) => {
      event.preventDefault();
      const expanded = section.dataset.expanded !== 'false';
      setConfigSectionExpanded(section, !expanded);
    });
  });
}


function populateConfigForm(config) {

  if (!config) {
    return;
  }
  dom.configFields.forEach((field) => {
    const path = field.dataset.configPath;
    const value = getNestedValue(config, path);
    if (field.type === 'checkbox') {
      field.checked = Boolean(value);
      return;
    }
    field.value = value == null ? '' : value;
  });
}

function serializeConfigForm() {
  const payload = {};
  dom.configFields.forEach((field) => {
    const path = field.dataset.configPath;
    const value = field.type === 'checkbox' ? field.checked : field.value.trim();
    setNestedValue(payload, path, value);
  });
  return payload;
}

function updateConfigPanel(snapshot, config) {
  if (!config) {
    return;
  }

  const meta = config.meta || {};
  const missingFields = Array.isArray(meta.missing_fields) ? meta.missing_fields : [];
  const parseError = meta.config_error;
  const ready = Boolean(meta.config_ready);

  if (parseError) {
    dom.configStatus.textContent = '配置异常';
    setStatusChip(dom.configStatus, 'is-error');
    dom.configHint.textContent = `${parseError} 请重新检查并保存配置。`;
  } else if (ready) {
    dom.configStatus.textContent = '配置已就绪';
    setStatusChip(dom.configStatus, 'is-online');
    dom.configHint.textContent = '配置已保存。修改后会自动重载 Telegram / TelDrive 服务参数。';
  } else {
    dom.configStatus.textContent = '待完善';
    setStatusChip(dom.configStatus, 'is-warn');
    dom.configHint.textContent = missingFields.length
      ? `当前仍缺少：${missingFields.join('、')}。补全后保存即可自动开始连接。`
      : '当前尚未完成配置，请填写后保存。';
  }

  if (snapshot?.config_ready === false && state.activeView === 'loginView') {
    setActiveView('configView', { immediate: true });
  }
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

  if (phase === 'awaiting_config') {
    dom.qrShell.classList.remove('has-image');
    dom.qrImage.removeAttribute('src');
    dom.qrPlaceholder.textContent = '等待完成网页配置';
    dom.loginTitle.textContent = '请先在配置中心填写参数';
    dom.loginDescription.textContent = snapshot.last_error || '当前尚未完成 Telegram 与 TelDrive 配置。请前往“参数配置”页面填写后保存。';
    return;
  }


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
  const configReady = snapshot.config_ready !== false;
  const syncValue = snapshot.sync_enabled
    ? `${snapshot.sync_interval} 秒 / 已开启`
    : '已关闭';

  dom.phaseLabel.textContent = phaseLabel;
  dom.phaseMeta.textContent = snapshot.last_error || `最近更新时间：${updatedAt}`;
  dom.metricPhaseValue.textContent = phaseLabel;
  dom.metricPhaseMeta.textContent = `最近更新时间：${updatedAt}`;
  dom.metricSessionValue.textContent = snapshot.authorized ? '已授权' : '未授权';
  dom.metricSessionMeta.textContent = !configReady
    ? '请先在网页端完成配置并保存'
    : (snapshot.needs_password
      ? '等待管理员输入两步验证密码'
      : (snapshot.authorized ? '当前可直接执行业务同步' : '首次登录或会话失效时会显示二维码'));
  dom.metricSyncValue.textContent = configReady
    ? (snapshot.sync_enabled ? `${snapshot.sync_interval} 秒轮询` : '删除同步已关闭')
    : '等待配置完成';
  dom.metricSyncMeta.textContent = configReady
    ? (snapshot.sync_enabled ? `确认周期 ${snapshot.confirm_cycles} 次` : '仅保留消息监听，不执行删除同步')
    : '请先填写 Telegram 与 TelDrive 参数';
  dom.metricLogValue.textContent = `${snapshot.log_count || 0} 条`;
  dom.metricLogMeta.textContent = snapshot.last_log_at
    ? `最近日志：${lastLogAt}`
    : '等待首条系统日志';

  dom.logFileName.textContent = snapshot.log_file || 'runtime.log';
  dom.logCountValue.textContent = snapshot.log_count || 0;
  dom.lastLogAtValue.textContent = lastLogAt;
  dom.summarySyncInterval.textContent = configReady ? syncValue : '等待配置';
  dom.summaryConfirmCycles.textContent = `${snapshot.confirm_cycles ?? '--'} 次`;
  dom.summaryMaxScan.textContent = `${snapshot.max_scan_messages ?? '--'} 条`;
  dom.summaryStartedAt.textContent = formatDateTime(snapshot.service_started_at);
  dom.feedbackBlock.textContent = snapshot.last_error || '当前暂无异常，系统会在此展示二维码刷新、密码校验、连接恢复等关键提示。';

  dom.detailSyncValue.textContent = configReady ? syncValue : '等待配置';
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
  updateConfigPanel(state.snapshot, state.config);
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
    if (response.status === 401) {
      applyAuthStatus({ auth_required: true, authenticated: false });
      if (stream) {
        stream.close();
      }
    }
    throw new Error(data?.detail || '请求失败');
  }
  return data;
}


async function loadBootstrap() {
  const data = await requestJson('/api/bootstrap');
  state.snapshot = data.state;
  state.logs = data.logs || [];
  state.config = data.config || null;
  if (state.config) {
    populateConfigForm(state.config);
    syncConfigSections(state.config);
  }
  renderSnapshot();
  renderLogs();
}


async function reloadConfigFromServer() {
  const data = await requestJson('/api/config');
  state.config = data;
  populateConfigForm(data);
  syncConfigSections(state.config);
  updateConfigPanel(state.snapshot, state.config);
}


function connectStream() {
  if (state.authRequired && !state.authenticated) {
    return;
  }
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

dom.accessLockForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const password = dom.accessLockInput.value.trim();
  if (!password) {
    dom.accessLockHint.textContent = '请输入前端访问密码。';
    return;
  }

  const submitButton = dom.accessLockForm.querySelector('button[type="submit"]');
  const defaultText = submitButton.textContent;
  submitButton.disabled = true;
  submitButton.textContent = '解锁中...';
  dom.accessLockHint.textContent = '正在校验前端访问密码，请稍候...';
  try {
    await requestJson('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    });
    dom.accessLockInput.value = '';
    dom.accessLockHint.textContent = '密码校验通过，正在载入控制台...';
    await initializeDashboard({ force: true });
    dom.feedbackBlock.textContent = '页面已解锁，控制台数据已恢复加载。';
  } catch (error) {
    dom.accessLockHint.textContent = error.message;
    dom.feedbackBlock.textContent = error.message;
    window.setTimeout(() => dom.accessLockInput.focus(), 0);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = defaultText;
  }
});

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

dom.configForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const defaultText = dom.saveConfigBtn.textContent;
  dom.saveConfigBtn.disabled = true;
  dom.saveConfigBtn.textContent = '保存中...';
  dom.configSaveNote.textContent = '正在保存配置并通知服务重载，请稍候...';
  try {
    const response = await requestJson('/api/config', {
      method: 'POST',
      body: JSON.stringify(serializeConfigForm()),
    });
    state.config = response.config || state.config;
    if (state.config) {
      populateConfigForm(state.config);
      syncConfigSections(state.config);
    }
    if (response.state) {
      state.snapshot = response.state;
    }

    renderSnapshot();
    dom.feedbackBlock.textContent = response.requires_process_restart
      ? '配置已保存。Telegram / TelDrive 参数已重载；若修改了 Web 地址、前端监测端口或日志缓存条数，请重启进程后完全生效。'
      : '配置已保存并已通知后台自动重载。';
    dom.configSaveNote.textContent = response.requires_process_restart
      ? '配置已保存。当前运行进程的 Web 监听地址 / 前端监测端口不会立刻变化，请在合适时机重启进程。'
      : '配置已保存。Telegram / TelDrive 服务会自动使用新参数重载。';

  } catch (error) {
    dom.configSaveNote.textContent = error.message;
    dom.feedbackBlock.textContent = error.message;
  } finally {
    dom.saveConfigBtn.disabled = false;
    dom.saveConfigBtn.textContent = defaultText;
  }
});

dom.reloadConfigBtn.addEventListener('click', async () => {
  const defaultText = dom.reloadConfigBtn.textContent;
  dom.reloadConfigBtn.disabled = true;
  dom.reloadConfigBtn.textContent = '读取中...';
  try {
    await reloadConfigFromServer();
    dom.configSaveNote.textContent = '已重新读取当前配置文件内容。';
    dom.feedbackBlock.textContent = '配置表单已刷新为磁盘中的最新内容。';
  } catch (error) {
    dom.configSaveNote.textContent = error.message;
    dom.feedbackBlock.textContent = error.message;
  } finally {
    dom.reloadConfigBtn.disabled = false;
    dom.reloadConfigBtn.textContent = defaultText;
  }
});

(async () => {
  bindNavigation();
  bindConfigSections();
  setActiveView(state.activeView, { immediate: true });

  try {
    const ready = await initializeDashboard();
    if (!ready) {
      dom.feedbackBlock.textContent = '页面已加锁，请先输入前端访问密码。';
    }
  } catch (error) {
    dom.feedbackBlock.textContent = error.message;
  }
})();

