/**
 * Exam page — LiveKit publisher (pure live) + optional local recording.
 *
 *   - Reads proc_session_id from the examRuntimeConfig data attribute (injected
 *     by Odoo at render time) with a fallback to the URL query string.
 *   - Requests a candidate token from Odoo.
 *   - Connects to LiveKit and publishes camera + mic.
 *   - The proctor dashboard is already subscribed to the same room, so the
 *     feed appears automatically with zero custom signaling code.
 *   - If record_video=1, a local MediaRecorder archives the same MediaStream
 *     and uploads a WebM blob on submit / pagehide.
 */
(function () {
    "use strict";

    var cfg = document.getElementById('examRuntimeConfig');
    if (!cfg) {
        console.warn('[ExamLive] No runtime config, abort.');
        return;
    }

    var RECORD_VIDEO = cfg.dataset.recordVideo === '1';
    var IS_PROCTORED = cfg.dataset.isProctored === '1';

    // Read proc_session_id from the server-rendered data attribute first.
    // Odoo's /survey/start/ -> /survey/fill/ redirect can strip query params,
    // so the URL alone is unreliable. The div attribute is injected by
    // exam_survey_fill_inject.xml and is always present when proctoring is on.
    var _cfgSessionId = parseInt(cfg.dataset.procSessionId, 10);
    var _urlSessionId = parseInt(
        new URLSearchParams(window.location.search).get('proc_session_id'), 10);
    var PROC_SESSION_ID = _cfgSessionId || _urlSessionId;
    if (!PROC_SESSION_ID) {
        console.warn('[ExamLive] proc_session_id missing from config and URL, abort.');
        return;
    }
    console.log('[ExamLive] proc_session_id =', PROC_SESSION_ID,
        '(source:', _cfgSessionId ? 'data-attr' : 'url-param', ')');

    // ---- State ----
    var room = null;
    var localTracks = [];
    var recorderStream = null;
    var mediaRecorder = null;
    var recordedChunks = [];
    var uploaded = false;
    var stopped = false;

    function rpc(url, params) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: params }),
            credentials: 'same-origin',
        })
        .then(function (r) { return r.json(); })
        .then(function (d) { return d.result; });
    }

    function lkAvailable() {
        return typeof window.LivekitClient !== 'undefined';
    }

    // ---- Live badge ----
    function injectLiveBadge() {
        if (document.getElementById('examLiveBadge')) return;
        var b = document.createElement('div');
        b.id = 'examLiveBadge';
        b.style.cssText =
            'position:fixed;top:14px;right:14px;z-index:9999;' +
            'background:rgba(239,68,68,0.95);color:#fff;' +
            'padding:6px 12px;border-radius:6px;font-size:12px;' +
            'font-weight:700;text-transform:uppercase;letter-spacing:1px;' +
            'font-family:system-ui,sans-serif;' +
            'box-shadow:0 2px 8px rgba(0,0,0,0.25);' +
            'display:flex;align-items:center;gap:6px;';
        b.innerHTML =
            '<span style="width:8px;height:8px;background:#fff;border-radius:50%;' +
            'animation:exam-live-blink 1s infinite;"></span>' +
            '<span id="examLiveText">CONNECTING</span>';
        var style = document.createElement('style');
        style.textContent =
            '@keyframes exam-live-blink{0%,100%{opacity:1}50%{opacity:.2}}';
        document.head.appendChild(style);
        document.body.appendChild(b);
    }

    function setBadgeState(state) {
        var badge = document.getElementById('examLiveBadge');
        var text = document.getElementById('examLiveText');
        if (!badge || !text) return;
        if (state === 'live') {
            badge.style.background = 'rgba(239,68,68,0.95)';
            text.textContent = 'LIVE';
        } else if (state === 'connecting') {
            badge.style.background = 'rgba(245,158,11,0.95)';
            text.textContent = 'CONNECTING';
        } else if (state === 'lost') {
            badge.style.background = 'rgba(107,114,128,0.95)';
            text.textContent = 'RECONNECTING';
        } else if (state === 'rec') {
            badge.style.background = 'rgba(239,68,68,0.95)';
            text.textContent = 'REC';
        }
    }

    function hideLiveBadge() {
        var b = document.getElementById('examLiveBadge');
        if (b) b.remove();
    }

    // ---- Start ----
    function start() {
        if (!IS_PROCTORED && !RECORD_VIDEO) return;

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            console.warn('[ExamLive] getUserMedia indisponible (HTTPS ou localhost requis).');
            return;
        }

        injectLiveBadge();
        setBadgeState('connecting');

        // 1) Toujours capter la camera via getUserMedia — INDÉPENDANT de LiveKit.
        navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480, facingMode: 'user', frameRate: 20 },
            audio: true,
        })
        .then(function (stream) {
            recorderStream = stream;

            // 2) Enregistrement LOCAL (WebM) : marche sans LiveKit ni Minio.
            if (RECORD_VIDEO) {
                setupMediaRecorder(stream);
                setBadgeState('rec');
            }

            // 3) Diffusion live LiveKit : OPTIONNELLE et jamais bloquante.
            if (IS_PROCTORED && lkAvailable()) {
                return rpc('/exam/proctoring/livekit/candidate-token',
                           { session_id: PROC_SESSION_ID })
                    .then(function (info) {
                        if (!info || info.error) {
                            console.warn('[ExamLive] live indisponible:', info && info.error);
                            if (!RECORD_VIDEO) setBadgeState('lost');
                            return null;
                        }
                        return connectAndPublish(info);
                    })
                    .catch(function (e) {
                        console.warn('[ExamLive] live KO (enregistrement local OK):', e);
                        if (!RECORD_VIDEO) setBadgeState('lost');
                    });
            }
            if (IS_PROCTORED && !lkAvailable()) {
                console.warn('[ExamLive] LiveKit absent — live désactivé, '
                           + 'enregistrement local actif.');
                if (!RECORD_VIDEO) setBadgeState('lost');
            }
            return null;
        })
        .catch(function (err) {
            console.error('[ExamLive] accès caméra refusé/erreur:', err);
            setBadgeState('lost');
        });
    }

    function connectAndPublish(info) {
        room = new window.LivekitClient.Room({
            adaptiveStream: true,
            dynacast: true,
        });

        room.on(window.LivekitClient.RoomEvent.ConnectionStateChanged,
                function (state) {
            console.log('[ExamLive] connection state:', state);
            if (state === window.LivekitClient.ConnectionState.Connected) {
                setBadgeState('live');
            } else if (state === window.LivekitClient.ConnectionState.Reconnecting) {
                setBadgeState('lost');
            } else if (state === window.LivekitClient.ConnectionState.Connecting) {
                setBadgeState('connecting');
            } else if (state === window.LivekitClient.ConnectionState.Disconnected) {
                if (!RECORD_VIDEO) setBadgeState('lost');
            }
        });

        // On publie directement les pistes du MediaStream déjà capté.
        return room.connect(info.url, info.token).then(function () {
            console.log('[ExamLive] Joined room ' + info.room);
            var pubs = [];
            recorderStream.getTracks().forEach(function (track) {
                pubs.push(room.localParticipant.publishTrack(track, {
                    source: track.kind === 'video'
                        ? window.LivekitClient.Track.Source.Camera
                        : window.LivekitClient.Track.Source.Microphone,
                }));
            });
            return Promise.all(pubs);
        })
        .then(function () {
            console.log('[ExamLive] Tracks published');
            setBadgeState('live');
        });
    }

    // ---- Local recorder (optional) ----
    function setupMediaRecorder(stream) {
        var mime = 'video/webm;codecs=vp9,opus';
        if (!window.MediaRecorder || !MediaRecorder.isTypeSupported(mime)) {
            mime = 'video/webm;codecs=vp8,opus';
        }
        if (!MediaRecorder.isTypeSupported(mime)) {
            mime = 'video/webm';
        }
        try {
            mediaRecorder = new MediaRecorder(stream, {
                mimeType: mime,
                videoBitsPerSecond: 500000,
            });
        } catch (e) {
            console.error('[ExamLive] MediaRecorder error:', e);
            return;
        }
        mediaRecorder.ondataavailable = function (evt) {
            if (evt.data && evt.data.size > 0) {
                recordedChunks.push(evt.data);
            }
        };
        mediaRecorder.start(5000);
        console.log('[ExamLive] MediaRecorder started');
    }

    // ---- Stop + upload ----
    function stopAll() {
        stopped = true;
        if (room) {
            try { room.disconnect(); } catch (e) { /* ignore */ }
            room = null;
        }
        hideLiveBadge();
    }

    function stopAndUpload() {
        return new Promise(function (resolve) {
            stopAll();
            if (!mediaRecorder || mediaRecorder.state === 'inactive') {
                stopLocalTracks();
                resolve(false);
                return;
            }
            mediaRecorder.onstop = function () {
                stopLocalTracks();
                uploadBlob().then(resolve).catch(function () { resolve(false); });
            };
            try { mediaRecorder.stop(); }
            catch (e) { resolve(false); }
        });
    }

    function stopLocalTracks() {
        if (recorderStream) {
            recorderStream.getTracks().forEach(function (t) {
                try { t.stop(); } catch (e) { /* ignore */ }
            });
        }
        localTracks.forEach(function (t) {
            try {
                if (t.stop) t.stop();
                else if (t.mediaStreamTrack && t.mediaStreamTrack.stop) {
                    t.mediaStreamTrack.stop();
                }
            } catch (e) { /* ignore */ }
        });
    }

    function uploadBlob() {
        if (uploaded) return Promise.resolve(true);
        uploaded = true;
        if (recordedChunks.length === 0) return Promise.resolve(false);

        var blob = new Blob(recordedChunks, { type: 'video/webm' });
        console.log('[ExamLive] Upload ' + Math.round(blob.size / 1024) + 'ko');

        var fd = new FormData();
        fd.append('session_id', PROC_SESSION_ID);
        fd.append('video_blob', blob, 'recording.webm');

        return fetch('/exam/proctoring/upload-recording', {
            method: 'POST',
            body: fd,
            credentials: 'same-origin',
        })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            console.log('[ExamLive] Upload OK', d);
            return true;
        })
        .catch(function (e) {
            console.error('[ExamLive] Upload KO', e);
            return false;
        });
    }

    // ---- End triggers ----
    var _watcher = setInterval(function () {
        if (document.querySelector('.o_survey_finished')) {
            clearInterval(_watcher);
            stopAndUpload();
        }
    }, 1000);

    window.addEventListener('pagehide', function () {
        stopped = true;
        if (room) { try { room.disconnect(); } catch (e) {} }
        if (uploaded || recordedChunks.length === 0) return;
        try {
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                mediaRecorder.stop();
            }
            var blob = new Blob(recordedChunks, { type: 'video/webm' });
            var fd = new FormData();
            fd.append('session_id', PROC_SESSION_ID);
            fd.append('video_blob', blob, 'recording.webm');
            navigator.sendBeacon('/exam/proctoring/upload-recording', fd);
            uploaded = true;
        } catch (e) { /* ignore */ }
    });

    // ---- Listen for proctor exclusion via Odoo bus ----
    function listenForExclusion() {
        if (!PROC_SESSION_ID) return;
        // Odoo bus (longpolling) - available in portal pages when odoo.services exists
        if (window.odoo && window.odoo.services && window.odoo.services['bus.service']) {
            var bus = window.odoo.services['bus.service'];
            // Candidate channel is keyed by partner_id; we use a simpler
            // approach: poll our own session for the 'excluded' state.
        }
        // Fallback: poll via existing /exam/proctoring/poll endpoint
        // The candidate already polls for state changes in the waiting room,
        // but on the exam page there is no polling. We add a lightweight poll here.
        var excludePollTimer = setInterval(function () {
            if (stopped) { clearInterval(excludePollTimer); return; }
            fetch('/web/dataset/call_kw', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    jsonrpc: '2.0', method: 'call', id: 1,
                    params: {
                        model: 'exam.proctoring.session',
                        method: 'read',
                        args: [[PROC_SESSION_ID], ['state']],
                        kwargs: {},
                    }
                }),
                credentials: 'same-origin',
            })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d.result || !d.result[0]) return;
                var state = d.result[0].state;
                if (state === 'completed' || state === 'rejected') {
                    clearInterval(excludePollTimer);
                    stopped = true;
                    stopAll();
                    // Show exclusion banner and redirect after delay
                    showExclusionBanner();
                }
            })
            .catch(function () { /* silent */ });
        }, 4000);  // poll every 4s - lightweight
    }

    function showExclusionBanner() {
        var banner = document.createElement('div');
        banner.style.cssText =
            'position:fixed;top:0;left:0;right:0;bottom:0;z-index:99999;' +
            'background:rgba(0,0,0,0.85);display:flex;align-items:center;' +
            'justify-content:center;flex-direction:column;color:#fff;' +
            'font-family:system-ui,sans-serif;text-align:center;padding:32px;';
        banner.innerHTML =
            '<div style="font-size:48px;margin-bottom:16px;">🚫</div>' +
            '<h2 style="margin:0 0 12px;font-size:24px;">Session terminée</h2>' +
            '<p style="margin:0 0 24px;color:#ccc;max-width:420px;">' +
            "Votre session d'examen a été clôturée par le surveillant." +
            '</p>' +
            '<p style="color:#9ca3af;font-size:14px;">Redirection dans quelques secondes...</p>';
        document.body.appendChild(banner);
        setTimeout(function () {
            window.location.href = '/my/exams';
        }, 4000);
    }

    // ---- Init ----
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            start();
            listenForExclusion();
        });
    } else {
        start();
        listenForExclusion();
    }

})();
