/* The compose page and the compose window: recipient chips, the formatting bar of the editor, attachments, and the preview. No library. */
(function () {
  // Template previews are pages 640 px wide, shown small: each one is scaled to the width of its box.
  function fitThumbs(root) {
    [].forEach.call((root || document).querySelectorAll('.tpl-thumb iframe, .tpl-big iframe'), function (frame) {
      var box = frame.parentElement, w = box.clientWidth;
      if (!w) return;
      var scale = w / 640;
      frame.style.transform = 'scale(' + scale.toFixed(3) + ')';
      frame.style.height = Math.ceil(box.clientHeight / scale) + 'px';
    });
  }
  window.addEventListener('resize', function () { fitThumbs(); });
  document.addEventListener('DOMContentLoaded', function () { fitThumbs(); });
  window.addEventListener('load', function () { fitThumbs(); });
  var EMAIL = /^[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]{2,}$/;

  function init(form) {
  // ── recipients as chips ──
  function chips(box) {
    var hidden = document.getElementById('f-' + box.getAttribute('data-target'));
    var list = box.querySelector('.chip-list'), input = box.querySelector('.chip-input');
    var items = [];
    function sync() { hidden.value = items.join(', '); }
    function draw() {
      list.textContent = '';
      items.forEach(function (address, i) {
        var chip = document.createElement('span'); chip.className = 'chip' + (EMAIL.test(address) ? '' : ' bad');
        var text = document.createElement('bdi'); text.textContent = address; text.setAttribute('dir', 'ltr');
        var x = document.createElement('button'); x.type = 'button'; x.className = 'chip-x'; x.textContent = '×'; x.setAttribute('aria-label', '×');
        x.addEventListener('click', function () { items.splice(i, 1); draw(); sync(); input.focus(); });
        chip.appendChild(text); chip.appendChild(x); list.appendChild(chip);
      });
      sync();
    }
    function take(raw) {
      raw.split(/[,;\s]+/).forEach(function (part) {
        part = part.trim().replace(/^<|>$/g, '');
        if (part && items.indexOf(part.toLowerCase()) < 0) items.push(part.toLowerCase());
      });
      draw();
    }
    take(hidden.value);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ',' || e.key === ';' || e.key === ' ') {
        if (input.value.trim()) { e.preventDefault(); take(input.value); input.value = ''; } else if (e.key === 'Enter') e.preventDefault();
      } else if (e.key === 'Backspace' && !input.value && items.length) { items.pop(); draw(); }
    });
    input.addEventListener('paste', function (e) {
      var text = (e.clipboardData || window.clipboardData).getData('text');
      if (/[,;\s]/.test(text.trim())) { e.preventDefault(); take(text); }
    });
    input.addEventListener('blur', function () { if (input.value.trim()) { take(input.value); input.value = ''; } });
    box.addEventListener('click', function () { input.focus(); });
    box.flush = function () { if (input.value.trim()) { take(input.value); input.value = ''; } };
  }
  var boxes = [].slice.call(form.querySelectorAll('[data-chips]'));
  boxes.forEach(chips);
  [].forEach.call(form.querySelectorAll('[data-show]'), function (b) {
    b.addEventListener('click', function () {
      var row = document.getElementById(b.getAttribute('data-show')); row.hidden = false; row.querySelector('input[type=text]').focus(); b.hidden = true;
    });
    if (!document.getElementById(b.getAttribute('data-show')).hidden) b.hidden = true;
  });

  // ── the editor ──
  var rte = document.getElementById('rte'), bar = form.querySelector('.rte-bar');
  var saved = null;
  function remember() { var s = getSelection(); if (s.rangeCount && rte.contains(s.anchorNode)) saved = s.getRangeAt(0).cloneRange(); }
  function restore() { if (saved) { var s = getSelection(); s.removeAllRanges(); s.addRange(saved); } }
  document.addEventListener('selectionchange', remember);
  function refresh() {
    [].forEach.call(bar.querySelectorAll('[data-cmd]'), function (b) {
      var cmd = b.getAttribute('data-cmd');
      if (['bold', 'italic', 'underline', 'insertUnorderedList', 'insertOrderedList'].indexOf(cmd) >= 0) {
        var on = false; try { on = document.queryCommandState(cmd); } catch (e) {}
        b.classList.toggle('on', on);
      }
    });
  }
  bar.addEventListener('mousedown', function (e) { if (e.target.closest('button')) e.preventDefault(); });   // keep the selection in the text
  bar.addEventListener('click', function (e) {
    var b = e.target.closest('button'); if (!b) return;
    rte.focus(); restore();
    if (b.hasAttribute('data-cmd')) { document.execCommand(b.getAttribute('data-cmd'), false, null); refresh(); }
    else if (b.hasAttribute('data-dir')) {
      var node = getSelection().anchorNode; node = node && (node.nodeType === 3 ? node.parentNode : node);
      var block = node && node.closest('p,div,li,blockquote,h1,h2,h3'); if (block === rte || !block) block = null;
      if (block) { block.setAttribute('dir', b.getAttribute('data-dir')); block.style.textAlign = b.getAttribute('data-dir') === 'rtl' ? 'right' : 'left'; }
      else { rte.setAttribute('dir', b.getAttribute('data-dir')); }
    }
  });
  var pop = bar.querySelector('.link-pop'), urlInput = pop.querySelector('input');
  bar.querySelector('[data-link]').addEventListener('click', function () { pop.hidden = !pop.hidden; if (!pop.hidden) urlInput.focus(); });
  pop.querySelector('[data-link-ok]').addEventListener('click', function () {
    var url = urlInput.value.trim();
    if (/^(https?:\/\/|mailto:|tel:)/i.test(url) === false && url) url = 'https://' + url;
    rte.focus(); restore();
    if (url) document.execCommand('createLink', false, url);
    urlInput.value = ''; pop.hidden = true;
  });
  urlInput.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); pop.querySelector('[data-link-ok]').click(); } });
  rte.addEventListener('keyup', refresh); rte.addEventListener('mouseup', refresh);
  rte.addEventListener('paste', function (e) {            // pasted text comes in clean: no fonts, colours or page junk from other programs
    e.preventDefault();
    var text = (e.clipboardData || window.clipboardData).getData('text/plain');
    document.execCommand('insertText', false, text);
  });
  rte.addEventListener('input', function () { if (!rte.textContent.trim() && !rte.querySelector('li,blockquote')) rte.classList.add('empty'); else rte.classList.remove('empty'); });
  rte.dispatchEvent(new Event('input'));
  if (!form.querySelector('#f-to').value) form.querySelector('#to-input').focus(); else { rte.focus(); var r = document.createRange(); r.setStart(rte, 0); r.collapse(true); var s = getSelection(); s.removeAllRanges(); s.addRange(r); }

  // ── attachments ──
  var fileInput = document.getElementById('files'), drop = document.getElementById('drop'), listEl = document.getElementById('file-list');
  var errEl = document.getElementById('attach-error');
  var maxFiles = parseInt(form.getAttribute('data-max-files'), 10), maxBytes = parseInt(form.getAttribute('data-max-mb'), 10) * 1024 * 1024;
  var files = [];
  function size(n) { return n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
  function draw() {
    listEl.textContent = '';
    var total = 0;
    files.forEach(function (f, i) {
      total += f.size;
      var li = document.createElement('li'), name = document.createElement('bdi'), sz = document.createElement('span'), x = document.createElement('button');
      name.textContent = f.name; sz.className = 'muted num'; sz.textContent = size(f.size);
      x.type = 'button'; x.className = 'chip-x'; x.textContent = '×'; x.setAttribute('aria-label', '×');
      x.addEventListener('click', function () { files.splice(i, 1); draw(); });
      li.appendChild(name); li.appendChild(sz); li.appendChild(x); listEl.appendChild(li);
    });
    var dt = new DataTransfer(); files.forEach(function (f) { dt.items.add(f); }); fileInput.files = dt.files;
    var bad = files.length > maxFiles || total > maxBytes;
    errEl.hidden = !bad; errEl.textContent = bad ? (files.length > maxFiles ? 'Max ' + maxFiles : 'Max ' + (maxBytes / 1048576) + ' MB') : '';
    form.classList.toggle('attach-bad', bad);
  }
  function add(list) {
    [].forEach.call(list, function (f) { if (!files.some(function (g) { return g.name === f.name && g.size === f.size; })) files.push(f); });
    draw();
  }
  drop.addEventListener('click', function () { fileInput.click(); });
  drop.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } });
  fileInput.addEventListener('change', function () { add(fileInput.files); });
  ['dragenter', 'dragover'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
  ['dragleave', 'drop'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
  drop.addEventListener('drop', function (e) { add(e.dataTransfer.files); });

  // ── things of the workspace: issued documents (as PDF) and papers of the library ──
  var pickBtn = document.getElementById('pick-btn'), pickDialog = document.getElementById('picker-dialog'), pickBody = document.getElementById('picker-body');
  var pickedList = document.getElementById('picked-list'), pickQ = document.getElementById('picker-q'), pickTimer = null;
  function pickLoad() {
    fetch(pickBtn.getAttribute('data-url') + '?q=' + encodeURIComponent(pickQ.value), { credentials: 'same-origin' })
      .then(function (r) { return r.text(); }).then(function (html) {
        pickBody.innerHTML = html;
        [].forEach.call(pickBody.querySelectorAll('input[type=checkbox]'), function (c) {
          if (pickedList.querySelector('input[value="' + c.value + '"][data-kind="' + c.getAttribute('data-kind') + '"]')) c.checked = true;
        });
      });
  }
  if (pickBtn) {
    pickBtn.addEventListener('click', function () { pickQ.value = ''; pickLoad(); if (pickDialog.showModal) pickDialog.showModal(); else pickDialog.setAttribute('open', ''); pickQ.focus(); });
    pickQ.addEventListener('input', function () { clearTimeout(pickTimer); pickTimer = setTimeout(pickLoad, 250); });
    document.getElementById('picker-close').addEventListener('click', function () { pickDialog.close(); });
    document.getElementById('picker-add').addEventListener('click', function () {
      [].forEach.call(pickBody.querySelectorAll('input[type=checkbox]'), function (c) {
        var kind = c.getAttribute('data-kind'), name = kind === 'doc' ? 'doc' : 'rec';
        var existing = pickedList.querySelector('input[name="' + name + '"][value="' + c.value + '"]');
        if (c.checked && !existing) {
          var li = document.createElement('li'), t = document.createElement('bdi'), x = document.createElement('button'), h = document.createElement('input');
          h.type = 'hidden'; h.name = name; h.value = c.value; h.setAttribute('data-kind', kind);
          t.textContent = (kind === 'doc' ? 'PDF · ' : '') + c.getAttribute('data-title');
          x.type = 'button'; x.className = 'chip-x'; x.textContent = '×'; x.setAttribute('aria-label', '×');
          x.addEventListener('click', function () { li.remove(); touched = true; });
          li.appendChild(t); li.appendChild(x); li.appendChild(h); pickedList.appendChild(li);
        } else if (!c.checked && existing) existing.closest('li').remove();
      });
      touched = true; pickDialog.close();
    });
  }

  // ── sending and previewing ──
  function collect() { boxes.forEach(function (b) { b.flush(); }); document.getElementById('body-html').value = rte.innerHTML; }
  var touched = false;
  form.addEventListener('input', function () { touched = true; });
  fileInput.addEventListener('change', function () { touched = true; });
  drop.addEventListener('drop', function () { touched = true; });
  var modal = form.getAttribute('data-modal') === '1', errBox = document.getElementById('compose-error');
  form.addEventListener('submit', function (e) {
    collect();
    if (form.classList.contains('attach-bad')) { e.preventDefault(); errEl.scrollIntoView({ block: 'center' }); return; }
    if (!modal) return;
    e.preventDefault();
    var send = form.querySelector('button[type=submit]');
    send.disabled = true; send.classList.add('is-loading'); errBox.hidden = true;
    fetch(form.action, { method: 'POST', body: new FormData(form), credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.ok) { window.location.reload(); return; }
        errBox.textContent = data.error; errBox.hidden = false; errBox.scrollIntoView({ block: 'nearest' });
        send.disabled = false; send.classList.remove('is-loading');
      })
      .catch(function () { errBox.textContent = '⚠'; errBox.hidden = false; send.disabled = false; send.classList.remove('is-loading'); });
  });
  var closeBtn = document.getElementById('compose-close');
  if (closeBtn) {
    var armed = null, label = closeBtn.getAttribute('data-discard'), icon = closeBtn.innerHTML;
    closeBtn.addEventListener('click', function () {
      var dirty = touched;
      if (dirty && !armed) {                       // a first click asks (on the button itself, no browser dialog); a second one discards
        closeBtn.textContent = label; closeBtn.classList.add('btn-danger');
        armed = setTimeout(function () { armed = null; closeBtn.innerHTML = icon; closeBtn.classList.remove('btn-danger'); }, 3500);
        return;
      }
      clearTimeout(armed); window.MailCompose.close();
    });
  }
  var dialog = document.getElementById('preview-dialog'), frame = document.getElementById('preview-frame');
  document.getElementById('preview-btn').addEventListener('click', function () {
    collect();
    var data = new FormData();
    ['subject', 'body_html'].forEach(function (n) { data.append(n, form.elements[n].value); });
    var tpl = form.querySelector('input[name=template]:checked'); data.append('template', tpl ? tpl.value : '');
    data.append('csrfmiddlewaretoken', form.querySelector('[name=csrfmiddlewaretoken]').value);
    fetch(form.getAttribute('data-preview-url'), { method: 'POST', body: data, credentials: 'same-origin' })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        frame.srcdoc = html;
        document.getElementById('preview-sub').textContent = form.elements.subject.value;
        if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
      });
  });
  frame.addEventListener('load', function () { try { frame.style.height = Math.max(420, frame.contentDocument.documentElement.scrollHeight + 16) + 'px'; } catch (e) {} });
  document.getElementById('preview-close').addEventListener('click', function () { dialog.close ? dialog.close() : dialog.removeAttribute('open'); });
  dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });
  return { rte: rte };
  }

  // ── the compose window over the mailbox ──
  var holder = document.getElementById('compose-dialog'), slot = document.getElementById('compose-slot');
  window.MailCompose = {
    close: function () { if (holder.close) holder.close(); else holder.removeAttribute('open'); slot.textContent = ''; },
  };
  if (holder) {
    document.addEventListener('click', function (e) {
      var link = e.target.closest('a[data-compose]');
      if (!link || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
      e.preventDefault();
      var url = link.getAttribute('href'); url += (url.indexOf('?') < 0 ? '?' : '&') + 'modal=1';
      fetch(url, { credentials: 'same-origin' }).then(function (r) { return r.text(); }).then(function (html) {
        slot.innerHTML = html;
        if (holder.showModal) holder.showModal(); else holder.setAttribute('open', '');
        init(slot.querySelector('#compose-form'));
        fitThumbs(slot);
      });
    });
    holder.addEventListener('cancel', function (e) { e.preventDefault(); var b = document.getElementById('compose-close'); if (b) b.click(); });
    holder.addEventListener('mousedown', function (e) { if (e.target === holder) { var b = document.getElementById('compose-close'); if (b) b.click(); } });
  }
  var pageForm = document.getElementById('compose-form');
  if (pageForm && !holder) init(pageForm);
})();
