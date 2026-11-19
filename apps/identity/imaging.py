"""Clean an uploaded logo into a transparent PNG.

The logo keeps its own colours: a picture that is already transparent is only cut to the drawing; one on a plain light
background has that background (the part of it joined to the edges, so white inside the logo stays) made transparent.
A logo on a dark, coloured or busy background is kept as it is, since removing that background would change the logo.
(The app keeps no stamp or signature, so only the logo is cleaned.)"""
import io
import warnings

import numpy as np
from django.utils.translation import gettext as _
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

MAX_PIXELS = 40_000_000          # larger pictures are refused before they are decoded (decompression bombs)
WORK_MAX = 1600                  # the working size; photos are far larger than a logo needs
LOGO_MAX = 1200
MIN_SIDE = 60
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageProblem(Exception):
    """The picture cannot be used; `message` says why, in the user's language."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _load(upload, keep_alpha=False) -> Image.Image:
    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)      # a huge picture is a refusal, not a warning
            probe = Image.open(upload)
        with probe:
            if probe.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ImageProblem(_('Use a PNG, JPG or WebP picture.'))
            if probe.width * probe.height > MAX_PIXELS:
                raise ImageProblem(_('The picture is too large. Use a smaller photo.'))
            im = ImageOps.exif_transpose(probe)
            im.load()
    except ImageProblem:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageProblem(_('The picture is too large. Use a smaller photo.')) from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageProblem(_('This picture could not be read. Try another one.')) from None
    if im.width < MIN_SIDE or im.height < MIN_SIDE:
        raise ImageProblem(_('The picture is too small. Use a sharper photo.'))
    if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
        im = im.convert('RGBA')
        if not keep_alpha:
            flat = Image.new('RGBA', im.size, (255, 255, 255, 255))
            flat.alpha_composite(im)
            im = flat
    if im.mode != 'RGBA' or not keep_alpha:
        im = im.convert('RGB')
    if max(im.size) > WORK_MAX:
        im.thumbnail((WORK_MAX, WORK_MAX), Image.LANCZOS)
    return im


def _png(result: Image.Image, limit: int):
    if max(result.size) > limit:
        result.thumbnail((limit, limit), Image.LANCZOS)
    buffer = io.BytesIO()
    result.save(buffer, 'PNG', optimize=True)
    return buffer.getvalue(), result.width, result.height


def _background_alpha(rgb: np.ndarray):
    """The alpha of a logo whose background is plain and light, or None when the background is not (left as it is).
    Only the background joined to the edges is removed, so white letters or shapes inside the logo stay."""
    h, w = rgb.shape[:2]
    band = max(2, min(h, w) // 50)
    border = np.concatenate([rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3),
                             rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    if float(bg @ np.array([0.299, 0.587, 0.114])) < 200:
        return None, bg                        # a dark or coloured background is part of the logo's look
    spread = float(np.percentile(np.abs(border - bg).max(axis=1), 90))
    if spread > 40:
        return None, bg                        # a photo or a pattern, not a plain background
    diff = np.abs(rgb - bg).max(axis=2)
    low = max(spread * 1.5, 14.0)
    high = low + 45.0
    # The background-like pixels joined to the edges: fill from a one-pixel frame around the picture.
    near = np.pad((diff < high).astype(np.uint8) * 255, 1, constant_values=255)
    mask = Image.fromarray(near, 'L').copy()        # a copy: floodfill does not change an image that shares the array
    ImageDraw.floodfill(mask, (0, 0), 128)
    outside = np.asarray(mask)[1:-1, 1:-1] == 128
    alpha = np.ones((h, w), dtype=np.float32)
    alpha[outside] = np.clip((diff[outside] - low) / (high - low), 0, 1)
    return alpha, bg


def clean_logo(upload):
    """Return (PNG bytes, width, height) of the logo on a transparent background, cut to the drawing."""
    im = _load(upload, keep_alpha=True)
    if im.mode == 'RGBA' and float((np.asarray(im)[..., 3] < 250).mean()) > 0.01:
        rgba = np.asarray(im, dtype=np.float32)              # already transparent: keep its own edges
        rgb, alpha = rgba[..., :3], rgba[..., 3] / 255.0
    else:
        rgb = np.asarray(im.convert('RGB'), dtype=np.float32)
        alpha, bg = _background_alpha(rgb)
        if alpha is None:
            return _png(im.convert('RGBA'), LOGO_MAX)
        # The colour of a half-transparent edge pixel without the background mixed into it.
        soft = (alpha > 0.02) & (alpha < 1)
        rgb = rgb.copy()
        rgb[soft] = bg + (rgb[soft] - bg) / alpha[soft][:, None]
    if float((alpha > 0.5).mean()) < 0.001:
        raise ImageProblem(_('We could not find a clear logo in this picture. Use the logo file on a plain background.'))
    rows, cols = np.where(alpha > 0.05)
    pad = int(0.02 * max(alpha.shape))
    top, bottom = max(rows.min() - pad, 0), min(rows.max() + pad + 1, alpha.shape[0])
    left, right = max(cols.min() - pad, 0), min(cols.max() + pad + 1, alpha.shape[1])
    out = np.zeros((bottom - top, right - left, 4), dtype=np.uint8)
    out[..., :3] = np.clip(rgb[top:bottom, left:right], 0, 255).astype(np.uint8)
    out[..., 3] = (np.clip(alpha[top:bottom, left:right], 0, 1) * 255).astype(np.uint8)
    return _png(Image.fromarray(out, 'RGBA'), LOGO_MAX)
