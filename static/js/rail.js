/* Wakeel — sidebar groups: fold/open (remembered), collapse to icons (remembered), pop-out of a group when collapsed.
   Ported from MyDocHub's app.js. The group of the page being shown is opened by the server. */
(function () {
    var root = document.documentElement;
    var grpKey = 'wkRailGroups', opened = [];
    try { opened = JSON.parse(localStorage.getItem(grpKey) || '[]'); } catch (err) {}

    function closeFly() {
        document.querySelectorAll('.rail-grp.fly').forEach(function (g) {
            g.classList.remove('fly');
            var h = g.querySelector('[data-grp-toggle]');
            if (h) h.setAttribute('aria-expanded', String(g.classList.contains('open')));
        });
    }
    function wide() { return window.innerWidth >= 992; }

    document.querySelectorAll('.rail-grp[data-grp]').forEach(function (g) {
        var h = g.querySelector('[data-grp-toggle]');
        if (h && opened.indexOf(g.getAttribute('data-grp')) > -1) { g.classList.add('open'); h.setAttribute('aria-expanded', 'true'); }
    });

    document.addEventListener('click', function (e) {
        var head = e.target.closest && e.target.closest('[data-grp-toggle]');
        if (!head) {
            if (e.target.closest && !e.target.closest('.rail-grp.fly') && !e.target.closest('[data-side-toggle]')) closeFly();
            if (e.target.closest && e.target.closest('[data-side-toggle]')) {
                closeFly();
                var collapsed = root.classList.toggle('side-collapsed');
                try { localStorage.setItem('wkSide', collapsed ? 'collapsed' : 'open'); } catch (err) {}
                e.target.closest('[data-side-toggle]').setAttribute('aria-expanded', String(!collapsed));
            }
            return;
        }
        var g = head.closest('.rail-grp'), name = g.getAttribute('data-grp');
        if (root.classList.contains('side-collapsed') && wide()) {
            var show = !g.classList.contains('fly');
            closeFly();
            if (show) {
                g.classList.add('fly');
                head.setAttribute('aria-expanded', 'true');
                var body = g.querySelector('.rail-grp-body'), at = head.getBoundingClientRect();
                body.style.top = Math.max(8, Math.min(at.top - 6, window.innerHeight - body.offsetHeight - 8)) + 'px';
            }
            return;
        }
        var open = g.classList.toggle('open');
        head.setAttribute('aria-expanded', String(open));
        opened = opened.filter(function (n) { return n !== name; });
        if (open) opened.push(name);
        try { localStorage.setItem(grpKey, JSON.stringify(opened)); } catch (err) {}
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeFly(); });

    var t = document.querySelector('[data-side-toggle]');
    if (t) t.setAttribute('aria-expanded', String(!root.classList.contains('side-collapsed')));
})();
