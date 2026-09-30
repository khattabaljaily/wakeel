from apps.core.tables import Col, Table


def members():
    return Table('membersTable', 'companies/rows/member.html', [
        Col('member', 'العضو', order='user.first_name'),
        Col('role', 'الدور', order='role'),
        Col('joined', 'انضم في', order='created_at'),
        Col('actions', '', cls='text-end'),
    ], paging=False, empty='لا يوجد أعضاء')
