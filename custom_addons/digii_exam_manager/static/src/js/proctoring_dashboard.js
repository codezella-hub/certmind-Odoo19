/**
 * Proctor dashboard — LiveKit subscriber.
 *
 * For each active proctoring session, we ask Odoo for a subscribe-only JWT
 * and join that candidate's room. When the candidate publishes its camera
 * track, the SDK fires TrackSubscribed and we attach the resulting
 * <video>/<audio> element into the candidate's card.
 *
 * Polling /exam/proctoring/sessions is kept (low-frequency) for the list
 * of active candidates, authorize/reject workflow and state updates.
 * The live video itself does NOT depend on polling anymore.
 */
(function () {
    "use strict";

    var SURVEY_ID = 0;
    var POLL_INTERVAL = 3000;   // Just to refresh the card list & state
    var pollTimerId = null;

    // sid -> { room, attached:{videoEl, audioEl} }
    var rooms = {};
    var connecting = {};        // sid -> true while the connect promise is in flight

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

    // ---- Global actions (unchanged) ----
    window.authorizeCandidate = function (sessionId) {
        var btn = event.target.closest('button');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i>';
        rpc('/exam/proctoring/authorize', { session_id: sessionId })
        .then(function (result) {
            if (result && result.status === 'ok') updateCardState(sessionId, 'authorized');
        });
    };

    window.openRejectModal = function (sessionId) {
        document.getElementById('rejectSessionId').value = sessionId;
        document.getElementById('rejectReason').value = '';
        document.getElementById('rejectModal').classList.add('visible');
    };
    window.closeRejectModal = function () {
        document.getElementById('rejectModal').classList.remove('visible');
    };

    // ---- Exclude modal ----
    window.openExcludeModal = function (sessionId) {
        document.getElementById('excludeSessionId').value = sessionId;
        document.getElementById('excludeReason').value = '';
        document.getElementById('excludeModal').classList.add('visible');
    };
    window.closeExcludeModal = function () {
        document.getElementById('excludeModal').classList.remove('visible');
    };
    window.confirmExclude = function () {
        var sessionId = parseInt(document.getElementById('excludeSessionId').value, 10);
        var reason = document.getElementById('excludeReason').value;
        var btn = document.querySelector('#excludeModal .confirm');
        btn.disabled = true;
        btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Exclusion...';
        rpc('/exam/proctoring/exclude', { session_id: sessionId, reason: reason })
        .then(function (result) {
            if (result && result.status === 'ok') {
                closeExcludeModal();
                removeCard(sessionId, true);
            } else {
                alert('Erreur : ' + (result && result.error ? result.error : 'Inconnue'));
                btn.disabled = false;
                btn.innerHTML = "<i class='fa fa-ban me-1'></i> Confirmer l'exclusion";
            }
        })
        .catch(function () {
            alert('Erreur de connexion.');
            btn.disabled = false;
            btn.innerHTML = "<i class='fa fa-ban me-1'></i> Confirmer l'exclusion";
        });
    };
    window.confirmReject = function () {
        var sessionId = parseInt(document.getElementById('rejectSessionId').value, 10);
        var reason = document.getElementById('rejectReason').value;
        rpc('/exam/proctoring/reject', { session_id: sessionId, reason: reason })
        .then(function (result) {
            if (result && result.status === 'ok') {
                closeRejectModal();
                removeCard(sessionId, false);
            } else {
                closeRejectModal();
            }
        });
    };

    function disconnectRoom(sid) {
        if (rooms[sid]) {
            try { rooms[sid].room.disconnect(); } catch (e) { /* ignore */ }
            delete rooms[sid];
        }
        delete connecting[sid];
    }

    function removeCard(sid, excluded) {
        var card = document.getElementById('card-' + sid);
        if (card) {
            card.classList.add(excluded ? 'excluded' : 'rejected');
            setTimeout(function () {
                card.remove();
                updateCount();
            }, 800);
        }
        disconnectRoom(sid);
    }

    // ---- LiveKit subscribe ----
    function ensureSubscribed(session) {
        var sid = session.id;
        if (rooms[sid] || connecting[sid]) return;
        if (!lkAvailable()) return;

        connecting[sid] = true;
        rpc('/exam/proctoring/livekit/proctor-token', { session_id: sid })
        .then(function (info) {
            if (!info || info.error) {
                console.warn('[Dashboard] token err session ' + sid + ':', info && info.error);
                delete connecting[sid];
                return;
            }
            var room = new window.LivekitClient.Room({ autoSubscribe: true });
            rooms[sid] = { room: room };

            // TrackSubscribed fires once per incoming track (video, audio)
            room.on(window.LivekitClient.RoomEvent.TrackSubscribed,
                    function (track, publication, participant) {
                console.log('[Dashboard] Subscribed ' + track.kind +
                            ' from ' + participant.identity + ' (session ' + sid + ')');
                attachTrack(sid, track);
            });

            room.on(window.LivekitClient.RoomEvent.TrackUnsubscribed,
                    function (track) {
                track.detach().forEach(function (el) { el.remove(); });
                if (track.kind === 'video') {
                    // Candidate stopped publishing -> show the placeholder
                    showNoFeed(sid, 'Flux interrompu...');
                }
            });

            room.on(window.LivekitClient.RoomEvent.ParticipantDisconnected,
                    function (p) {
                console.log('[Dashboard] Participant left ' + p.identity);
                showNoFeed(sid, 'Reconnexion du flux...');
            });

            room.on(window.LivekitClient.RoomEvent.Reconnecting, function () {
                showNoFeed(sid, 'Reconnexion...');
            });

            room.on(window.LivekitClient.RoomEvent.Disconnected, function (reason) {
                console.warn('[Dashboard] Room disconnected session ' + sid + ':', reason);
                delete rooms[sid];
                delete connecting[sid];
            });

            return room.connect(info.url, info.token).then(function () {
                console.log('[Dashboard] Joined room ' + info.room);
                delete connecting[sid];

                // Candidates may have published BEFORE we joined - iterate
                // existing remote participants and attach their tracks now.
                room.remoteParticipants.forEach(function (p) {
                    p.trackPublications.forEach(function (pub) {
                        if (pub.track) attachTrack(sid, pub.track);
                    });
                });
            });
        })
        .catch(function (err) {
            console.warn('[Dashboard] connect err session ' + sid + ':', err);
            delete connecting[sid];
            delete rooms[sid];
        });
    }

    function attachTrack(sid, track) {
        var videoArea = document.getElementById('video-area-' + sid);
        if (!videoArea) return;

        var el = track.attach();  // returns <video> or <audio>
        if (track.kind === 'video') {
            el.id = 'video-live-' + sid;
            el.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block;';
            // Replace any previous video
            var old = document.getElementById('video-live-' + sid);
            if (old && old !== el) old.remove();
            videoArea.appendChild(el);

            var noFeed = document.getElementById('no-feed-' + sid);
            if (noFeed) noFeed.style.display = 'none';
        } else {
            // Audio: kept attached but we mute it by default so the proctor
            // doesn't get blasted by echo from multiple candidates. Uncomment
            // the line below if you want audio on by default.
            el.muted = true;
            el.style.display = 'none';
            videoArea.appendChild(el);
        }
    }

    function showNoFeed(sid, message) {
        var noFeed = document.getElementById('no-feed-' + sid);
        if (noFeed) {
            noFeed.style.display = 'flex';
            if (message) {
                noFeed.innerHTML = '<i class="fa fa-video-camera"></i> ' + message;
            }
        }
    }

    // ---- Cards (unchanged) ----
    function updateCardState(sessionId, newState) {
        var card = document.getElementById('card-' + sessionId);
        if (!card) return;
        card.dataset.state = newState;
        if (newState === 'authorized') card.classList.add('authorized');
        var badge = document.getElementById('badge-' + sessionId);
        if (badge) {
            badge.className = 'pd-state-badge ' + newState;
            if (newState === 'authorized') badge.textContent = 'Autorise';
            else if (newState === 'in_exam') badge.textContent = 'En examen';
            else badge.textContent = 'En attente';
        }
        var actions = document.getElementById('actions-' + sessionId);
        if (actions) {
            if (newState === 'authorized') {
                actions.innerHTML =
                    '<button class="pd-btn pd-btn-authorize" disabled="disabled">' +
                    '<i class="fa fa-check-circle"></i> Autorise</button>';
            } else if (newState === 'in_exam') {
                actions.innerHTML =
                    '<button class="pd-btn pd-btn-authorize" disabled="disabled" ' +
                    'style="background:rgba(59,130,246,0.15);color:var(--pd-accent);">' +
                    '<i class="fa fa-pencil"></i> En cours d\'examen</button>' +
                    '<button class="pd-btn pd-btn-exclude" data-action="exclude" data-session-id="' + sessionId + '">' +
                    '<i class="fa fa-ban"></i> Exclure</button>';
            }
        }
    }
    function updateCount() {
        var cards = document.querySelectorAll('.pd-card:not(.rejected)');
        var countEl = document.getElementById('sessionCount');
        var emptyEl = document.getElementById('emptyState');
        if (countEl) countEl.textContent = cards.length;
        if (emptyEl) emptyEl.style.display = cards.length === 0 ? 'flex' : 'none';
    }
    function addNewCard(session) {
        var grid = document.getElementById('sessionsGrid');
        if (!grid) return;
        var initial = (session.partner_name || 'X')[0].toUpperCase();
        var card = document.createElement('div');
        card.className = 'pd-card';
        card.id = 'card-' + session.id;
        card.dataset.state = session.state;
        card.innerHTML =
            '<div class="pd-card-header">' +
                '<div class="pd-candidate-info">' +
                    '<div class="pd-avatar">' + initial + '</div>' +
                    '<div>' +
                        '<div class="pd-candidate-name">' + (session.partner_name || 'Candidat') + '</div>' +
                        '<div class="pd-candidate-email">' + (session.partner_email || '') + '</div>' +
                    '</div>' +
                '</div>' +
                '<span class="pd-state-badge waiting" id="badge-' + session.id + '">En attente</span>' +
            '</div>' +
            '<div class="pd-video-area" id="video-area-' + session.id + '">' +
                '<div class="pd-no-feed" id="no-feed-' + session.id + '">' +
                    '<i class="fa fa-video-camera"></i> En attente du flux...' +
                '</div>' +
                '<div class="pd-timestamp" id="ts-' + session.id + '"></div>' +
            '</div>' +
            '<div class="pd-card-actions" id="actions-' + session.id + '">' +
                '<button class="pd-btn pd-btn-authorize" data-action="authorize" data-session-id="' + session.id + '">' +
                    '<i class="fa fa-check"></i> Autoriser</button>' +
                '<button class="pd-btn pd-btn-reject" data-action="reject" data-session-id="' + session.id + '">' +
                    '<i class="fa fa-times"></i> Rejeter</button>' +
            '</div>';
        grid.appendChild(card);
    }

    // ---- Polling for session list + state ----
    function pollSessions() {
        rpc('/exam/proctoring/sessions', { survey_id: SURVEY_ID })
        .then(function (result) {
            if (!result || !result.sessions) return;
            var liveIds = {};
            result.sessions.forEach(function (s) { liveIds[s.id] = true; });

            // Drop cards for sessions that disappeared (rejected/completed/excluded)
            document.querySelectorAll('.pd-card').forEach(function (c) {
                var sid = parseInt(c.id.replace('card-', ''), 10);
                if (!liveIds[sid]) {
                    // Card not in active list anymore - remove silently if not
                    // already animating out
                    if (!c.classList.contains('rejected') && !c.classList.contains('excluded')) {
                        c.remove();
                    }
                    disconnectRoom(sid);
                }
            });

            // Add / update the rest
            var existingIds = {};
            document.querySelectorAll('.pd-card').forEach(function (c) {
                existingIds[parseInt(c.id.replace('card-', ''), 10)] = true;
            });
            result.sessions.forEach(function (s) {
                if (!existingIds[s.id]) addNewCard(s);
                ensureSubscribed(s);
                var card = document.getElementById('card-' + s.id);
                if (card && card.dataset.state !== s.state) updateCardState(s.id, s.state);
            });

            var countEl = document.getElementById('sessionCount');
            var emptyEl = document.getElementById('emptyState');
            if (countEl) countEl.textContent = result.sessions.length;
            if (emptyEl) emptyEl.style.display = result.sessions.length === 0 ? 'flex' : 'none';
        })
        .catch(function () { /* silent */ });
    }

    // ---- Init ----
    document.addEventListener('DOMContentLoaded', function () {
        var configEl = document.getElementById('proctoringConfig');
        if (!configEl) return;
        SURVEY_ID = parseInt(configEl.dataset.surveyId, 10);
        console.log('[Dashboard] Init survey_id=' + SURVEY_ID);

        if (!lkAvailable()) {
            console.error('[Dashboard] LivekitClient global missing - CDN not loaded?');
        }

        // Event delegation for card action buttons (safer than inline onclick)
        var grid = document.getElementById('sessionsGrid');
        if (grid) {
            grid.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-action]');
                if (!btn) return;
                var action = btn.dataset.action;
                var sid = parseInt(btn.dataset.sessionId, 10);
                if (!sid) return;
                if (action === 'authorize') authorizeCandidate(sid);
                else if (action === 'reject')  openRejectModal(sid);
                else if (action === 'exclude') openExcludeModal(sid);
            });
        }

        pollSessions();
        pollTimerId = setInterval(pollSessions, POLL_INTERVAL);

        window.addEventListener('beforeunload', function () {
            Object.keys(rooms).forEach(function (sid) { disconnectRoom(sid); });
        });

        // Listen for real-time exam_completed events via Odoo longpolling bus.
        // This removes the card immediately without waiting for the next poll.
        if (window.odoo && window.odoo.services && window.odoo.services['bus.service']) {
            var bus = window.odoo.services['bus.service'];
            var channel = 'exam_proctoring_dashboard_' + SURVEY_ID;
            bus.subscribe(channel, function (payload) {
                if (payload && payload.type === 'exam_completed' && payload.session_id) {
                    var sid = payload.session_id;
                    console.log('[Dashboard] exam_completed received for session', sid,
                        payload.excluded ? '(excluded)' : '(submitted)');
                    removeCard(sid, Boolean(payload.excluded));
                }
            });
            bus.start();
        }
    });

})();
