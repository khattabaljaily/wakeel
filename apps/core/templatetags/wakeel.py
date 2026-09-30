from django import template

from apps.content.models import Post

register = template.Library()

STATUS_CLASSES = {
    Post.Status.DRAFT: 'draft',
    Post.Status.REVIEW: 'review',
    Post.Status.APPROVED: 'approved',
    Post.Status.PUBLISHED: 'published',
}


@register.filter
def status_class(status):
    return STATUS_CLASSES.get(status, 'draft')


@register.simple_tag(takes_context=True)
def nav_active(context, *prefixes):
    path = context['request'].path
    return 'active' if any(path.startswith(p) for p in prefixes) else ''
