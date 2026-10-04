from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.clickjacking import xframe_options_sameorigin

from apps.companies.decorators import company_required
from apps.companies.models import MediaAsset
from apps.content.models import Post

from .render import post_fields, render_html

OVERRIDABLE = ('headline', 'subheadline', 'cta', 'badge', 'template', 'size', 'scheme', 'motif', 'variant')


@company_required
@xframe_options_sameorigin
def preview(request, pk):
    """The post's design as a live HTML page; the editor passes unsaved values as query params."""
    post = get_object_or_404(Post.objects.select_related('company', 'background'), pk=pk, company=request.company)
    overrides = {k: request.GET[k] for k in OVERRIDABLE if k in request.GET}
    if 'background' in request.GET:
        bg = request.GET['background']
        overrides['background'] = MediaAsset.objects.filter(pk=bg, company=request.company).first() if bg.isdigit() else None
    return HttpResponse(render_html(request.company, post_fields(post, overrides)))
