"""Who hears about what happens to plans and posts.

Each function takes the finished change and turns it into notifications
(apps.notifications). Kept apart from the services so bulk actions can
announce one change for many posts instead of one notification per post.
"""
from django.urls import reverse
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _, pgettext_lazy

from apps.notifications.services import managers, members, notify

from .models import Post, PostComment


def _authors(posts):
    return members(posts[0].company, [p.created_by for p in posts])


def _editors(company):
    return [m.user for m in company.memberships.select_related('user') if m.can_edit and not m.can_manage]


def _subject(posts):
    if len(posts) == 1:
        return format_lazy('«{title}»', title=posts[0].title)
    return format_lazy(_('{count} منشورات'), count=len(posts))


def _link(posts, status=''):
    if len(posts) == 1:
        return posts[0].get_absolute_url()
    return reverse('content:post_list') + (f'?status={status}' if status else '')


def status_changed(posts, status, actor, note=''):
    posts = list(posts)
    if not posts:
        return
    company, name = posts[0].company, actor.display_name
    if status == Post.Status.REVIEW:
        notify(managers(company), company, format_lazy(_('أرسل {name} {subject} للمراجعة.'), name=name, subject=_subject(posts)), _link(posts, 'review'),
               icon='bi-hourglass-split', actor=actor)
    elif status == Post.Status.APPROVED:
        notify(_authors(posts), company, format_lazy(_('اعتمد {name} {subject}.'), name=name, subject=_subject(posts)), _link(posts, 'approved'),
               icon='bi-patch-check', actor=actor)
    elif status == Post.Status.DRAFT and note:
        for post in posts:
            PostComment.objects.create(post=post, user=actor, kind=PostComment.Kind.CHANGES, body=note)
        # Posts written by the AI belong to whoever created the plan; fall back to the editors.
        notify(_authors(posts) or _editors(company), company, format_lazy(_('طلب {name} تعديل {subject}: {note}'), name=name, subject=_subject(posts), note=note),
               _link(posts), icon='bi-arrow-return-right', actor=actor, email=True)


def comment_added(comment):
    post, company = comment.post, comment.post.company
    earlier = [c.user for c in post.comments.select_related('user').exclude(pk=comment.pk) if c.user]
    recipients = members(company, [post.created_by, *earlier])
    from_guest = comment.is_guest
    team_managers = managers(company)
    if from_guest or comment.user not in team_managers:
        recipients += team_managers
    # "{who} {verb} «{title}»": verbs get their own context, as the same Arabic words label things elsewhere.
    verb = {PostComment.Kind.CHANGES: pgettext_lazy('notification verb', 'طلب تعديل'),
            PostComment.Kind.APPROVAL: pgettext_lazy('notification verb', 'اعتمد')}.get(
        comment.kind, pgettext_lazy('notification verb', 'علّق على'))
    who = format_lazy(_('{name} (العميل)'), name=comment.author_name) if from_guest else comment.author_name
    text = format_lazy('{who} {verb} «{title}»{rest}', who=who, verb=verb, title=post.title,
                       rest=f': {comment.body}' if comment.body else '.')
    notify(recipients, company, text, post.get_absolute_url() + '#comments', icon='bi-chat-left-text',
           actor=comment.user, email=from_guest)


def plan_ready(plan, posts_count):
    company = plan.company
    notify([plan.created_by, *managers(company)], company,
           format_lazy(_('خطة {title} جاهزة: {count} منشوراً بانتظار المراجعة.'), title=plan.title or _('المحتوى'), count=posts_count),
           plan.get_absolute_url(), icon='bi-stars', email=True)


def plan_failed(plan):
    notify(members(plan.company, [plan.created_by]), plan.company,
           format_lazy(_('تعذّر إعداد خطة المحتوى: {error}'), error=plan.error), plan.get_absolute_url(), icon='bi-exclamation-triangle', email=True)
