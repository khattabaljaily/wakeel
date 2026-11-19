/* Every file field of the app becomes one calm "choose or drop a file" box (2026-11-18). The real <input type=file> stays where it is
   (same name, id, accept, multiple, required, events), only dressed: it covers the box invisibly, so a click, the keyboard and a
   dropped file all work natively and the form posts exactly as before. Texts come from <body data-t-file-*> (translated by Django).
   Opt out with data-wk-plain on the input. */
(function () {
  'use strict';
  var body = document.body;
  var T = {
    choose: body.getAttribute('data-t-file-choose') || 'Choose a file',
    drop: body.getAttribute('data-t-file-drop') || 'or drop it here',
    many: body.getAttribute('data-t-file-many') || 'files chosen',
    none: body.getAttribute('data-t-file-none') || 'No file chosen'
  };

  function size(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return Math.round(bytes / 1024) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function visible(input) {
    return !(input.hidden || input.type === 'hidden' || input.closest('[hidden], .d-none') || input.hasAttribute('data-wk-plain') || input.closest('.input-group') ||
             input.classList.contains('visually-hidden') || getComputedStyle(input).display === 'none');
  }

  function enhance(input) {
    if (input.dataset.wkFile || !visible(input)) return;
    input.dataset.wkFile = '1';
    var box = document.createElement('div');
    box.className = 'wk-file';
    var face = document.createElement('div');
    face.className = 'wk-file__face';
    face.innerHTML = '<i class="bi bi-cloud-arrow-up wk-file__icon" aria-hidden="true"></i>' +
      '<span class="wk-file__text"><strong class="wk-file__choose"></strong> <span class="wk-file__drop"></span></span>' +
      '<span class="wk-file__name"></span>';
    face.querySelector('.wk-file__choose').textContent = T.choose;
    face.querySelector('.wk-file__drop').textContent = T.drop;
    var name = face.querySelector('.wk-file__name');
    input.parentNode.insertBefore(box, input);
    box.appendChild(face);
    box.appendChild(input);
    input.classList.add('wk-file__input');

    function show() {
      var files = input.files || [];
      box.classList.toggle('has-file', files.length > 0);
      if (!files.length) { name.textContent = ''; return; }
      name.textContent = files.length === 1 ? files[0].name + ' · ' + size(files[0].size) : files.length + ' ' + T.many;
    }
    input.addEventListener('change', show);
    ['dragenter', 'dragover'].forEach(function (ev) { input.addEventListener(ev, function () { box.classList.add('is-over'); }); });
    ['dragleave', 'drop', 'blur'].forEach(function (ev) { input.addEventListener(ev, function () { box.classList.remove('is-over'); }); });
    if (input.form) input.form.addEventListener('reset', function () { setTimeout(show, 0); });
    show();
  }

  function run(root) { (root || document).querySelectorAll('input[type=file]').forEach(enhance); }
  run();
  new MutationObserver(function (list) {
    list.forEach(function (m) { m.addedNodes.forEach(function (n) { if (n.nodeType === 1) { if (n.matches && n.matches('input[type=file]')) enhance(n); else run(n); } }); });
  }).observe(document.body, { childList: true, subtree: true });
})();
