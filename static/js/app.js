/* Wakeel — shared front-end helpers (page spinner, AJAX, job polling, toasts). */

// ---------- Global page spinner (as in enjazpms) ----------
// Reference-counted: every show() needs a hide(). It comes up on page navigation
// (links, form submits) and on AJAX calls, and a 15 s safety timer means it can
// never get stuck. AJAX calls wait 150 ms before showing it, so quick ones don't flash.
var WkSpinner = (function () {
    var _el = null, _count = 0, _safety = null, _delay = null;

    function _getEl() { return _el || (_el = document.getElementById('wkSpinner')); }
    function _doShow() { var s = _getEl(); if (s) s.classList.add('active'); }
    function _doHide() { clearTimeout(_delay); _delay = null; var s = _getEl(); if (s) s.classList.remove('active'); }

    function show(delayed) {
        _count++;
        clearTimeout(_safety);
        _safety = setTimeout(forceHide, 15000);
        if (delayed) { if (!_delay) _delay = setTimeout(_doShow, 150); } else _doShow();
    }
    function hide() {
        _count = Math.max(0, _count - 1);
        if (_count === 0) { clearTimeout(_safety); _doHide(); }
    }
    function forceHide() { clearTimeout(_safety); _count = 0; _doHide(); }

    return { show: show, hide: hide, forceHide: forceHide };
})();

// pageshow fires on normal loads and on back/forward (bfcache) restores, so the
// spinner never stays up after navigating back.
window.addEventListener('pageshow', function () { WkSpinner.forceHide(); });
window.addEventListener('load', function () { WkSpinner.forceHide(); });

// Navigation links: skip in-page anchors, new tabs, Bootstrap toggles and downloads.
document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var link = e.target.closest('a[href]');
    if (!link) return;
    var href = link.getAttribute('href') || '';
    if (!href || /^(#|javascript:|mailto:|tel:|whatsapp:)/i.test(href)) return;
    if (link.target === '_blank' || link.hasAttribute('download') || link.hasAttribute('data-no-spinner')) return;
    if (link.hasAttribute('data-bs-toggle') || link.hasAttribute('data-bs-dismiss')) return;
    if (/\/(download|export)\/|\.(txt|csv|png|jpe?g|pdf|zip)(\?|$)/i.test(href)) return;  // files: the page stays put
    if (link.origin && link.origin !== location.origin) return;
    WkSpinner.show();
});

// Forms that navigate (AJAX forms call preventDefault, so they're skipped).
document.addEventListener('submit', function (e) {
    if (e.defaultPrevented || e.target.target === '_blank' || e.target.hasAttribute('data-no-spinner')) return;
    WkSpinner.show();
});

