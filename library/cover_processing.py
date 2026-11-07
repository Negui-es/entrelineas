"""Local document detection and perspective correction; original photos are never stored."""
from io import BytesIO
import json
import warnings
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

cv2.setNumThreads(1)


def load_photo(upload):
    if upload.size > 4 * 1024 * 1024:
        raise ValidationError(_("La portada debe ocupar menos de 4 MB."))
    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 25_000_000 or min(image.size) < 80:
                    raise ValueError
                image.load()
                oriented = ImageOps.exif_transpose(image)
                # Transparent input is composited on white rather than turning black.
                if "A" in oriented.getbands():
                    rgba = oriented.convert("RGBA")
                    photo = Image.new("RGB", rgba.size, "white")
                    photo.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    photo = oriented.convert("RGB")
                photo.thumbnail((2000, 2000))
                photo.info.clear()
                return photo
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError(_("Elige una portada legible en JPG, PNG o WebP, de al menos 80 píxeles por lado."))


def ordered(points):
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1]-center[1], points[:, 0]-center[0])
    points = points[np.argsort(angles)]
    return np.roll(points, -np.argmin(points.sum(axis=1)), axis=0)


def validate_corners(value):
    try:
        points = json.loads(value) if isinstance(value, str) else value
        if not isinstance(points, list) or len(points) != 4 or any(not isinstance(p, list) or len(p) != 2 for p in points):
            raise ValueError
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) for p in points for n in p):
            raise ValueError
        array = np.asarray(points, dtype=np.float32)
        if not np.isfinite(array).all() or np.any(array < 0) or np.any(array > 1):
            raise ValueError
        if not cv2.isContourConvex(array.reshape(4, 1, 2)) or abs(cv2.contourArea(array)) < .03:
            raise ValueError
        return array
    except (ValueError, TypeError, OverflowError):
        raise ValidationError(_("Marca las cuatro esquinas de la portada sin cruzar los bordes."))


def detect_cover(photo):
    width, height = photo.size
    ratio = min(1, 1000 / max(width, height))
    rgb = cv2.resize(np.asarray(photo), (round(width*ratio), round(height*ratio)))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    masks = []
    for low, high in ((35, 110), (70, 180)):
        edges = cv2.Canny(gray, low, high)
        masks.append(cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)))
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    border = np.concatenate((lab[0], lab[-1], lab[:, 0], lab[:, -1]))
    background = np.median(border, axis=0)
    foreground = (np.linalg.norm(lab-background, axis=2) > 24).astype(np.uint8)*255
    masks.append(cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)))
    total = gray.shape[0]*gray.shape[1]
    candidates = []
    for mask in masks:
        contours, unused = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:40]:
            area = cv2.contourArea(contour)/total
            if not .18 <= area <= .94:
                continue
            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, .025*perimeter, True)
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            points = ordered(polygon)
            sides = np.linalg.norm(points-np.roll(points, -1, axis=0), axis=1)
            if sides.min() < 65 or sides.max()/sides.min() > 3.2:
                continue
            # Reject steep, collapsed shapes and candidates away from the photograph's centre.
            a, b = np.roll(points, 1, axis=0)-points, np.roll(points, -1, axis=0)-points
            cosines = np.abs(np.sum(a*b, axis=1)/(np.linalg.norm(a, axis=1)*np.linalg.norm(b, axis=1)))
            if cosines.max() > .65 or cv2.pointPolygonTest(points, (gray.shape[1]/2, gray.shape[0]/2), False) < 0:
                continue
            rectangularity = min(1, cv2.contourArea(contour)/max(1, cv2.contourArea(points)))
            score = .7*area + .3*(1-float(cosines.mean()))*rectangularity
            normalized = points/np.array([gray.shape[1]-1, gray.shape[0]-1], dtype=np.float32)
            candidates.append((score, np.clip(normalized, 0, 1)))
    return max(candidates, key=lambda pair: pair[0])[1].tolist() if candidates else None


def crop_cover(photo, corners, rotation=0):
    points = validate_corners(corners)
    width, height = photo.size
    points *= np.array([width-1, height-1], dtype=np.float32)
    top, right, bottom, left = np.linalg.norm(points-np.roll(points, -1, axis=0), axis=1)
    out_width, out_height = round(max(top, bottom)), round(max(left, right))
    if min(out_width, out_height) < 80 or max(out_width, out_height)/min(out_width, out_height) > 4:
        raise ValidationError(_("El recorte es demasiado pequeño o estrecho. Revisa las esquinas."))
    target = np.array([[0, 0], [out_width-1, 0], [out_width-1, out_height-1], [0, out_height-1]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(points, target)
    cropped = cv2.warpPerspective(np.asarray(photo), transform, (out_width, out_height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    image = Image.fromarray(cropped)
    if rotation not in {0, 90, 180, 270}:
        raise ValidationError(_("Giro de portada no válido."))
    return image.rotate(-rotation, expand=True) if rotation else image


def jpeg_bytes(photo):
    photo = photo.copy()
    photo.thumbnail((1200, 1800))
    result = BytesIO()
    photo.save(result, format="JPEG", quality=88, optimize=True)
    return result.getvalue()
