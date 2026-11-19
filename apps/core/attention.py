"""The one list of what is waiting for this person, across both halves of the product (marketing and documents/work).

Each item is a count, a sentence and the page that deals with it; an item with nothing waiting is left out, and a person only
sees what their role can act on (a viewer sees nothing to approve, a client sees only what concerns them)."""
import datetime

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import pgettext

from apps.companies.models import Membership


def _item(icon, tone, count, label, url):
    # The count is shown large and the label names what is counted ("5 | posts waiting for review"), so one wording serves 1 and 5.
    return {'icon': icon, 'tone': tone, 'count': count, 'label': _(label), 'url': url}


def waiting(company, user, membership):
    """[{'title', 'icon', 'items': [...]}] for the groups that have something waiting."""
    from apps.content.models import Post
    from apps.documents.models import Document
    from apps.inbox.models import InboxItem
    from apps.library.models import SOON_DAYS, Record
    from apps.tasks.models import Task

    now = timezone.now()
    is_client = membership.role == Membership.Role.CLIENT
    groups = []

    marketing = []
    posts = Post.objects.filter(company=company)
    if membership.can_edit:
        review = posts.filter(status=Post.Status.REVIEW).count()
        if review:
            marketing.append(_item('bi-hourglass-split', 'review', review, 'منشورات بانتظار المراجعة',
                                   reverse('content:post_list') + '?status=review'))
        late = posts.filter(scheduled_at__lt=now, status__in=[Post.Status.APPROVED, Post.Status.REVIEW]).count()
        if late:
            marketing.append(_item('bi-alarm', 'late', late, 'منشورات تجاوزت موعد نشرها',
                                   reverse('content:post_list') + '?overdue=1'))
        replies = InboxItem.objects.filter(company=company, status=InboxItem.Status.NEW).exclude(category=InboxItem.Category.SPAM).count()
        if replies:
            marketing.append(_item('bi-chat-dots', 'primary', replies, 'تعليقات بانتظار الرد', reverse('inbox:inbox')))
    if marketing:
        groups.append({'title': _('التسويق'), 'icon': 'bi-stars', 'items': marketing})

    docs = []
    if membership.can_manage:
        pending = Document.objects.filter(status=Document.PENDING).count()
        if pending:
            docs.append(_item('bi-patch-check', 'review', pending, 'Documents waiting for your approval',
                              reverse('documents:issued') + '?status=pending'))
    if not is_client:
        soon = timezone.localdate() + datetime.timedelta(days=SOON_DAYS)
        expiring = Record.objects.filter(expiry_date__isnull=False, expiry_date__lte=soon).count()
        if expiring:
            docs.append(_item('bi-hourglass-bottom', 'late', expiring, 'Papers expired or expiring within 30 days', reverse('library:list') + '?status=soon'))
    if docs:
        groups.append({'title': pgettext('menu section', 'Documents and files'), 'icon': 'bi-layers', 'items': docs})

    work = []
    if not is_client:
        mine = Task.objects.filter(assignee=user).exclude(status=Task.DONE)
        today = timezone.localdate()
        overdue = mine.filter(due_date__lt=today).count()
        if overdue:
            work.append(_item('bi-alarm', 'late', overdue, 'Tasks of yours are overdue', reverse('tasks:list') + '?show=mine'))
        rest = mine.count() - overdue
        if rest:
            work.append(_item('bi-check2-square', 'primary', rest, 'Tasks assigned to you', reverse('tasks:list') + '?show=mine'))
    if work:
        groups.append({'title': pgettext('menu section', 'Team workspace'), 'icon': 'bi-people', 'items': work})
    return groups


def overview(company, user, membership):
    """The company's whole product at a glance (not only marketing): money, papers, documents, tasks. None for a client."""
    if membership.role == Membership.Role.CLIENT:
        return None
    from apps.credits import catalog, charging
    from apps.documents.models import Document
    from apps.library.models import SOON_DAYS, Record
    from apps.tasks.models import Task
    today = timezone.localdate()
    wallet = charging.get_wallet(company)
    month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = charging.revenue_usd(since=month, company=company)[2]
    low = not wallet.is_exempt and wallet.balance < 1000          # under $1
    return {
        'balance': catalog.format_points(wallet.balance), 'exempt': wallet.is_exempt, 'low': low, 'spent_month': spent,
        'records': Record.objects.count(),
        'expiring': Record.objects.filter(expiry_date__isnull=False, expiry_date__lte=today + datetime.timedelta(days=SOON_DAYS)).count(),
        'issued_month': Document.objects.filter(created_at__gte=month).count(),
        'drafts': Document.objects.filter(status=Document.DRAFT, created_by=user).count(),
        'my_tasks': Task.objects.filter(assignee=user).exclude(status=Task.DONE).count(),
    }