var Wakeel = (function () {
    function csrf() {
        var m = document.cookie.match(/(?:^|; )wakeel_csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    // JSON API call. Resolves with the parsed body; rejects with {status, data}.
    // The page spinner shows while it runs, unless opts.silent (background polling,
    // or long calls that show their own progress).
    function api(url, method, data, opts_) {
        var silent = !!(opts_ && opts_.silent);
        if (!silent) WkSpinner.show(true);
        var opts = { method: method || 'GET', headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' };
        if (data instanceof FormData) {
            opts.body = data;
        } else if (data !== undefined) {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(data);
        }
        return fetch(url, opts).then(function (res) {
            return res.json().catch(function () { return {}; }).then(function (body) {
                if (!res.ok) throw { status: res.status, data: body };
                return body;
            });
        }).finally(function () { if (!silent) WkSpinner.hide(); });
    }

    function errorText(err, fallback) {
        var d = (err && err.data) || {};
        return d.error || d.detail || fallback || 'حدث خطأ. حاول مرة أخرى.';
    }

    function toast(message, type) {
        var box = document.getElementById('wkToasts');
        if (!box) return;
        var el = document.createElement('div');
        el.className = 'wk-toast ' + (type || '');
        var icon = type === 'error' ? 'bi-exclamation-circle' : 'bi-check-circle-fill';
        el.innerHTML = '<i class="bi ' + icon + '"></i><span></span>';
        el.querySelector('span').textContent = message;
        box.appendChild(el);
        setTimeout(function () { el.style.transition = 'opacity .3s'; el.style.opacity = '0'; }, 3800);
        setTimeout(function () { el.remove(); }, 4200);
    }

    // Poll a background job until it finishes. onProgress(job) is called on every tick.
    function pollJob(id, onProgress, interval) {
        return new Promise(function (resolve, reject) {
            var waited = 0;
            function tick() {
                api('/api/jobs/' + id + '/', 'GET', undefined, { silent: true }).then(function (job) {
                    if (onProgress) onProgress(job);
                    if (job.finished) {
                        return job.status === 'done' ? resolve(job) : reject(job);
                    }
                    waited += 1;
                    setTimeout(tick, waited > 30 ? 4000 : (interval || 1500));
                }).catch(function () { setTimeout(tick, 4000); });
            }
            tick();
        });
    }

    function debounce(fn, ms) {
        var t;
        return function () {
            var args = arguments, self = this;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(self, args); }, ms);
        };
    }

    function copy(text) {
        return navigator.clipboard.writeText(text).then(function () { toast('تم النسخ'); });
    }

    return { spinner: WkSpinner, api: api, csrf: csrf, toast: toast, pollJob: pollJob, debounce: debounce, errorText: errorText, copy: copy };
})();

// Styled confirmation dialog (replaces window.confirm / window.prompt).
// Wakeel.confirm({title, message, okText, tone: 'danger'|'primary', icon,
//                 requireText, input: {label, placeholder, multiline, required}})
// resolves with true (or the typed text when there's an input), or null when cancelled.
Wakeel.confirm = (function () {
    var el, modal, pending = null;

    function setup() {
        el = document.getElementById('wkConfirm');
        modal = bootstrap.Modal.getOrCreateInstance(el);
        el.addEventListener('hidden.bs.modal', function () { finish(null); });
        el.querySelector('.wk-modal__ok').addEventListener('click', function () { finish(value()); });
        el.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && e.target.id === 'wkConfirmInput' && !el.querySelector('.wk-modal__ok').disabled) {
                e.preventDefault(); finish(value());
            }
        });
    }
    function field() {
        var multi = !el.querySelector('#wkConfirmText').classList.contains('d-none');
        return el.querySelector(multi ? '#wkConfirmText' : '#wkConfirmInput');
    }
    function value() {
        return el.querySelector('.wk-modal__field').classList.contains('d-none') ? true : field().value.trim();
    }
    function finish(result) {
        if (!pending) return;
        var resolve = pending;
        pending = null;
        modal.hide();
        resolve(result);
    }

    return function (opts) {
        if (!el) setup();
        if (pending) finish(null);
        opts = opts || {};
        var tone = opts.tone || 'danger';
        el.classList.remove('danger', 'primary');
        el.classList.add(tone);
        el.querySelector('.wk-modal__icon i').className = 'bi ' + (opts.icon || (tone === 'danger' ? 'bi-trash3' : 'bi-question-lg'));
        el.querySelector('.wk-modal__title').textContent = opts.title || 'هل أنت متأكد؟';
        el.querySelector('.wk-modal__msg').textContent = opts.message || '';
        el.querySelector('.wk-modal__msg').classList.toggle('d-none', !opts.message);
        var ok = el.querySelector('.wk-modal__ok');
        ok.textContent = opts.okText || (tone === 'danger' ? 'حذف' : 'تأكيد');

        var box = el.querySelector('.wk-modal__field'), input = el.querySelector('#wkConfirmInput'), text = el.querySelector('#wkConfirmText');
        var wantsInput = !!(opts.requireText || opts.input);
        box.classList.toggle('d-none', !wantsInput);
        ok.disabled = false;
        if (wantsInput) {
            var multi = !!(opts.input && opts.input.multiline);
            input.classList.toggle('d-none', multi);
            text.classList.toggle('d-none', !multi);
            var f = multi ? text : input, label = box.querySelector('label');
            f.value = '';
            f.placeholder = (opts.input && opts.input.placeholder) || opts.requireText || '';
            label.setAttribute('for', f.id);
            if (opts.requireText) {
                label.innerHTML = 'للتأكيد، اكتب <strong></strong>';
                label.querySelector('strong').textContent = opts.requireText;
            } else {
                label.textContent = (opts.input && opts.input.label) || '';
            }
            var check = function () {
                ok.disabled = opts.requireText ? f.value.trim() !== opts.requireText.trim()
                                               : !!(opts.input.required && !f.value.trim());
            };
            f.oninput = check;
            check();
        }
        el.addEventListener('shown.bs.modal', function focus() {
            el.removeEventListener('shown.bs.modal', focus);
            (wantsInput ? field() : el.querySelector('[data-bs-dismiss]')).focus();
        });
        return new Promise(function (resolve) { pending = resolve; modal.show(); });
    };
})();

