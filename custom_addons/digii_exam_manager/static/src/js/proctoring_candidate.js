/**
 * Waiting room (candidate) — LiveKit publisher.
 *
 * The SDK exposes `LivekitClient` as a global (loaded from unpkg in the
 * template). We use:
 *   - LivekitClient.Room          -> the LiveKit room connection
 *   - LivekitClient.createLocalTracks -> wrapper around getUserMedia
 *
 * Flow :
 *   1. User clicks "activer camera" -> createLocalTracks()
 *   2. Show local preview in the <video>
 *   3. Ask Odoo for a JWT via /exam/proctoring/livekit/candidate-token
 *   4. room.connect(url, token) + room.localParticipant.publishTrack()
 *   5. Poll /exam/proctoring/poll for state changes (waiting -> authorized
 *      -> rejected) because that part stays in Odoo, not LiveKit.
 *   6. On "authorized" button click -> navigate to exam page; LiveKit tracks
 *      stay published until the next page takes over.
 */
(function () {
    "use strict";

    var SESSION_ID = 0;
    var SESSION_STATE = '';
    var POLL_INTERVAL = 2000;   // State polling is not the live feed anymore

    var room = null;
    var localTracks = [];
    var pollTimer = null;
    var currentState = '';
    var stopped = false;

    var videoEl, overlay, liveBadge, cameraBtn, statusPanel;
    var statusIcon, statusIconI, statusTitle, statusDesc, statusLoader, btnStartExam;
    var stepCamera, stepWaiting, stepExam;

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

    // ---- Expose globally ----
    window.startCamera = function () {
        if (!lkAvailable()) {
            alert("LiveKit SDK non charge. Verifiez la connexion au CDN.");
            console.error('[Candidate] LivekitClient global missing');
            return;
        }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert(
                "Votre navigateur ne peut pas acceder a la camera.\n\n" +
                "La camera necessite HTTPS ou localhost."
            );
            return;
        }

        // 1) Create local video + audio tracks
        window.LivekitClient.createLocalTracks({
            audio: true,
            video: { resolution: { width: 640, height: 480, frameRate: 20 } },
        })
        .then(function (tracks) {
            localTracks = tracks;

            // 2) Attach video preview
            tracks.forEach(function (t) {
                if (t.kind === 'video') {
                    // track.attach() returns a <video> element but we already
                    // have one in the DOM; use mediaStreamTrack directly.
                    videoEl.srcObject = new MediaStream([t.mediaStreamTrack]);
                }
            });
            overlay.classList.add('hidden');
            liveBadge.classList.add('active');
            cameraBtn.style.display = 'none';
            statusPanel.style.display = 'block';
            stepCamera.classList.add('done');
            stepWaiting.classList.add('active');

            // 3) Ask Odoo for a LiveKit JWT
            return rpc('/exam/proctoring/livekit/candidate-token',
                       { session_id: SESSION_ID });
        })
        .then(function (info) {
            if (!info || info.error) {
                throw new Error(info && info.error || 'Token refuse');
            }
            // 4) Connect + publish
            return connectAndPublish(info);
        })
        .then(function () {
            // 5) Poll for state changes (authorized / rejected)
            startPolling();
        })
        .catch(function (err) {
            console.error('[Candidate] setup error:', err);
            alert("Impossible d'activer la camera : " + (err.message || err));
        });
    };

    function connectAndPublish(info) {
        room = new window.LivekitClient.Room({
            adaptiveStream: true,
            dynacast: true,
            // reconnectPolicy default is fine; the SDK handles ICE restart
            // and resume automatically, including after NAT changes.
        });

        room.on(window.LivekitClient.RoomEvent.Disconnected, function (reason) {
            console.warn('[Candidate] LiveKit disconnected:', reason);
        });
        room.on(window.LivekitClient.RoomEvent.Reconnecting, function () {
            console.log('[Candidate] LiveKit reconnecting...');
        });
        room.on(window.LivekitClient.RoomEvent.Reconnected, function () {
            console.log('[Candidate] LiveKit reconnected');
        });

        return room.connect(info.url, info.token)
            .then(function () {
                console.log('[Candidate] Joined room ' + info.room);
                var pubs = localTracks.map(function (t) {
                    return room.localParticipant.publishTrack(t, {
                        source: t.kind === 'video'
                            ? window.LivekitClient.Track.Source.Camera
                            : window.LivekitClient.Track.Source.Microphone,
                    });
                });
                return Promise.all(pubs);
            })
            .then(function () {
                console.log('[Candidate] Tracks published');
            });
    }

    window.startExam = function () {
        btnStartExam.disabled = true;
        btnStartExam.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Chargement...';

        rpc('/exam/proctoring/start-exam', { session_id: SESSION_ID })
        .then(function (data) {
            if (data && data.survey_url) {
                stopped = true;
                if (pollTimer) clearInterval(pollTimer);
                // IMPORTANT: do NOT disconnect the LiveKit room here.
                // The next page (exam_recording.js) will receive the same
                // navigation and immediately re-connect with its own token.
                // On some browsers navigating keeps the MediaStream alive
                // across pages, so we let the natural page unload stop it.
                window.location.href = data.survey_url;
            } else {
                alert(data && data.error ? data.error : 'Erreur lors du lancement.');
                btnStartExam.disabled = false;
                btnStartExam.innerHTML = '<i class="fa fa-play"></i> Commencer l\'examen';
            }
        })
        .catch(function () {
            alert('Erreur de connexion.');
            btnStartExam.disabled = false;
            btnStartExam.innerHTML = '<i class="fa fa-play"></i> Commencer l\'examen';
        });
    };

    // ---- Polling for state changes ----
    function startPolling() {
        pollTimer = setInterval(doPoll, POLL_INTERVAL);
    }

    function doPoll() {
        if (stopped) return;
        rpc('/exam/proctoring/poll', { session_id: SESSION_ID })
        .then(function (result) {
            if (!result) return;
            if (result.state && result.state !== currentState) {
                currentState = result.state;
                if (result.state === 'authorized') updateUIAuthorized();
                else if (result.state === 'rejected') updateUIRejected(result.rejection_reason || '');
            }
        })
        .catch(function () { /* silent */ });
    }

    // ---- UI ----
    function updateUIAuthorized() {
        statusIcon.className = 'wr-status-icon authorized';
        statusIconI.className = 'fa fa-check-circle';
        statusTitle.textContent = 'Vous etes autorise !';
        statusDesc.textContent = 'Le surveillant a valide votre identite. Vous pouvez commencer.';
        statusLoader.style.display = 'none';
        btnStartExam.style.display = 'inline-flex';
        btnStartExam.classList.remove('disabled');
        stepWaiting.classList.remove('active');
        stepWaiting.classList.add('done');
        stepExam.classList.add('active');
        var vc = document.querySelector('.wr-video-card');
        if (vc) vc.style.borderColor = '#10B981';
    }

    function updateUIRejected(reason) {
        stopped = true;
        statusIcon.className = 'wr-status-icon rejected';
        statusIconI.className = 'fa fa-times-circle';
        statusTitle.textContent = 'Session rejetee';
        statusDesc.textContent = reason || 'Votre session a ete rejetee par le surveillant.';
        statusLoader.style.display = 'none';
        btnStartExam.style.display = 'none';
        var vc = document.querySelector('.wr-video-card');
        if (vc) vc.style.borderColor = '#EF4444';
        if (pollTimer) clearInterval(pollTimer);
        if (room) {
            try { room.disconnect(); } catch (e) { /* ignore */ }
        }
    }

    // ---- Init ----
    document.addEventListener('DOMContentLoaded', function () {
        var configEl = document.getElementById('waitingRoomConfig');
        if (!configEl) return;

        SESSION_ID = parseInt(configEl.dataset.sessionId, 10);
        SESSION_STATE = configEl.dataset.sessionState;
        currentState = SESSION_STATE;

        videoEl = document.getElementById('localVideo');
        overlay = document.getElementById('videoOverlay');
        liveBadge = document.getElementById('liveBadge');
        cameraBtn = document.getElementById('cameraButtonWrap');
        statusPanel = document.getElementById('statusPanel');
        statusIcon = document.getElementById('statusIcon');
        statusIconI = document.getElementById('statusIconI');
        statusTitle = document.getElementById('statusTitle');
        statusDesc = document.getElementById('statusDesc');
        statusLoader = document.getElementById('statusLoader');
        btnStartExam = document.getElementById('btnStartExam');
        stepCamera = document.getElementById('step-camera');
        stepWaiting = document.getElementById('step-waiting');
        stepExam = document.getElementById('step-exam');

        if (SESSION_STATE === 'waiting' || SESSION_STATE === 'authorized') {
            window.startCamera();
        }
        if (SESSION_STATE === 'authorized') updateUIAuthorized();
    });

})();
