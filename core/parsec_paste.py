"""Paste through the remote context menu when Parsec ignores synthetic keys."""

import io
import json
import math
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

_LOCK = threading.Lock()


def _normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.lower())
                   if not unicodedata.combining(c)).replace('\u0131', 'i')


def _ocr_paste_entries(png):
    import Quartz
    import Vision
    from Foundation import NSData

    data = NSData.dataWithBytes_length_(png, len(png))
    source = Quartz.CGImageSourceCreateWithData(data, None)
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    # The GPU path can stall on newer macOS versions; keep OCR isolated and on CPU.
    request.setUsesCPUOnly_(True)
    request.setRecognitionLevel_(0)
    request.setRecognitionLanguages_(['tr-TR', 'en-US'])
    request.setUsesLanguageCorrection_(False)
    handler = Vision.VNSequenceRequestHandler.alloc().init()
    ok, error = handler.performRequests_onCGImage_error_([request], image, None)
    if not ok:
        raise RuntimeError('Menu OCR basarisiz.')
    entries = []
    for result in request.results() or []:
        candidate = result.topCandidates_(1)[0]
        value = str(candidate.string())
        for word in re.finditer(r'\w+', value):
            if _normalized(word.group()) not in {'paste', 'yapistir'}:
                continue
            # Vision uses UTF-16 offsets, while Python indexes Unicode code points.
            start = len(value[:word.start()].encode('utf-16-le')) // 2
            length = len(word.group().encode('utf-16-le')) // 2
            rect, error = candidate.boundingBoxForRange_error_((start, length), None)
            if rect is None or candidate.confidence() < 0.4:
                continue
            box = rect.boundingBox()
            entries.append([float(box.origin.x), float(box.origin.y),
                            float(box.size.width), float(box.size.height)])
    return entries


def _capture_entries(gui, region):
    left, top, right, bottom = region
    screenshot = gui.screenshot()
    crop = None
    try:
        width, height = gui.size()
        scale_x, scale_y = screenshot.width / width, screenshot.height / height
        crop = screenshot.crop((int(left * scale_x), int(top * scale_y),
                                int(right * scale_x), int(bottom * scale_y)))
        with io.BytesIO() as buffer:
            crop.save(buffer, format='PNG')
            completed = subprocess.run(
                [sys.executable, '-m', 'core.parsec_paste', '--ocr'],
                input=buffer.getvalue(), capture_output=True, timeout=8,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
        if completed.returncode:
            raise RuntimeError('Parsec menu OCR kullanilamiyor; Vision kurulumunu kontrol edin.')
        return [(left + (x + w / 2) * (right - left),
                 top + (1 - y - h / 2) * (bottom - top))
                for x, y, w, h in json.loads(completed.stdout)]
    finally:
        if crop is not None:
            crop.close()
        screenshot.close()


def _new_entry(before, after, anchor):
    candidates = [point for point in after
                  if math.dist(point, anchor) < 380
                  and all(math.dist(point, old) > 15 for old in before)]
    return candidates[0] if len(candidates) == 1 else None


def _pointer_on_parsec(point):
    import AppKit
    import Quartz

    apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_('tv.parsec.www')
    pids = {int(app.processIdentifier()) for app in apps}
    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, 0)
    x, y = point
    for window in windows or []:
        if window.get('kCGWindowLayer') != 0:
            continue
        bounds = window['kCGWindowBounds']
        if (bounds['X'] <= x < bounds['X'] + bounds['Width']
                and bounds['Y'] <= y < bounds['Y'] + bounds['Height']):
            return int(window['kCGWindowOwnerPID']) in pids
    return False


def paste_via_menu(text, gui, clipboard, *, restore_clipboard=False):
    from core.system_tools import SystemOps

    with _LOCK:
        if not SystemOps.is_parsec_frontmost():
            raise RuntimeError('Once Parsec penceresindeki hedef metin alanini secin.')
        anchor = tuple(gui.position())
        if not _pointer_on_parsec(anchor):
            raise RuntimeError('Fare gorunur Parsec metin alaninin uzerinde olmali.')
        width, height = gui.size()
        x, y = anchor
        region = (max(0, x - 380), max(0, y - 420),
                  min(width, x + 380), min(height, y + 420))
        before = _capture_entries(gui, region)
        previous = clipboard.paste() if restore_clipboard else None
        clipboard.copy(text)
        menu_open = False
        try:
            time.sleep(1.0)
            if not SystemOps.is_parsec_frontmost():
                raise RuntimeError('Parsec odagi degisti; metin gonderilmedi.')
            gui.click(x, y, button='right')
            menu_open = True
            time.sleep(0.4)
            point = _new_entry(before, _capture_entries(gui, region), anchor)
            if point is None:
                raise RuntimeError('Hedef menude Yapistir/Paste bulunamadi.')
            if not SystemOps.is_parsec_frontmost():
                raise RuntimeError('Parsec odagi degisti; yapistirma iptal edildi.')
            gui.click(*point)
            time.sleep(0.5)
            remaining = _capture_entries(gui, region)
            if any(math.dist(point, item) < 15 for item in remaining):
                raise RuntimeError('Yapistir menusu kapanmadi; pano iznini kontrol edin.')
            menu_open = False
            return True
        finally:
            if menu_open and SystemOps.is_parsec_frontmost():
                # Dismiss the remote menu by clicking the original text target.
                gui.click(*anchor)
            if restore_clipboard and clipboard.paste() == text:
                clipboard.copy(previous)


if __name__ == '__main__':
    if sys.argv[1:] != ['--ocr']:
        raise SystemExit(2)
    print(json.dumps(_ocr_paste_entries(sys.stdin.buffer.read())))