// Buttons/links with data-confirm open the dialog first. Optional attributes:
// data-confirm-title, data-confirm-ok, data-confirm-tone (danger|primary),
// data-confirm-require (text to type) + data-confirm-field (form input that receives it).
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-confirm]');
    if (!btn) return;
    if (btn.dataset.confirmed) { delete btn.dataset.confirmed; return; }
    e.preventDefault();
    e.stopPropagation();
    Wakeel.confirm({
        title: btn.dataset.confirmTitle,
        message: btn.dataset.confirm,
        okText: btn.dataset.confirmOk,
        tone: btn.dataset.confirmTone,
        requireText: btn.dataset.confirmRequire,
    }).then(function (result) {
        if (result === null) return;
        if (btn.dataset.confirmField && btn.form) btn.form.elements[btn.dataset.confirmField].value = result;
        btn.dataset.confirmed = '1';
        if (btn.form && btn.type !== 'button') btn.form.requestSubmit(btn);
        else btn.click();
    });
}, true);

// Copy buttons: data-copy-target="#id" copies that element's value/text.
document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-copy-target]');
    if (!btn) return;
    var src = document.querySelector(btn.getAttribute('data-copy-target'));
    if (src) Wakeel.copy(src.value !== undefined ? src.value : src.textContent);
});

// Bulk actions on post grids: a [data-bulk] bar plus .wk-post__select checkboxes on the cards.
document.addEventListener('DOMContentLoaded', function () {
    var bar = document.querySelector('[data-bulk]');
    if (!bar) return;
    var boxes = document.querySelectorAll('.wk-post__select'), all = bar.querySelector('[data-bulk-all]');
    var buttons = bar.querySelectorAll('[data-bulk-action]');
    function selected() { return Array.prototype.filter.call(boxes, function (b) { return b.checked; }).map(function (b) { return b.value; }); }
    function refresh() {
        var n = selected().length;
        boxes.forEach(function (b) { b.closest('.wk-post').classList.toggle('selected', b.checked); });
        buttons.forEach(function (btn) { btn.disabled = !n; btn.querySelector('.n').textContent = n ? '(' + n + ')' : ''; });
    }
    boxes.forEach(function (b) { b.addEventListener('change', refresh); });
    all.addEventListener('change', function () { boxes.forEach(function (b) { b.checked = all.checked; }); refresh(); });
    buttons.forEach(function (btn) {
        btn.addEventListener('click', function () {
            var ids = selected(), req;
            if (btn.dataset.bulkAction === 'delete') {
                req = Wakeel.confirm({
                    title: 'حذف ' + ids.length + ' منشوراً؟',
                    message: 'ستُحذف المنشورات المحددة وتصاميمها نهائياً، ولا يمكن التراجع عن ذلك.',
                    okText: 'حذف المنشورات',
                }).then(function (ok) {
                    if (ok === null) throw null;
                    return Wakeel.api('/api/posts/bulk-delete/', 'POST', { ids: ids });
                }).then(function (r) { return 'تم حذف ' + r.deleted + ' منشوراً'; });
            } else {
                req = Wakeel.api('/api/posts/bulk-status/', 'POST', { ids: ids, status: 'approved' }).then(function (r) { return 'تم اعتماد ' + r.updated + ' منشوراً'; });
            }
            req.then(function (msg) { Wakeel.toast(msg); setTimeout(function () { location.reload(); }, 700); })
               .catch(function (e) { if (e !== null) Wakeel.toast(Wakeel.errorText(e), 'error'); });
        });
    });
});

// jQuery AJAX (DataTables) shares the page spinner, as in enjazpms. Requests made
// with `global: false` stay silent.
// jQuery is loaded after this file on table pages, so hook in once the page is parsed.
document.addEventListener('DOMContentLoaded', function () {
    if (!window.jQuery) return;
    jQuery(document)
        .on('ajaxSend', function () { WkSpinner.show(true); })
        .on('ajaxComplete', function () { WkSpinner.hide(); });
});

