"""macOS helpers: is MainStage running / which concerts are open, file bookmarks."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

IS_MAC = sys.platform == "darwin"


def mainstage_running() -> bool:
    if not IS_MAC:
        return False
    r = subprocess.run(["pgrep", "-f", r"/MainStage[^/]*\.app/Contents/MacOS/"],
                       capture_output=True, text=True)
    return r.returncode == 0


def mainstage_windows() -> list[str] | None:
    """Window titles of MainStage. None if they cannot be read (missing permission)."""
    if not IS_MAC:
        return []
    script = ('tell application "System Events" to get name of every window of '
              '(first process whose bundle identifier starts with "com.apple.mainstage")')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return None
    return [w.strip() for w in r.stdout.strip().split(",") if w.strip()]


def status() -> dict:
    running = mainstage_running()
    wins = mainstage_windows() if running else []
    return {"running": running, "windows": wins,
            "windows_readable": wins is not None}


def concert_blocker(concert_path: str) -> str | None:
    """Return a reason why the concert must not be modified right now, or None."""
    if not mainstage_running():
        return None
    name = os.path.basename(os.path.normpath(concert_path))
    stem = name[:-8] if name.endswith(".concert") else name
    wins = mainstage_windows()
    if wins is None:
        return ("MainStage is running and its open concerts cannot be determined "
                "(grant Automation/Accessibility permission for System Events). "
                "Please quit MainStage before changing concerts.")
    if any(stem in w for w in wins):
        return f'MainStage has "{name}" open. Please close the concert (or quit MainStage) first.'
    return None


def wait_until_closed(concert_path: str, timeout: float = 0, interval: float = 2) -> str | None:
    """Poll until the concert is closed or the timeout expires. Returns blocker or None."""
    deadline = time.monotonic() + max(0.0, timeout)
    reason = concert_blocker(concert_path)
    while reason and time.monotonic() < deadline:
        time.sleep(interval)
        reason = concert_blocker(concert_path)
    if reason is None and timeout:
        time.sleep(1.0)  # let MainStage finish writing
    return reason


_JXA_BOOKMARK = r"""
ObjC.import('Foundation');
function run(argv) {
  var url = $.NSURL.fileURLWithPath(argv[0]);
  var err = $();
  var data = url.bookmarkDataWithOptionsIncludingResourceValuesForKeysRelativeToURLError(0, $(), $(), err);
  if (!data || data.isNil()) { throw new Error('bookmark failed'); }
  return JSON.stringify({url: ObjC.unwrap(url.absoluteString),
                         bookmark: ObjC.unwrap(data.base64EncodedStringWithOptions(0))});
}
"""


def file_bookmark(path: str) -> tuple[str, bytes]:
    """Create (file URL, bookmark data) for a file, like MainStage does.

    Uses PyObjC when available, otherwise JavaScript for Automation (osascript).
    """
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if not IS_MAC:
        raise RuntimeError("file bookmarks can only be created on macOS")
    try:  # PyObjC
        from Foundation import NSURL  # type: ignore
        url = NSURL.fileURLWithPath_(path)
        data, err = url.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(
            0, None, None, None)
        if data is not None:
            return str(url.absoluteString()), bytes(data)
    except ImportError:
        pass
    r = subprocess.run(["osascript", "-l", "JavaScript", "-e", _JXA_BOOKMARK, path],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError(f"could not create a file bookmark: {r.stderr.strip()}")
    res = json.loads(r.stdout.strip())
    return res["url"], base64.b64decode(res["bookmark"])
