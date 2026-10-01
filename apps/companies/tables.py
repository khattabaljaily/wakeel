from django.utils.translation import gettext_lazy as _
from apps.core.tables import Col, Table


def members():
    return Table('membersTable', 'companies/rows/member.html', [
        Col('member', _('العضو'), order='user.first_name'),
        Col('role', _('الدور'), order='role'),
        Col('joined', _('انضم في'), order='created_at'),
        Col('actions', '', cls='text-end'),
    ], paging=False, empty=_('لا يوجد أعضاء'))