// ---------- Installable app (PWA) and push notifications ----------
Wakeel.pwa = (function () {
    var standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
    var ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    var deferredPrompt = null;
    var reg = null;

    function urlKey(b64) {
        var pad = '='.repeat((4 - b64.length % 4) % 4), raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
        return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
    }
    function pushSupported() { return !!(reg && 'PushManager' in window && 'Notification' in window); }
    function subscription() { return pushSupported() ? reg.pushManager.getSubscription() : Promise.resolve(null); }

    // Ask for permission (must follow a tap), subscribe, and register the device with the server.
    function enablePush() {
        var bar = document.getElementById('wkAppBar'), key = bar && bar.dataset.vapid;
        if (!pushSupported() || !key) return Promise.reject({ data: { error: ios && !standalone
            ? 'على الآيفون، ثبّت التطبيق على الشاشة الرئيسية أولاً ثم فعّل الإشعارات منه.'
            : 'هذا المتصفح لا يدعم الإشعارات.' } });
        return Notification.requestPermission().then(function (perm) {
            if (perm !== 'granted') throw { data: { error: 'لم يُسمح بالإشعارات. يمكنك تفعيلها من إعدادات المتصفح.' } };
            return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlKey(key) });
        }).then(function (sub) {
            return Wakeel.api('/notifications/push/subscribe/', 'POST', sub.toJSON(), { silent: true });
        });
    }
    function disablePush() {
        return subscription().then(function (sub) {
            if (!sub) return;
            return Wakeel.api('/notifications/push/unsubscribe/', 'POST', { endpoint: sub.endpoint }, { silent: true })
                .then(function () { return sub.unsubscribe(); });
        });
    }

    // A small bar offering to install the app, or (once installed) to turn on notifications.
    function snoozed(what) { try { return Date.now() < +localStorage.getItem('wkSnooze.' + what); } catch (e) { return false; } }
    function snooze(what) { try { localStorage.setItem('wkSnooze.' + what, Date.now() + 14 * 864e5); } catch (e) {} }
    function offer(what, title, text, button, action) {
        var bar = document.getElementById('wkAppBar');
        if (!bar || snoozed(what)) return;
        bar.querySelector('strong').textContent = title;
        bar.querySelector('span').textContent = text;
        var go = bar.querySelector('.wk-appbar__go');
        go.textContent = button;
        go.hidden = !action;
        go.onclick = function () { action().then(function () { bar.hidden = true; }, function (e) { Wakeel.toast(Wakeel.errorText(e), 'error'); }); };
        bar.querySelector('.wk-appbar__close').onclick = function () { bar.hidden = true; snooze(what); };
        bar.hidden = false;
    }
    function maybeOfferPush() {
        if (!standalone || !pushSupported() || Notification.permission !== 'default') return;
        subscription().then(function (sub) {
            if (!sub) offer('push', 'فعّل الإشعارات', 'ليصلك جديد الخطط والمراجعات على هاتفك.', 'تفعيل', function () {
                return enablePush().then(function () { Wakeel.toast('ستصلك الإشعارات على هذا الجهاز'); });
            });
        });
    }

    window.addEventListener('beforeinstallprompt', function (e) {
        e.preventDefault();
        deferredPrompt = e;
        if (window.innerWidth < 992) offer('install', 'ثبّت وكيل على هاتفك', 'افتحه كتطبيق بضغطة واحدة، وتصلك إشعاراته.', 'تثبيت', function () {
            deferredPrompt.prompt();
            return deferredPrompt.userChoice.then(function () { deferredPrompt = null; });
        });
    });

    if ('serviceWorker' in navigator) {
        window.addEventListener('load', function () {
            navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(function (r) {
                reg = r;
                maybeOfferPush();
                document.dispatchEvent(new CustomEvent('wakeel:sw-ready'));
            }).catch(function () {});
            // iPhone Safari has no install prompt: explain the Share > Add to Home Screen way.
            if (ios && !standalone && window.innerWidth < 992) {
                offer('install-ios', 'ثبّت وكيل على الآيفون', 'اضغط زر المشاركة ثم «إضافة إلى الشاشة الرئيسية».', '', null);
            }
        });
    }

    return { enablePush: enablePush, disablePush: disablePush, subscription: subscription, pushSupported: pushSupported,
             standalone: standalone, ios: ios };
})();
