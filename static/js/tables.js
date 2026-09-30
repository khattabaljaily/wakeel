/* Wakeel — DataTables for every table: a table on desktop, cards on phones (as in enjazpms).
 *
 * <table data-wk-table="client|server"> is set up on load (markup: templates/_datatable.html).
 * Cards are rebuilt from the same rows on every draw, so searching, sorting and paging drive both views.
 * Controls outside the table, by table id:
 *   <input data-dt-search="ID">                                   searches the table
 *   <button data-dt-filter="ID" data-name="status" data-value=""> a tab in a group: sends status=… (server mode)
 *   <select data-dt-filter="ID" data-name="kind">                 same, from a select
 * Wakeel.tables[ID] is the DataTables API, e.g. Wakeel.tables.subsTable.ajax.reload().
 */
(function () {
    var AR = {
        emptyTable: 'لا توجد بيانات', zeroRecords: 'لا توجد نتائج مطابقة',
        info: 'عرض _START_ إلى _END_ من أصل _TOTAL_', infoEmpty: 'لا توجد نتائج', infoFiltered: '(من أصل _MAX_)',
        processing: '<span class="spinner-border spinner-border-sm"></span> جارٍ التحميل…', loadingRecords: 'جارٍ التحميل…',
        paginate: { first: 'الأول', last: 'الأخير', next: '<i class="bi bi-chevron-left"></i>', previous: '<i class="bi bi-chevron-right"></i>' },
        aria: { paginate: { next: 'التالي', previous: 'السابق' } }
    };
    Wakeel.tables = {};

    function emptyCard(text) {
        var el = document.createElement('div');
        el.className = 'wk-dt__empty';
        el.innerHTML = '<i class="bi bi-inbox"></i><span></span>';
        el.querySelector('span').textContent = text;
        return el;
    }

    function init(table) {
        var d = table.dataset, server = d.wkTable === 'server', id = table.id;
        var wrap = table.closest('.wk-dt'), cards = wrap.querySelector('.wk-dt__cards');
        var filters = {}, paging = d.paging !== 'false';
        var columns = Array.prototype.map.call(table.tHead.rows[0].cells, function (th) {
            var col = { orderable: th.dataset.orderable !== 'false', className: th.className };
            if (server) col.data = th.dataset.col;
            return col;
        });

        function buildCards(api) {
            cards.innerHTML = '';
            var rows = api.rows({ page: 'current', search: 'applied', order: 'applied' });
            if (server) {
                rows.data().each(function (row) { cards.insertAdjacentHTML('beforeend', row.card); });
            } else {
                rows.nodes().each(function (tr) {
                    var tpl = tr.querySelector('template.wk-dt__card');
                    if (tpl) cards.appendChild(tpl.content.cloneNode(true));
                });
            }
            if (!cards.children.length) cards.appendChild(emptyCard(api.page.info().recordsTotal ? AR.zeroRecords : d.empty));
        }

        var options = {
            dom: '<"wk-dt__scroll"t>r<"wk-dt__foot"ip>',
            paging: paging, info: paging, searching: true, ordering: true, autoWidth: false,
            pageLength: +(d.pageLength || 25), order: JSON.parse(d.order || '[]'),
            language: Object.assign({}, AR, { emptyTable: d.empty || AR.emptyTable }),
            columns: columns,
            drawCallback: function () { buildCards(this.api()); },
            initComplete: function () {
                // Cards sit between the table and the footer (info + pages).
                var foot = wrap.querySelector('.wk-dt__foot');
                if (foot) foot.parentNode.insertBefore(cards, foot);
            }
        };
        if (server) {
            options.serverSide = true;
            options.processing = true;
            options.ajax = { url: d.url, data: function (params) { Object.assign(params, filters); } };
        }
        var api = jQuery(table).DataTable(options);
        Wakeel.tables[id] = api;

        var timer;
        document.querySelectorAll('[data-dt-search="' + id + '"]').forEach(function (input) {
            input.addEventListener('input', function () {
                clearTimeout(timer);
                timer = setTimeout(function () { api.search(input.value.trim()).draw(); }, server ? 350 : 120);
            });
        });
        document.querySelectorAll('[data-dt-filter="' + id + '"]').forEach(function (control) {
            var name = control.dataset.name;
            if (control.tagName === 'SELECT') {
                filters[name] = control.value;
                control.addEventListener('change', function () { filters[name] = control.value; api.ajax.reload(); });
            } else {
                if (control.classList.contains('active')) filters[name] = control.dataset.value;
                control.addEventListener('click', function () {
                    document.querySelectorAll('[data-dt-filter="' + id + '"][data-name="' + name + '"]').forEach(function (b) {
                        b.classList.toggle('active', b === control);
                        b.setAttribute('aria-pressed', b === control ? 'true' : 'false');
                    });
                    filters[name] = control.dataset.value;
                    api.ajax.reload();
                });
            }
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (!window.jQuery || !jQuery.fn.DataTable) return;
        document.querySelectorAll('table[data-wk-table]').forEach(init);
    });
})();
