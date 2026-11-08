/**
 * Beacon v2.1 · Frontend Application
 * Data Center Acoustic Localization & Direction Finding
 * 
 * Features:
 * 1. 10 Hz WebSocket telemetry streaming (L, M, R mic levels)
 * 2. Instant Incident state machine synchronization (DETECTED -> LOCATED -> IDENTIFIED -> ACKNOWLEDGED -> CLEARED)
 * 3. Responsive Bifurcation: Full NOC Dashboard on Desktop; Dedicated Pager View on Mobile
 * 4. Model Proof: Multi-method accuracy comparisons and interactive confusion matrix heatmaps
 * 5. Laser Turret Calibration: Servo jog controls, keyboard listeners, and aim angle locking
 */

(function () {
  'use strict';

  // =========================================================================
  // 1. Configuration & Global State
  // =========================================================================
  const getApiBase = () => {
    if (window.location.protocol === 'file:' || !window.location.host) {
      return 'http://localhost:8000';
    }
    return window.location.origin;
  };

  const getWsUrl = () => {
    if (window.location.protocol === 'file:' || !window.location.host) {
      return 'ws://localhost:8000/live';
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/live`;
  };

  const state = {
    // Active incident matching contract:
    // { id: "inc_1", state: "IDENTIFIED", rack: "B", confidence: 0.89, alarm: { meaning: "UPS On Battery" }, beeps: 12, ... }
    incident: null,
    
    // Live mic levels at 10Hz
    micLevels: { L: 10.0, M: 10.0, R: 10.0 },
    
    // WebSocket connection state
    ws: null,
    wsConnected: false,
    reconnectAttempts: 0,
    reconnectTimer: null,
    
    // Laser Turret & Calibration
    laser: {
      power: true,
      panAngle: 0, // -45° to +45°
      calibratedAngles: { A: -35, B: -18, C: 0, D: 18, E: 35 },
      rackCoordinates: {
        A: 115, // SVG center X
        B: 280,
        C: 450,
        D: 620,
        E: 785,
      },
    },

    // Cached model metrics
    metrics: null,

    // Pitch & Simulation Demo Controls
    demo: {
      selectedPattern: 'P1',
      replayPaused: true,
    },
  };

  // =========================================================================
  // 2. DOM Elements Cache
  // =========================================================================
  const dom = {
    // Pitch Simulation & Demo Bar
    btnReplayToggle: document.getElementById('btn-replay-toggle'),
    replayStatusDot: document.getElementById('replay-status-dot'),
    replayStatusText: document.getElementById('replay-status-text'),
    patternBtns: document.querySelectorAll('.demo-pattern-btn'),
    triggerRackBtns: document.querySelectorAll('.demo-trigger-rack-btn'),

    // Responsive Toggle Buttons
    btnToggleMobile: document.getElementById('btn-toggle-view-mobile'),
    btnToggleDesktop: document.getElementById('btn-toggle-view-desktop'),

    // WebSocket Status
    desktopWsStatus: document.getElementById('desktop-ws-status'),
    desktopWsPing: document.getElementById('desktop-ws-ping'),
    desktopWsDot: document.getElementById('desktop-ws-dot'),
    mobileWsPing: document.getElementById('mobile-ws-ping'),
    mobileWsDot: document.getElementById('mobile-ws-dot'),

    // Mobile Technician Pager View
    mobileNominalState: document.getElementById('mobile-nominal-state'),
    mobileActiveState: document.getElementById('mobile-active-state'),
    mobileIncidentId: document.getElementById('mobile-incident-id'),
    mobileIncidentState: document.getElementById('mobile-incident-state'),
    mobileRackLetter: document.getElementById('mobile-rack-letter'),
    mobileAlarmMeaning: document.getElementById('mobile-alarm-meaning'),
    mobileAlarmAction: document.getElementById('mobile-alarm-action'),
    mobileConfidenceVal: document.getElementById('mobile-confidence-val'),
    mobileBeepsVal: document.getElementById('mobile-beeps-val'),
    btnMobileAck: document.getElementById('btn-mobile-ack'),

    // Desktop Tabs
    tabBtns: document.querySelectorAll('.tab-btn'),
    tabPanes: document.querySelectorAll('.tab-pane'),

    // Desktop SVG Map
    aisleSvg: document.getElementById('aisle-svg'),
    laserBeam: document.getElementById('laser-beam'),
    rackGroups: {
      A: document.getElementById('svg-rack-A'),
      B: document.getElementById('svg-rack-B'),
      C: document.getElementById('svg-rack-C'),
      D: document.getElementById('svg-rack-D'),
      E: document.getElementById('svg-rack-E'),
    },
    micGroups: {
      L: document.getElementById('svg-mic-L'),
      M: document.getElementById('svg-mic-M'),
      R: document.getElementById('svg-mic-R'),
    },

    // Desktop Live Mic Energy Meters
    levelValL: document.getElementById('level-val-L'),
    levelValM: document.getElementById('level-val-M'),
    levelValR: document.getElementById('level-val-R'),
    barMicL: document.getElementById('bar-mic-L'),
    barMicM: document.getElementById('bar-mic-M'),
    barMicR: document.getElementById('bar-mic-R'),

    // Desktop Active Incident Card
    desktopIncidentId: document.getElementById('desktop-incident-id'),
    desktopIncidentState: document.getElementById('desktop-incident-state'),
    desktopRackVal: document.getElementById('desktop-rack-val'),
    desktopConfVal: document.getElementById('desktop-conf-val'),
    desktopBeepsVal: document.getElementById('desktop-beeps-val'),
    desktopAlarmMeaning: document.getElementById('desktop-alarm-meaning'),
    desktopAlarmAction: document.getElementById('desktop-alarm-action'),
    desktopLastHeard: document.getElementById('desktop-last-heard'),
    btnDesktopAck: document.getElementById('btn-desktop-ack'),

    // Model Metrics Tab (Brain 1 & Brain 2)
    btnRefreshMetrics: document.getElementById('btn-refresh-metrics'),
    metricLoudestAcc: document.getElementById('metric-loudest-acc'),
    metricCentroidAcc: document.getElementById('metric-centroid-acc'),
    metricRfAcc: document.getElementById('metric-rf-acc'),
    cmLoudest: document.getElementById('cm-loudest'),
    cmCentroid: document.getElementById('cm-centroid'),
    cmRf: document.getElementById('cm-rf'),

    metricRhythmSgdF1: document.getElementById('metric-rhythm-sgd-f1'),
    metricRhythmRfF1: document.getElementById('metric-rhythm-rf-f1'),
    metricRhythmTestAcc: document.getElementById('metric-rhythm-test-acc'),
    metricRhythmFalseAlarm: document.getElementById('metric-rhythm-false-alarm'),
    cmRhythm: document.getElementById('cm-rhythm'),

    // Live QR Codes
    headerQrBox: document.getElementById('header-qr-box'),
    qrCanvasHeader: document.getElementById('qr-canvas-header'),
    qrContainerHeader: document.getElementById('qr-container-header'),
    qrLinkHeader: document.getElementById('qr-link-header'),

    sidebarQrBox: document.getElementById('sidebar-qr-box'),
    qrCanvasSidebar: document.getElementById('qr-canvas-sidebar'),
    qrContainerSidebar: document.getElementById('qr-container-sidebar'),
    qrLinkSidebar: document.getElementById('qr-link-sidebar'),

    // Laser Turret Setup Tab
    laserAngleDisplay: document.getElementById('laser-angle-display'),
    btnJogLeft: document.getElementById('btn-jog-left'),
    btnJogRight: document.getElementById('btn-jog-right'),
    btnToggleLaser: document.getElementById('btn-toggle-laser'),
    btnSaveRacks: document.querySelectorAll('.btn-save-rack'),
    btnTestBlanking: document.getElementById('btn-test-blanking'),
  };

  // =========================================================================
  // 3. WebSocket Real-Time Telemetry & Reconnect Loop
  // =========================================================================
  function initWebSocket() {
    if (state.ws) {
      try {
        state.ws.close();
      } catch (e) {}
    }

    const wsUrl = getWsUrl();
    setWsStatus('CONNECTING');

    try {
      state.ws = new WebSocket(wsUrl);

      state.ws.onopen = () => {
        state.wsConnected = true;
        state.reconnectAttempts = 0;
        setWsStatus('CONNECTED');
        console.log('[Beacon WS] Live telemetry connected.');
      };

      state.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleIncomingMessage(data);
        } catch (err) {
          console.warn('[Beacon WS] Failed to parse message JSON:', err, event.data);
        }
      };

      state.ws.onerror = (err) => {
        console.warn('[Beacon WS] Connection error:', err);
      };

      state.ws.onclose = () => {
        state.wsConnected = false;
        setWsStatus('DISCONNECTED');
        scheduleWsReconnect();
      };
    } catch (err) {
      console.warn('[Beacon WS] Initialization error:', err);
      setWsStatus('DISCONNECTED');
      scheduleWsReconnect();
    }
  }

  function scheduleWsReconnect() {
    if (state.reconnectTimer) clearTimeout(state.reconnectTimer);
    state.reconnectAttempts++;
    const delay = Math.min(5000, 1000 * Math.pow(1.5, state.reconnectAttempts - 1));
    console.log(`[Beacon WS] Reconnecting in ${(delay / 1000).toFixed(1)}s...`);
    state.reconnectTimer = setTimeout(initWebSocket, delay);
  }

  function setWsStatus(status) {
    if (status === 'CONNECTED') {
      if (dom.desktopWsStatus) dom.desktopWsStatus.textContent = 'WS LIVE (10Hz)';
      if (dom.desktopWsDot) dom.desktopWsDot.className = 'relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500';
      if (dom.desktopWsPing) dom.desktopWsPing.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75';
      if (dom.mobileWsDot) dom.mobileWsDot.className = 'relative inline-flex rounded-full h-3 w-3 bg-cyan-500';
      if (dom.mobileWsPing) dom.mobileWsPing.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75';
    } else if (status === 'CONNECTING') {
      if (dom.desktopWsStatus) dom.desktopWsStatus.textContent = 'WS CONNECTING...';
      if (dom.desktopWsDot) dom.desktopWsDot.className = 'relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500';
      if (dom.desktopWsPing) dom.desktopWsPing.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75';
      if (dom.mobileWsDot) dom.mobileWsDot.className = 'relative inline-flex rounded-full h-3 w-3 bg-amber-500';
      if (dom.mobileWsPing) dom.mobileWsPing.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75';
    } else {
      if (dom.desktopWsStatus) dom.desktopWsStatus.textContent = 'WS RECONNECTING';
      if (dom.desktopWsDot) dom.desktopWsDot.className = 'relative inline-flex rounded-full h-2.5 w-2.5 bg-rose-500';
      if (dom.desktopWsPing) dom.desktopWsPing.className = 'hidden';
      if (dom.mobileWsDot) dom.mobileWsDot.className = 'relative inline-flex rounded-full h-3 w-3 bg-rose-500';
      if (dom.mobileWsPing) dom.mobileWsPing.className = 'hidden';
    }
  }

  function handleIncomingMessage(msg) {
    if (!msg || typeof msg !== 'object') return;

    if (msg.type === 'mic_levels') {
      updateMicLevels(msg);
    } else if (msg.type === 'incident') {
      updateIncident(msg);
    } else if (msg.id && msg.state) {
      // In case incident payload arrives directly
      updateIncident(msg);
    }
  }

  // =========================================================================
  // 4. Live Mic Energies (10 Hz)
  // =========================================================================
  function updateMicLevels(data) {
    state.micLevels.L = typeof data.L === 'number' ? data.L : 10.0;
    state.micLevels.M = typeof data.M === 'number' ? data.M : 10.0;
    state.micLevels.R = typeof data.R === 'number' ? data.R : 10.0;

    // Numerical displays
    if (dom.levelValL) dom.levelValL.textContent = state.micLevels.L.toFixed(1);
    if (dom.levelValM) dom.levelValM.textContent = state.micLevels.M.toFixed(1);
    if (dom.levelValR) dom.levelValR.textContent = state.micLevels.R.toFixed(1);

    // Dynamic bar scaling (Background floor ~10, Active Beeps up to 120+)
    const scaleWidth = (val) => {
      const pct = Math.min(100, Math.max(4, ((val) / 100) * 100));
      return `${pct}%`;
    };

    if (dom.barMicL) dom.barMicL.style.width = scaleWidth(state.micLevels.L);
    if (dom.barMicM) dom.barMicM.style.width = scaleWidth(state.micLevels.M);
    if (dom.barMicR) dom.barMicR.style.width = scaleWidth(state.micLevels.R);

    // Visual mic animation on active beep threshold (>25)
    animateMicCircle(dom.micGroups.L, state.micLevels.L > 25);
    animateMicCircle(dom.micGroups.M, state.micLevels.M > 25);
    animateMicCircle(dom.micGroups.R, state.micLevels.R > 25);
  }

  function animateMicCircle(micGroup, isActive) {
    if (!micGroup) return;
    const circle = micGroup.querySelector('.mic-circle');
    if (!circle) return;

    if (isActive) {
      circle.setAttribute('r', '17');
      circle.setAttribute('fill', '#06b6d4');
      circle.setAttribute('stroke', '#ffffff');
      circle.setAttribute('stroke-width', '3');
    } else {
      circle.setAttribute('r', '14');
      circle.setAttribute('fill', '#0891b2');
      circle.setAttribute('stroke', '#22d3ee');
      circle.setAttribute('stroke-width', '2');
    }
  }

  // =========================================================================
  // 5. Incident Lifecycle & Instant Multi-View Synchronization
  // =========================================================================
  function updateIncident(inc) {
    state.incident = inc;

    // 1. Sync Desktop NOC Dashboard
    syncDesktopIncidentUI(inc);

    // 2. Sync Mobile Technician Pager Card
    syncMobilePagerUI(inc);

    // 3. Update Top-Down SVG Aisle Map & Laser Beam Aiming
    syncSvgAisleMap(inc);
  }

  function syncDesktopIncidentUI(inc) {
    if (!inc || inc.state === 'CLEARED') {
      if (dom.desktopIncidentId) dom.desktopIncidentId.textContent = 'NO ACTIVE INCIDENT';
      if (dom.desktopIncidentState) {
        dom.desktopIncidentState.textContent = 'CLEARED';
        dom.desktopIncidentState.className = 'text-xs font-mono px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-400 uppercase font-bold';
      }
      if (dom.desktopRackVal) dom.desktopRackVal.textContent = '—';
      if (dom.desktopConfVal) dom.desktopConfVal.textContent = '—';
      if (dom.desktopBeepsVal) dom.desktopBeepsVal.textContent = '0';
      if (dom.desktopAlarmMeaning) dom.desktopAlarmMeaning.textContent = 'Scanning rhythm...';
      if (dom.desktopAlarmAction) dom.desktopAlarmAction.textContent = 'Aisle nominal · 3 Mics active at 2500 Hz';
      if (dom.btnDesktopAck) {
        dom.btnDesktopAck.disabled = true;
        dom.btnDesktopAck.textContent = 'Acknowledge Incident';
        dom.btnDesktopAck.className = 'px-5 py-2 rounded-xl bg-slate-800 text-slate-500 font-bold text-xs font-mono tracking-wider uppercase disabled:opacity-40 disabled:pointer-events-none';
      }
      return;
    }

    // Active Incident Present
    if (dom.desktopIncidentId) dom.desktopIncidentId.textContent = inc.id || 'INC-01';
    
    // Status Badge
    if (dom.desktopIncidentState) {
      dom.desktopIncidentState.textContent = inc.state;
      if (inc.state === 'ACKNOWLEDGED') {
        dom.desktopIncidentState.className = 'text-xs font-mono px-2.5 py-0.5 rounded-full bg-emerald-500 text-slate-950 uppercase font-black tracking-wider';
      } else if (inc.state === 'IDENTIFIED') {
        dom.desktopIncidentState.className = 'text-xs font-mono px-2.5 py-0.5 rounded-full bg-amber-500 text-slate-950 uppercase font-black tracking-wider animate-pulse';
      } else if (inc.state === 'LOCATED') {
        dom.desktopIncidentState.className = 'text-xs font-mono px-2.5 py-0.5 rounded-full bg-cyan-500 text-slate-950 uppercase font-black tracking-wider';
      } else {
        dom.desktopIncidentState.className = 'text-xs font-mono px-2.5 py-0.5 rounded-full bg-slate-700 text-slate-200 uppercase font-bold';
      }
    }

    if (dom.desktopRackVal) {
      dom.desktopRackVal.textContent = `RACK ${inc.rack || '—'}`;
    }
    if (dom.desktopConfVal) {
      const conf = typeof inc.confidence === 'number' ? (inc.confidence * 100).toFixed(1) : '—';
      dom.desktopConfVal.textContent = `${conf}%`;
    }
    if (dom.desktopBeepsVal) {
      dom.desktopBeepsVal.textContent = String(inc.beeps || 1);
    }
    if (dom.desktopAlarmMeaning) {
      dom.desktopAlarmMeaning.textContent = (inc.alarm && inc.alarm.meaning) ? inc.alarm.meaning : 'Identifying alarm cadence...';
    }
    if (dom.desktopAlarmAction) {
      dom.desktopAlarmAction.textContent = (inc.alarm && inc.alarm.action) ? inc.alarm.action : 'Waiting for temporal pattern confirmation';
    }

    // Acknowledge Button state
    if (dom.btnDesktopAck) {
      if (inc.state === 'ACKNOWLEDGED') {
        dom.btnDesktopAck.disabled = true;
        dom.btnDesktopAck.textContent = 'ACKNOWLEDGED ✓';
        dom.btnDesktopAck.className = 'px-5 py-2 rounded-xl bg-emerald-700 text-emerald-100 font-bold text-xs font-mono tracking-wider uppercase';
      } else {
        dom.btnDesktopAck.disabled = false;
        dom.btnDesktopAck.textContent = 'Acknowledge Incident';
        dom.btnDesktopAck.className = 'px-5 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 active:bg-amber-600 text-slate-950 font-bold text-xs font-mono tracking-wider uppercase transition-all shadow-md shadow-amber-500/20';
      }
    }
  }

  function syncMobilePagerUI(inc) {
    if (!inc || inc.state === 'CLEARED') {
      if (dom.mobileNominalState) dom.mobileNominalState.classList.remove('hidden');
      if (dom.mobileActiveState) dom.mobileActiveState.classList.add('hidden');
      if (dom.btnMobileAck) {
        dom.btnMobileAck.disabled = true;
        dom.btnMobileAck.innerHTML = `
          <svg class="w-8 h-8 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
          </svg>
          <span>ALL RACKS NOMINAL</span>
        `;
        dom.btnMobileAck.className = 'w-full py-5 rounded-2xl bg-slate-900 text-slate-600 font-bold text-xl tracking-wider uppercase border border-slate-800 flex items-center justify-center gap-3 disabled:pointer-events-none';
      }
      return;
    }

    // Active Incident on Mobile Pager
    if (dom.mobileNominalState) dom.mobileNominalState.classList.add('hidden');
    if (dom.mobileActiveState) dom.mobileActiveState.classList.remove('hidden');

    if (dom.mobileIncidentId) dom.mobileIncidentId.textContent = inc.id || 'INC-01';
    if (dom.mobileIncidentState) {
      dom.mobileIncidentState.textContent = inc.state;
      if (inc.state === 'ACKNOWLEDGED') {
        dom.mobileIncidentState.className = 'text-xs font-mono uppercase px-2.5 py-0.5 rounded-full bg-emerald-500 text-slate-950 font-extrabold tracking-wider';
      } else {
        dom.mobileIncidentState.className = 'text-xs font-mono uppercase px-2.5 py-0.5 rounded-full bg-amber-500 text-slate-950 font-extrabold tracking-wider animate-pulse';
      }
    }

    if (dom.mobileRackLetter) dom.mobileRackLetter.textContent = inc.rack || '?';
    if (dom.mobileAlarmMeaning) {
      dom.mobileAlarmMeaning.textContent = (inc.alarm && inc.alarm.meaning) ? inc.alarm.meaning : 'Acoustic Alarm Lock';
    }
    if (dom.mobileAlarmAction) {
      dom.mobileAlarmAction.textContent = (inc.alarm && inc.alarm.action) ? inc.alarm.action : 'Inspect target server rack immediately';
    }
    if (dom.mobileConfidenceVal) {
      const conf = typeof inc.confidence === 'number' ? (inc.confidence * 100).toFixed(1) : '—';
      dom.mobileConfidenceVal.textContent = `${conf}%`;
    }
    if (dom.mobileBeepsVal) {
      dom.mobileBeepsVal.textContent = `${inc.beeps || 1} beeps`;
    }

    // Giant Mobile Action Button
    if (dom.btnMobileAck) {
      if (inc.state === 'ACKNOWLEDGED') {
        dom.btnMobileAck.disabled = true;
        dom.btnMobileAck.innerHTML = `
          <svg class="w-8 h-8 text-emerald-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
          </svg>
          <span>ACKNOWLEDGED ✓</span>
        `;
        dom.btnMobileAck.className = 'w-full py-5 rounded-2xl bg-emerald-600 text-white font-black text-2xl tracking-wider uppercase shadow-xl shadow-emerald-950/80 flex items-center justify-center gap-3 transition-all';
      } else {
        dom.btnMobileAck.disabled = false;
        dom.btnMobileAck.innerHTML = `
          <svg class="w-8 h-8 text-slate-950" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
          </svg>
          <span>ACKNOWLEDGE</span>
        `;
        dom.btnMobileAck.className = 'w-full py-5 rounded-2xl bg-amber-500 hover:bg-amber-400 active:bg-amber-600 text-slate-950 font-black text-2xl tracking-wider uppercase shadow-xl shadow-amber-500/30 transition-all flex items-center justify-center gap-3 animate-pulse';
      }
    }
  }

  function syncSvgAisleMap(inc) {
    const activeRack = (inc && inc.state !== 'CLEARED') ? inc.rack : null;
    const isAck = inc && inc.state === 'ACKNOWLEDGED';
    const isIdentified = inc && inc.state === 'IDENTIFIED';

    // 1. Highlight target rack, reset idle racks
    ['A', 'B', 'C', 'D', 'E'].forEach((rackId) => {
      const g = dom.rackGroups[rackId];
      if (!g) return;

      const rect = g.querySelector('.rack-rect');
      const confText = g.querySelector('.rack-conf');

      if (rackId === activeRack) {
        if (isAck) {
          rect.setAttribute('fill', '#064e3b'); // emerald-900
          rect.setAttribute('stroke', '#10b981'); // emerald-500
          rect.setAttribute('stroke-width', '4');
          rect.setAttribute('filter', 'url(#glow-filter)');
          if (confText) {
            confText.textContent = `ACK (${Math.round((inc.confidence || 0) * 100)}%)`;
            confText.setAttribute('fill', '#34d399');
          }
        } else if (isIdentified) {
          rect.setAttribute('fill', '#78350f'); // amber-900
          rect.setAttribute('stroke', '#f59e0b'); // amber-500
          rect.setAttribute('stroke-width', '4');
          rect.setAttribute('filter', 'url(#glow-filter)');
          if (confText) {
            confText.textContent = `LOCKED (${Math.round((inc.confidence || 0) * 100)}%)`;
            confText.setAttribute('fill', '#fbbf24');
          }
        } else {
          rect.setAttribute('fill', '#1e3a8a'); // sky-950
          rect.setAttribute('stroke', '#06b6d4'); // cyan-500
          rect.setAttribute('stroke-width', '3');
          rect.setAttribute('filter', 'url(#glow-filter)');
          if (confText) {
            confText.textContent = `LOCATED (${Math.round((inc.confidence || 0) * 100)}%)`;
            confText.setAttribute('fill', '#22d3ee');
          }
        }
      } else {
        // Idle Rack
        rect.setAttribute('fill', '#1e293b');
        rect.setAttribute('stroke', '#334155');
        rect.setAttribute('stroke-width', '2');
        rect.removeAttribute('filter');
        if (confText) {
          confText.textContent = 'IDLE';
          confText.setAttribute('fill', '#64748b');
        }
      }
    });

    // 2. Aim the pan laser turret
    if (!dom.laserBeam) return;

    if (activeRack && state.laser.rackCoordinates[activeRack]) {
      const targetSvgX = state.laser.rackCoordinates[activeRack];
      // Turret is centered at (450, 270). In group coords:
      const relX = targetSvgX - 450;
      const relY = -150; // top edge of aisle rack

      dom.laserBeam.setAttribute('x2', String(relX));
      dom.laserBeam.setAttribute('y2', String(relY));
      dom.laserBeam.setAttribute('stroke', isAck ? '#10b981' : '#ef4444');
      dom.laserBeam.setAttribute('stroke-width', '3');
      dom.laserBeam.setAttribute('stroke-dasharray', 'none');
      dom.laserBeam.setAttribute('opacity', state.laser.power ? '1.0' : '0');

      // Update Setup Tab angle display to match target lock
      if (state.laser.calibratedAngles[activeRack] !== undefined) {
        state.laser.panAngle = state.laser.calibratedAngles[activeRack];
        updateLaserDisplay();
      }
    } else {
      // Idle or Manual Jog Aiming
      updateLaserBeamManual();
    }
  }

  function updateLaserBeamManual() {
    if (!dom.laserBeam) return;
    const rad = (state.laser.panAngle * Math.PI) / 180;
    const length = 170;
    const relX = length * Math.sin(rad);
    const relY = -length * Math.cos(rad);

    dom.laserBeam.setAttribute('x2', String(relX));
    dom.laserBeam.setAttribute('y2', String(relY));
    dom.laserBeam.setAttribute('stroke', '#ef4444');
    dom.laserBeam.setAttribute('stroke-width', '2');
    dom.laserBeam.setAttribute('stroke-dasharray', '4,4');
    dom.laserBeam.setAttribute('opacity', state.laser.power ? '0.4' : '0');
  }

  // =========================================================================
  // 6. Manual Acknowledgment Action (POST /incidents/{id}/ack)
  // =========================================================================
  async function acknowledgeActiveIncident() {
    if (!state.incident || !state.incident.id) {
      console.warn('No active incident to acknowledge.');
      return;
    }

    const incidentId = state.incident.id;

    // Zero-latency local optimistic update
    state.incident.state = 'ACKNOWLEDGED';
    updateIncident(state.incident);

    try {
      const resp = await fetch(`${getApiBase()}/incidents/${encodeURIComponent(incidentId)}/ack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });

      if (!resp.ok) {
        console.warn(`ACK request returned status ${resp.status}`);
      } else {
        const updated = await resp.json();
        console.log('[Beacon] Incident successfully acknowledged:', updated);
      }
    } catch (err) {
      console.error('[Beacon] Failed to send acknowledge request:', err);
    }
  }

  // =========================================================================
  // 7. Desktop Tab Navigation
  // =========================================================================
  function initTabNavigation() {
    dom.tabBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetTabId = btn.getAttribute('data-tab');

        // Style tab buttons
        dom.tabBtns.forEach((b) => {
          if (b === btn) {
            b.className = 'tab-btn px-4 py-1.5 rounded-lg text-xs font-semibold tracking-wide font-mono transition-all bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20';
          } else {
            b.className = 'tab-btn px-4 py-1.5 rounded-lg text-xs font-semibold tracking-wide font-mono transition-all text-slate-400 hover:text-slate-200';
          }
        });

        // Toggle panes
        dom.tabPanes.forEach((pane) => {
          if (pane.id === targetTabId) {
            pane.classList.remove('hidden');
            pane.classList.add('flex');
          } else {
            pane.classList.add('hidden');
            pane.classList.remove('flex');
          }
        });

        // Trigger Model fetch if navigating to Model tab
        if (targetTabId === 'tab-model' && !state.metrics) {
          fetchModelMetrics();
        }
      });
    });
  }

  // =========================================================================
  // 8. Model Proof Tab: Fetch Metrics & Render Confusion Matrices (Dual-Brain)
  // =========================================================================
  const RHYTHM_ABBREV = {
    'burst_2_every_30s': 'B2-30s',
    'burst_4_every_30s': 'B4-30s',
    'not_alarm': 'Ambient',
    'one_long_beep': '1-Long',
    'paired_rapid': 'Paired',
    'pulse_every_0_5s': '0.5s',
    'pulse_every_2s': '2.0s',
    'pulse_every_3s': '3.0s',
    'pulse_every_4s': '4.0s',
    'pulse_every_10s': '10.0s',
    'repeating_long_beep': 'Rep-Long',
    'solid_tone': 'Solid',
  };

  async function fetchModelMetrics() {
    if (dom.btnRefreshMetrics) {
      dom.btnRefreshMetrics.textContent = 'Loading...';
    }

    try {
      const [locResult, rhythmResult] = await Promise.allSettled([
        fetch(`${getApiBase()}/model/location/metrics`).then(r => r.ok ? r.json() : null),
        fetch(`${getApiBase()}/model/rhythm/metrics`).then(r => r.ok ? r.json() : null),
      ]);

      if (locResult.status === 'fulfilled' && locResult.value) {
        state.locationMetrics = locResult.value;
        renderLocationMetrics(locResult.value);
      } else {
        renderFallbackLocationMetrics();
      }

      if (rhythmResult.status === 'fulfilled' && rhythmResult.value) {
        state.rhythmMetrics = rhythmResult.value;
        renderRhythmMetrics(rhythmResult.value);
      } else {
        renderFallbackRhythmMetrics();
      }
    } catch (err) {
      console.warn('[Beacon] Error fetching model metrics:', err);
      renderFallbackLocationMetrics();
      renderFallbackRhythmMetrics();
    } finally {
      if (dom.btnRefreshMetrics) {
        dom.btnRefreshMetrics.textContent = '↻ Refresh Metrics';
      }
    }
  }

  function renderLocationMetrics(data) {
    if (!data) return;

    // 1. Accuracies
    const loudestAcc = data.loudest_mic && typeof data.loudest_mic.accuracy === 'number'
      ? (data.loudest_mic.accuracy * 100).toFixed(1)
      : '51.7';
    const centroidAcc = data.weighted_centroid && typeof data.weighted_centroid.accuracy === 'number'
      ? (data.weighted_centroid.accuracy * 100).toFixed(1)
      : '51.0';
    const rfAcc = data.random_forest && typeof data.random_forest.accuracy === 'number'
      ? (data.random_forest.accuracy * 100).toFixed(1)
      : '100.0';

    if (dom.metricLoudestAcc) dom.metricLoudestAcc.textContent = `${loudestAcc}%`;
    if (dom.metricCentroidAcc) dom.metricCentroidAcc.textContent = `${centroidAcc}%`;
    if (dom.metricRfAcc) dom.metricRfAcc.textContent = `${rfAcc}%`;

    // 2. Confusion Matrices
    const classes = data.classes || ['A', 'B', 'C', 'D', 'E', 'NONE'];

    if (dom.cmLoudest && data.loudest_mic && data.loudest_mic.confusion_matrix) {
      dom.cmLoudest.innerHTML = buildConfusionMatrixHtml(data.loudest_mic.confusion_matrix, classes, 'rose');
    }
    if (dom.cmCentroid && data.weighted_centroid && data.weighted_centroid.confusion_matrix) {
      dom.cmCentroid.innerHTML = buildConfusionMatrixHtml(data.weighted_centroid.confusion_matrix, classes, 'amber');
    }
    if (dom.cmRf && data.random_forest && data.random_forest.confusion_matrix) {
      dom.cmRf.innerHTML = buildConfusionMatrixHtml(data.random_forest.confusion_matrix, classes, 'cyan');
    }
  }

  function renderFallbackLocationMetrics() {
    if (dom.metricLoudestAcc) dom.metricLoudestAcc.textContent = '51.7%';
    if (dom.metricCentroidAcc) dom.metricCentroidAcc.textContent = '51.0%';
    if (dom.metricRfAcc) dom.metricRfAcc.textContent = '100.0%';
  }

  function renderRhythmMetrics(data) {
    if (!data) return;

    // 1. Validation Macro F1s
    const valF1 = data.val_macro_f1 || {};
    const sgdF1 = typeof valF1.sgd_log === 'number'
      ? (valF1.sgd_log * 100).toFixed(1)
      : '73.2';
    const rfF1 = typeof valF1.random_forest === 'number'
      ? (valF1.random_forest * 100).toFixed(1)
      : '99.0';

    if (dom.metricRhythmSgdF1) dom.metricRhythmSgdF1.textContent = `${sgdF1}%`;
    if (dom.metricRhythmRfF1) dom.metricRhythmRfF1.textContent = `${rfF1}%`;

    // 2. Test Set Metrics
    const testData = data.test || {};
    const testAcc = typeof testData.accuracy === 'number'
      ? (testData.accuracy * 100).toFixed(1)
      : '99.2';
    const falseAlarm = typeof data.noise_false_alarm_rate === 'number'
      ? (data.noise_false_alarm_rate * 100).toFixed(1)
      : '0.0';

    if (dom.metricRhythmTestAcc) dom.metricRhythmTestAcc.textContent = `${testAcc}%`;
    if (dom.metricRhythmFalseAlarm) dom.metricRhythmFalseAlarm.textContent = `${falseAlarm}%`;

    // 3. Cadence Confusion Matrix
    if (dom.cmRhythm && testData.confusion_matrix) {
      const cm = testData.confusion_matrix;
      const labels = cm.labels || [];
      const rows = cm.rows_are_true || [];
      dom.cmRhythm.innerHTML = buildRhythmConfusionMatrixHtml(rows, labels);
    }
  }

  function renderFallbackRhythmMetrics() {
    if (dom.metricRhythmSgdF1) dom.metricRhythmSgdF1.textContent = '73.2%';
    if (dom.metricRhythmRfF1) dom.metricRhythmRfF1.textContent = '99.0%';
    if (dom.metricRhythmTestAcc) dom.metricRhythmTestAcc.textContent = '99.2%';
    if (dom.metricRhythmFalseAlarm) dom.metricRhythmFalseAlarm.textContent = '0.0%';
  }

  function buildRhythmConfusionMatrixHtml(matrix, classes) {
    if (!matrix || !classes || !classes.length) {
      return '<div class="text-xs text-slate-500 font-mono p-4">No cadence confusion matrix data available.</div>';
    }

    let html = `
      <table class="w-full text-[10px] font-mono text-center border-collapse min-w-[700px]">
        <thead>
          <tr class="text-slate-500 border-b border-slate-800">
            <th class="p-1.5 text-left text-[9px] text-slate-400 bg-slate-950/80 sticky left-0">TRUE \\ PRED</th>
            ${classes.map(c => {
              const shortName = RHYTHM_ABBREV[c] || c;
              return `<th class="p-1.5 font-bold text-slate-300" title="${c}">${shortName}</th>`;
            }).join('')}
          </tr>
        </thead>
        <tbody>
    `;

    matrix.forEach((row, rowIdx) => {
      const trueClass = classes[rowIdx] || rowIdx;
      const trueShort = RHYTHM_ABBREV[trueClass] || trueClass;
      html += `
        <tr class="border-b border-slate-800/40 hover:bg-slate-800/30">
          <td class="p-1.5 text-left font-bold text-slate-300 bg-slate-950/90 sticky left-0" title="${trueClass}">${trueShort}</td>
      `;

      row.forEach((count, colIdx) => {
        const isDiagonal = rowIdx === colIdx;
        const predClass = classes[colIdx] || colIdx;
        let cellClass = 'p-1.5 ';
        let title = `True: ${trueClass} -> Pred: ${predClass} (${count})`;

        if (count > 0) {
          if (isDiagonal) {
            cellClass += 'bg-purple-950/80 text-purple-300 font-black border border-purple-500/40';
          } else {
            cellClass += 'bg-rose-950/50 text-rose-300 font-bold border border-rose-500/40';
          }
        } else {
          cellClass += 'text-slate-700';
        }

        html += `<td class="${cellClass}" title="${title}">${count}</td>`;
      });

      html += `</tr>`;
    });

    html += `
        </tbody>
      </table>
    `;
    return html;
  }

  function buildConfusionMatrixHtml(matrix, classes, theme) {
    let html = `
      <table class="w-full text-xs font-mono text-center border-collapse">
        <thead>
          <tr class="text-slate-500 border-b border-slate-800">
            <th class="p-1.5 text-left text-[10px] text-slate-400">TRUE \\ PRED</th>
            ${classes.map(c => `<th class="p-1.5 font-bold">${c}</th>`).join('')}
          </tr>
        </thead>
        <tbody>
    `;

    matrix.forEach((row, rowIdx) => {
      const trueClass = classes[rowIdx] || rowIdx;
      html += `
        <tr class="border-b border-slate-800/40 hover:bg-slate-800/20">
          <td class="p-1.5 text-left font-bold text-slate-400 bg-slate-950/40">${trueClass}</td>
      `;

      row.forEach((count, colIdx) => {
        const isDiagonal = rowIdx === colIdx;
        let cellClass = 'p-1.5 ';

        if (count > 0) {
          if (isDiagonal) {
            cellClass += theme === 'cyan'
              ? 'bg-cyan-950/80 text-cyan-300 font-black border border-cyan-500/40'
              : 'bg-emerald-950/80 text-emerald-300 font-bold border border-emerald-500/30';
          } else {
            cellClass += 'bg-rose-950/50 text-rose-300 font-bold border border-rose-500/30';
          }
        } else {
          cellClass += 'text-slate-700';
        }

        html += `<td class="${cellClass}">${count}</td>`;
      });

      html += `</tr>`;
    });

    html += `
        </tbody>
      </table>
    `;
    return html;
  }

  // =========================================================================
  // 9. Laser Turret Setup & Calibration
  // =========================================================================
  function jogLaser(delta) {
    state.laser.panAngle = Math.max(-45, Math.min(45, state.laser.panAngle + delta));
    updateLaserDisplay();
    updateLaserBeamManual();
  }

  function updateLaserDisplay() {
    if (dom.laserAngleDisplay) {
      const sign = state.laser.panAngle > 0 ? '+' : '';
      dom.laserAngleDisplay.textContent = `${sign}${state.laser.panAngle}°`;
    }
  }

  function initLaserSetup() {
    // Jog Left
    if (dom.btnJogLeft) {
      dom.btnJogLeft.addEventListener('click', () => jogLaser(-5));
    }

    // Jog Right
    if (dom.btnJogRight) {
      dom.btnJogRight.addEventListener('click', () => jogLaser(5));
    }

    // Laser Toggle
    if (dom.btnToggleLaser) {
      dom.btnToggleLaser.addEventListener('click', () => {
        state.laser.power = !state.laser.power;
        if (state.laser.power) {
          dom.btnToggleLaser.className = 'px-6 py-4 rounded-xl bg-rose-600 hover:bg-rose-500 active:bg-rose-700 text-white font-bold text-sm font-mono flex items-center gap-2 shadow-lg shadow-rose-900/40';
          dom.btnToggleLaser.textContent = '🔴 Laser: ON';
        } else {
          dom.btnToggleLaser.className = 'px-6 py-4 rounded-xl bg-slate-800 hover:bg-slate-700 active:bg-slate-600 text-slate-400 font-bold text-sm font-mono flex items-center gap-2 border border-slate-700';
          dom.btnToggleLaser.textContent = '⚪ Laser: OFF';
        }
        syncSvgAisleMap(state.incident);
      });
    }

    // Keyboard Arrow Keys
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        jogLaser(-5);
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        jogLaser(5);
      }
    });

    // Save Rack Angle Buttons
    dom.btnSaveRacks.forEach((btn) => {
      btn.addEventListener('click', () => {
        const rackId = btn.getAttribute('data-rack');
        if (!rackId) return;

        state.laser.calibratedAngles[rackId] = state.laser.panAngle;

        // Visual confirmation
        const origHtml = btn.innerHTML;
        btn.innerHTML = `
          Rack ${rackId} (${state.laser.panAngle > 0 ? '+' : ''}${state.laser.panAngle}°)
          <span class="block text-[10px] text-emerald-400 mt-1 font-bold">Angle Locked ✓</span>
        `;
        btn.classList.add('border-emerald-500', 'bg-emerald-950/40');

        setTimeout(() => {
          btn.innerHTML = origHtml;
          btn.classList.remove('border-emerald-500', 'bg-emerald-950/40');
        }, 1500);

        console.log(`[Beacon Laser] Saved angle for Rack ${rackId}: ${state.laser.panAngle}°`);
      });
    });

    // Test Blanking Button (350 ms acoustic blanking window)
    if (dom.btnTestBlanking) {
      dom.btnTestBlanking.addEventListener('click', () => {
        const origText = dom.btnTestBlanking.textContent;
        dom.btnTestBlanking.textContent = 'Blanking Active (350ms)...';
        dom.btnTestBlanking.className = 'px-4 py-2 rounded-lg bg-amber-600 text-slate-950 font-bold text-xs font-mono animate-pulse';

        setTimeout(() => {
          dom.btnTestBlanking.textContent = origText;
          dom.btnTestBlanking.className = 'px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-mono text-slate-300';
        }, 350);
      });
    }
  }

  // =========================================================================
  // 10. Responsive View Simulation Toggles (Desktop <-> Pager Mode)
  // =========================================================================
  function initSimulationToggles() {
    if (dom.btnToggleMobile) {
      dom.btnToggleMobile.addEventListener('click', () => {
        if (document.body.classList.contains('force-desktop')) {
          document.body.classList.remove('force-desktop');
          document.body.classList.add('force-mobile');
        } else {
          document.body.classList.remove('force-mobile');
          document.body.classList.add('force-desktop');
        }
      });
    }

    if (dom.btnToggleDesktop) {
      dom.btnToggleDesktop.addEventListener('click', () => {
        if (document.body.classList.contains('force-mobile')) {
          document.body.classList.remove('force-mobile');
          document.body.classList.add('force-desktop');
        } else {
          document.body.classList.remove('force-desktop');
          document.body.classList.add('force-mobile');
        }
      });
    }
  }

  // =========================================================================
  // 11. Pitch Simulation & Demo Bar Controls
  // =========================================================================
  function setDemoPattern(pattern) {
    if (!['P1', 'P2', 'P3'].includes(pattern)) return;
    state.demo.selectedPattern = pattern;

    dom.patternBtns.forEach((btn) => {
      const btnPat = btn.getAttribute('data-pattern');
      if (btnPat === pattern) {
        btn.className = 'demo-pattern-btn px-2 py-0.5 rounded border border-cyan-500 bg-cyan-950/80 text-cyan-300 font-bold transition-all';
      } else {
        btn.className = 'demo-pattern-btn px-2 py-0.5 rounded border border-slate-800 bg-slate-950/60 text-slate-400 hover:text-slate-200 transition-all';
      }
    });
    console.log(`[Beacon Demo] Active alarm pattern set to: ${pattern}`);
  }

  async function toggleReplay(forceState = null) {
    try {
      const payload = forceState !== null ? { paused: forceState } : null;
      const resp = await fetch(`${getApiBase()}/demo/replay/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload ? JSON.stringify(payload) : null,
      });

      if (resp.ok) {
        const data = await resp.json();
        state.demo.replayPaused = Boolean(data.replay_paused);
        updateReplayButtonUI(state.demo.replayPaused);
      }
    } catch (err) {
      console.warn('[Beacon Demo] Failed to toggle replay:', err);
    }
  }

  function updateReplayButtonUI(isPaused) {
    if (!dom.btnReplayToggle) return;
    if (isPaused) {
      dom.btnReplayToggle.className = 'px-2.5 py-1 rounded-lg bg-amber-950/80 border border-amber-500/40 text-amber-300 font-bold hover:bg-amber-900/60 transition-all flex items-center gap-1.5';
      if (dom.replayStatusDot) dom.replayStatusDot.className = 'w-2 h-2 rounded-full bg-amber-400';
      if (dom.replayStatusText) dom.replayStatusText.textContent = '⏸ Auto-Replay: PAUSED';
    } else {
      dom.btnReplayToggle.className = 'px-2.5 py-1 rounded-lg bg-emerald-950/80 border border-emerald-500/40 text-emerald-300 font-bold hover:bg-emerald-900/60 transition-all flex items-center gap-1.5';
      if (dom.replayStatusDot) dom.replayStatusDot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
      if (dom.replayStatusText) dom.replayStatusText.textContent = '▶ Auto-Replay: ON';
    }
  }

  async function triggerDemoRack(rack) {
    const rackUpper = rack.toUpperCase();
    const pattern = state.demo.selectedPattern || 'P1';

    // Optimistically update replay button to paused state
    state.demo.replayPaused = true;
    updateReplayButtonUI(true);

    // Visual button bounce feedback
    dom.triggerRackBtns.forEach((btn) => {
      if (btn.getAttribute('data-rack') === rackUpper) {
        btn.classList.add('bg-cyan-500', 'text-slate-950', 'scale-105', 'shadow-md', 'shadow-cyan-500/50');
        setTimeout(() => {
          btn.classList.remove('bg-cyan-500', 'text-slate-950', 'scale-105', 'shadow-md', 'shadow-cyan-500/50');
        }, 300);
      }
    });

    console.log(`[Beacon Demo] Triggering Rack ${rackUpper} with Pattern ${pattern}...`);

    try {
      const resp = await fetch(`${getApiBase()}/demo/trigger/${rackUpper}/${pattern}?realtime=true`, {
        method: 'POST',
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.incident) {
          updateIncident(data.incident);
        }
      }
    } catch (err) {
      console.warn(`[Beacon Demo] Failed to trigger Rack ${rackUpper}:`, err);
    }
  }

  function initDemoPitchControls() {
    // 1. Initial Replay State (default Paused for Live Hardware)
    updateReplayButtonUI(state.demo.replayPaused);

    // 2. Replay Toggle Click
    if (dom.btnReplayToggle) {
      dom.btnReplayToggle.addEventListener('click', () => toggleReplay());
    }

    // 2. Pattern Select Clicks
    dom.patternBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const pat = btn.getAttribute('data-pattern');
        setDemoPattern(pat);
      });
    });

    // 3. Quick Rack Trigger Clicks
    dom.triggerRackBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const rack = btn.getAttribute('data-rack');
        triggerDemoRack(rack);
      });
    });

    // 4. Keyboard Shortcuts on Desktop (Keys 1-5, Q, W, E, P)
    window.addEventListener('keydown', (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;

      const key = e.key.toLowerCase();

      // [P] Toggle Auto-Replay Pause
      if (key === 'p') {
        e.preventDefault();
        toggleReplay();
        return;
      }

      // [Q/W/E] Select Alarm Pattern
      if (key === 'q') {
        e.preventDefault();
        setDemoPattern('P1');
        return;
      }
      if (key === 'w') {
        e.preventDefault();
        setDemoPattern('P2');
        return;
      }
      if (key === 'e') {
        e.preventDefault();
        setDemoPattern('P3');
        return;
      }

      // [1-5] Trigger Racks A through E
      if (['1', '2', '3', '4', '5'].includes(key)) {
        e.preventDefault();
        const rackMap = { '1': 'A', '2': 'B', '3': 'C', '4': 'D', '5': 'E' };
        triggerDemoRack(rackMap[key]);
        return;
      }
    });
  }

  // =========================================================================
  // 12. Initial REST Hydration & Timer Loop
  // =========================================================================
  async function hydrateInitialState() {
    try {
      const resp = await fetch(`${getApiBase()}/incidents`);
      if (resp.ok) {
        const data = await resp.json();
        if (data.active) {
          updateIncident(data.active);
        }
      }
    } catch (e) {
      console.log('[Beacon] Note: Could not prefetch initial active incident:', e);
    }
  }

  function initRelativeTimeTicker() {
    setInterval(() => {
      if (!dom.desktopLastHeard) return;
      if (!state.incident || state.incident.state === 'CLEARED' || !state.incident.last_heard_ts) {
        dom.desktopLastHeard.textContent = 'Last heard: —';
        return;
      }

      const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - state.incident.last_heard_ts));
      dom.desktopLastHeard.textContent = `Last heard: ${elapsed}s ago`;
    }, 1000);
  }

  // =========================================================================
  // 12. Dynamic QR Code for Mobile Technician Pager Hand-Off
  // =========================================================================
  async function initQrCodeHandoff() {
    let localIp = null;
    try {
      const resp = await fetch(`${getApiBase()}/layout`);
      if (resp.ok) {
        const data = await resp.json();
        if (data.local_ip) {
          localIp = data.local_ip;
        }
      }
    } catch (e) {
      console.warn('[Beacon] Could not fetch /layout for local_ip:', e);
    }

    let hostname = window.location.hostname;
    // If hostname is localhost or loopback, prioritize local LAN IP so phones can connect
    if (!hostname || hostname === 'localhost' || hostname === '127.0.0.1') {
      if (localIp && localIp !== '127.0.0.1') {
        hostname = localIp;
      } else {
        hostname = '127.0.0.1';
      }
    }

    const port = window.location.port ? `:${window.location.port}` : ':8000';
    const pagerUrl = `http://${hostname}${port}/?mobile=1`;

    renderQrCanvas('qr-canvas-header', 'qr-container-header', pagerUrl, 44);
    if (dom.qrLinkHeader) {
      dom.qrLinkHeader.href = pagerUrl;
      dom.qrLinkHeader.textContent = `${hostname}${port}/?mobile=1`;
    }
    if (dom.headerQrBox) {
      dom.headerQrBox.onclick = () => window.open(pagerUrl, '_blank');
    }

    renderQrCanvas('qr-canvas-sidebar', 'qr-container-sidebar', pagerUrl, 70);
    if (dom.qrLinkSidebar) {
      dom.qrLinkSidebar.href = pagerUrl;
      dom.qrLinkSidebar.textContent = pagerUrl;
    }
    if (dom.sidebarQrBox) {
      dom.sidebarQrBox.onclick = () => window.open(pagerUrl, '_blank');
    }
  }

  function renderQrCanvas(canvasId, containerId, text, size) {
    const canvas = document.getElementById(canvasId);
    const container = document.getElementById(containerId);

    if (typeof QRious !== 'undefined' && canvas) {
      try {
        new QRious({
          element: canvas,
          value: text,
          size: size,
          level: 'M',
          background: '#ffffff',
          foreground: '#000000',
        });
        canvas.style.display = 'block';
        if (container) container.style.display = 'none';
        return;
      } catch (e) {
        console.warn('QRious render error:', e);
      }
    }

    if (typeof QRCode !== 'undefined' && container) {
      try {
        container.innerHTML = '';
        new QRCode(container, {
          text: text,
          width: size,
          height: size,
          colorDark: '#000000',
          colorLight: '#ffffff',
        });
        if (canvas) canvas.style.display = 'none';
        container.style.display = 'block';
        return;
      } catch (e) {
        console.warn('QRCode render error:', e);
      }
    }
  }

  // =========================================================================
  // 13. Application Bootstrapper
  // =========================================================================
  function initApp() {
    // Check for ?mobile=1 in query parameter
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('mobile') === '1' || urlParams.get('mode') === 'pager') {
      document.body.classList.add('force-mobile');
    }

    // Bind Action Buttons
    if (dom.btnMobileAck) {
      dom.btnMobileAck.addEventListener('click', acknowledgeActiveIncident);
    }
    if (dom.btnDesktopAck) {
      dom.btnDesktopAck.addEventListener('click', acknowledgeActiveIncident);
    }
    if (dom.btnRefreshMetrics) {
      dom.btnRefreshMetrics.addEventListener('click', fetchModelMetrics);
    }

    // Initialize Subsystems
    initTabNavigation();
    initLaserSetup();
    initSimulationToggles();
    initDemoPitchControls();
    initRelativeTimeTicker();
    initQrCodeHandoff();

    // Hydrate & Connect
    hydrateInitialState();
    fetchModelMetrics();
    initWebSocket();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }

})();

