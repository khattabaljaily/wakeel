/* Wakeel — shared front-end helpers (AJAX, job polling, toasts). */
var Wakeel = (function () {
    function csrf() {
        var m = document.cookie.match(/(?:^|; )wakeel_csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    // JSON API call. Resolves with the parsed body; rejects with {status, data}.
    function api(url, method, data) {
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
        });
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
                api('/api/jobs/' + id + '/').then(function (job) {
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

    return { api: api, csrf: csrf, toast: toast, pollJob: pollJob, debounce: debounce, errorText: errorText, copy: copy };
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
