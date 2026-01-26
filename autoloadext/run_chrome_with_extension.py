#!/usr/bin/env python3
"""
Launch Chrome with unpacked extension(s) loaded from a local folder.

Notes/limits:
- Chrome cannot "permanently install" an unpacked extension without UI/policy.
- This script loads unpacked extensions for the launched Chrome instance via
  `--load-extension` (similar to "Load unpacked" in chrome://extensions).
- True headless + extensions is not reliably supported by Chrome; use `--background`
  on macOS to launch Chrome hidden (no focus). On Windows this is best-effort
  (starts minimized + detaches from console).
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def _exe_dir() -> Path:
    # When frozen (PyInstaller), sys.executable points to the built executable.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _script_dir()


def _bundle_dir() -> Path:
    # In PyInstaller one-file mode, sys._MEIPASS is the temporary extraction dir.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            return Path(meipass).resolve()
        except OSError:
            return Path(meipass)
    return _script_dir()


def _normalize_platform(value: str) -> str:
    v = (value or "").strip().lower()
    if v in ("auto", ""):
        return "auto"
    if v in ("win", "windows"):
        return "windows"
    if v in ("mac", "macos", "osx", "darwin"):
        return "darwin"
    # Keep unknown values as-is so we can error consistently.
    return v


def _effective_platform(host_sysname: str, configured: str | None) -> str:
    cfg = _normalize_platform(configured or "auto")
    if cfg == "auto":
        return host_sysname
    if cfg not in ("windows", "darwin"):
        print(
            f"Unknown platform={configured!r}; falling back to host platform {host_sysname!r}.",
            file=sys.stderr,
        )
        return host_sysname
    # Safety: don't allow forcing cross-OS behaviors that rely on OS-specific APIs/constants.
    if cfg != host_sysname:
        print(
            f"Ignoring configured platform={configured!r} because host platform is {host_sysname!r}.",
            file=sys.stderr,
        )
        return host_sysname
    return cfg


def _load_or_create_config(path: Path) -> configparser.ConfigParser:
    # Disable interpolation so Windows-style env vars like %APPDATA% work in values.
    cfg = configparser.ConfigParser(interpolation=None)
    if not path.exists():
        template = textwrap.dedent(
            """\
            [settings]
            # platform: auto / win / mac
            platform = auto

            # extension_dir: unpacked extension folder path (must contain manifest.json).
            # - Use an absolute path, or a path relative to this script directory.
            # - You can specify multiple folders separated by ',' or ';'.
            extension_dir =

            # cleanup_shortcut_path (Windows only): shortcut file to delete when the script exits.
            # - Absolute path is recommended.
            # - If you put only a file name like "test.lnk", the script will try to delete it from
            #   the Startup folders.
            cleanup_shortcut_path = test.lnk
            """
        )
        try:
            path.write_text(template, encoding="utf-8")
            print(f"Created default config: {path}", file=sys.stderr)
        except OSError:
            # Best-effort: if we can't write, continue without config.
            return cfg
    cfg.read(path, encoding="utf-8")
    return cfg


def _load_config_with_fallback(primary: Path, fallback: Path | None) -> tuple[configparser.ConfigParser, Path]:
    """
    Load config from primary path if it exists, otherwise from fallback if it exists.
    If neither exists, create a template at primary.
    Returns (config, used_path).
    """
    if primary.exists():
        return _load_or_create_config(primary), primary
    if fallback and fallback.exists():
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(fallback, encoding="utf-8")
        return cfg, fallback
    return _load_or_create_config(primary), primary


def _default_chrome_candidates(sysname: str) -> list[str]:
    # Prefer explicit env if provided.
    env = os.environ.get("CHROME_BIN")
    cands: list[str] = []
    if env:
        cands.append(env)

    if sysname == "darwin":
        cands += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif sysname == "windows":
        # Best-effort; users can pass --chrome explicitly.
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LocalAppData")
        cands += [
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pfx86, "Google", "Chrome", "Application", "chrome.exe"),
        ]
        if local:
            cands.append(os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"))
        for name in ("chrome", "chrome.exe"):
            p = shutil.which(name)
            if p:
                cands.append(p)
    else:
        # Linux/BSD
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            p = shutil.which(name)
            if p:
                cands.append(p)
    return cands


def find_chrome_binary(sysname: str, user_value: str | None) -> str:
    if user_value:
        p = Path(user_value)
        if p.exists():
            return str(p)
        w = shutil.which(user_value)
        if w:
            return w
        raise SystemExit(f"Chrome binary not found: {user_value}")

    for c in _default_chrome_candidates(sysname):
        if Path(c).exists():
            return c
    raise SystemExit(
        "Chrome binary not found. Pass --chrome /path/to/chrome (or set CHROME_BIN)."
    )


def _windows_startup_dirs() -> list[Path]:
    # Per-user and common Startup folders.
    # - User: %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
    # - Common: %PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\Startup
    out: list[Path] = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")

    if appdata:
        out.append(
            Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        )
    if programdata:
        out.append(
            Path(programdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
    # Filter duplicates/non-existing.
    seen: set[Path] = set()
    dirs: list[Path] = []
    for p in out:
        p = p.resolve()
        if p in seen:
            continue
        seen.add(p)
        if p.is_dir():
            dirs.append(p)
    return dirs


def delete_windows_startup_shortcut(shortcut_name: str) -> None:
    if not shortcut_name:
        return
    for d in _windows_startup_dirs():
        p = d / shortcut_name
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                # Best-effort cleanup; ignore permission/locking issues.
                pass


def delete_windows_shortcut_path(path_spec: str) -> None:
    """
    Delete a Windows .lnk file specified either as:
    - an absolute path; OR
    - a relative file name/path resolved against the Startup folders.
    """

    spec = (path_spec or "").strip().strip('"')
    if not spec:
        return

    expanded = os.path.expandvars(os.path.expanduser(spec))
    p = Path(expanded)
    if p.is_absolute():
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
        return

    # Treat as relative to Startup folders.
    for d in _windows_startup_dirs():
        cand = (d / p).resolve()
        if cand.is_file():
            try:
                cand.unlink()
            except OSError:
                pass


def discover_extensions(root: Path) -> list[Path]:
    exts: list[Path] = []
    if not root.exists():
        return exts
    for p in root.iterdir():
        if p.is_dir() and (p / "manifest.json").is_file():
            exts.append(p.resolve())
    return sorted(exts)


def ensure_dev_mode_pref(user_data_dir: Path) -> None:
    # This only toggles the UI flag for chrome://extensions. It is not required
    # for --load-extension, but matches "enable developer mode" expectation.
    pref = user_data_dir / "Default" / "Preferences"
    pref.parent.mkdir(parents=True, exist_ok=True)
    if pref.exists():
        try:
            data = json.loads(pref.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    exts = data.setdefault("extensions", {})
    ui = exts.setdefault("ui", {})
    ui["developer_mode"] = True
    pref.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def build_chrome_args(
    user_data_dir: Path,
    ext_dirs: list[Path],
    url: str | None,
    headless: bool,
    background: bool,
    sysname: str,
    extra_args: list[str],
) -> list[str]:
    args = [
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "--metrics-recording-only",
        "--disable-component-update",
    ]
    if headless:
        # Extensions may not work in headless; keep it optional.
        args += ["--headless=new", "--disable-gpu"]
    if background and sysname == "windows":
        # Best-effort: Chrome is a GUI app and can still show a window, but this
        # usually starts it minimized.
        args.append("--start-minimized")
    if ext_dirs:
        ext_list = ",".join(str(p) for p in ext_dirs)
        args += [
            f"--disable-extensions-except={ext_list}",
            f"--load-extension={ext_list}",
        ]
    if url:
        args.append(url)
    args += extra_args
    return args


def main() -> int:
    exe_dir = _exe_dir()
    bundle_dir = _bundle_dir()

    # Allow overriding config path, but default to conf.ini next to this script.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    pre_args, _ = pre.parse_known_args()
    if pre_args.config:
        raw = os.path.expandvars(os.path.expanduser(pre_args.config))
        p = Path(raw)
        config_path = (exe_dir / p).resolve() if not p.is_absolute() else p.resolve()
    else:
        config_path = (exe_dir / "conf.ini").resolve()

    # Frozen one-file mode: allow reading a bundled conf.ini from sys._MEIPASS as fallback.
    fallback_config_path: Path | None = None
    if getattr(sys, "frozen", False):
        fallback_config_path = (bundle_dir / "conf.ini").resolve()

    cfg, cfg_used_path = _load_config_with_fallback(config_path, fallback_config_path)
    cfg_settings = cfg["settings"] if cfg.has_section("settings") else {}
    cfg_platform = cfg_settings.get("platform", "auto")
    cfg_ext_dir = cfg_settings.get("extension_dir", "")
    cfg_cleanup_shortcut_path = cfg_settings.get("cleanup_shortcut_path", "test.lnk")

    ap = argparse.ArgumentParser(
        description="Launch Chrome and load unpacked extension(s) from folder(s)."
    )
    ap.add_argument(
        "--config",
        default=str(config_path),
        help="Path to conf.ini (default: conf.ini next to this program).",
    )
    ap.add_argument(
        "--platform",
        choices=["auto", "win", "mac"],
        help="Override platform detection (auto/win/mac). If omitted, uses conf.ini then host OS.",
    )
    ap.add_argument(
        "--ext",
        action="append",
        default=[],
        help="Extension folder path (repeatable). Must contain manifest.json.",
    )
    ap.add_argument(
        "--ext-root",
        default=".",
        help="Scan this folder for subfolders containing manifest.json (default: .).",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Load all discovered extension folders under --ext-root.",
    )
    ap.add_argument(
        "--allow-no-ext",
        action="store_true",
        help="Allow launching Chrome even if no extension folder is found.",
    )
    ap.add_argument("--chrome", help="Chrome binary path (or name in PATH).")
    ap.add_argument(
        "--user-data-dir",
        help="Chrome user data dir. Default: a new temp dir for each run.",
    )
    ap.add_argument(
        "--dev-mode",
        action="store_true",
        help='Also set "extensions.ui.developer_mode" in the profile Preferences.',
    )
    ap.add_argument(
        "--background",
        action="store_true",
        help=(
            "Best-effort background launch. macOS: hidden (no focus) via `open -gj`. "
            "Windows: start minimized and detach from console."
        ),
    )
    ap.add_argument(
        "--cleanup-startup-shortcut",
        help="Windows only: delete this shortcut name from the Startup folder on exit (CLI overrides conf.ini).",
    )
    ap.add_argument(
        "--cleanup-shortcut-path",
        help=(
            "Windows only: delete this shortcut path on exit. "
            "If relative, it is resolved against the Startup folders."
        ),
    )
    ap.add_argument(
        "--no-cleanup-startup-shortcut",
        action="store_true",
        help="Windows only: do not delete the Startup shortcut on exit.",
    )
    ap.add_argument(
        "--headless",
        action="store_true",
        help="Try headless mode (extensions may not work).",
    )
    ap.add_argument("--url", help="URL to open after launching Chrome.")
    ap.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help=(
            "Extra flags passed to Chrome after '--'. "
            "Example: -- --remote-debugging-port=9222"
        ),
    )
    args = ap.parse_args()
    host_sysname = platform.system().lower()
    sysname = _effective_platform(host_sysname, args.platform or cfg_platform)

    try:
        chrome_bin = find_chrome_binary(sysname, args.chrome)

        user_data_dir = (
            Path(args.user_data_dir).expanduser().resolve()
            if args.user_data_dir
            else Path(tempfile.mkdtemp(prefix="chrome-profile-")).resolve()
        )

        # If user didn't specify --ext, use extension_dir from config.
        if not args.ext and cfg_ext_dir.strip():
            # If we used a bundled config from sys._MEIPASS, resolve relative paths
            # against the executable directory (the place users would expect to manage files).
            if fallback_config_path and cfg_used_path == fallback_config_path:
                config_base_dir = exe_dir
            else:
                config_base_dir = cfg_used_path.parent
            # Allow multiple extension dirs separated by ',' or ';'.
            parts = [p.strip() for p in cfg_ext_dir.replace(";", ",").split(",") if p.strip()]
            for raw in parts:
                p = Path(os.path.expandvars(os.path.expanduser(raw)))
                if not p.is_absolute():
                    p = (config_base_dir / p).resolve()
                args.ext.append(str(p))

        ext_dirs: list[Path] = []
        for e in args.ext:
            p = Path(e).expanduser().resolve()
            if not (p.is_dir() and (p / "manifest.json").is_file()):
                raise SystemExit(f"--ext must be a folder containing manifest.json: {p}")
            ext_dirs.append(p)

        discovered = discover_extensions(Path(args.ext_root).expanduser().resolve())
        if args.all and discovered:
            ext_dirs = discovered
        elif not ext_dirs and discovered:
            # If user didn't specify --ext/--all, default to the first discovered extension.
            ext_dirs = [discovered[0]]
        elif not ext_dirs and not args.allow_no_ext:
            raise SystemExit(
                "No extension folder found. Put an unpacked extension folder (with manifest.json) "
                "under --ext-root, or pass --ext /path/to/extension, or use --all."
            )

        if args.dev_mode:
            ensure_dev_mode_pref(user_data_dir)

        chrome_args = build_chrome_args(
            user_data_dir=user_data_dir,
            ext_dirs=ext_dirs,
            url=args.url,
            headless=args.headless,
            background=args.background,
            sysname=sysname,
            extra_args=args.extra,
        )

        if args.background and host_sysname == "darwin":
            # `open -gj` keeps Chrome hidden and doesn't steal focus.
            app_path = None
            try:
                p = Path(chrome_bin)
                # Typical macOS path:
                #   Foo.app/Contents/MacOS/Foo
                if p.parts[-3:] == ("Contents", "MacOS", p.name) and p.parents[2].suffix == ".app":
                    app_path = str(p.parents[2])
            except Exception:
                app_path = None
            cmd = ["open", "-gj", "-n", "-a", app_path or "Google Chrome", "--args", *chrome_args]
            subprocess.run(cmd, check=True)
            print(f"Launched Chrome in background. user-data-dir={user_data_dir}")
            if ext_dirs:
                print("Loaded extensions:")
                for p in ext_dirs:
                    print(f"  - {p}")
            else:
                print("No extension folders were loaded.")
            return 0

        # Cross-platform: launch chrome binary directly (window may appear).
        cmd = [chrome_bin, *chrome_args]
        popen_kwargs: dict[str, object] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if host_sysname == "windows":
            # Detach from the console so the script can exit without keeping a console window open.
            if args.background:
                popen_kwargs["stdin"] = subprocess.DEVNULL
                popen_kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
        subprocess.Popen(cmd, **popen_kwargs)
        print(f"Launched Chrome. user-data-dir={user_data_dir}")
        if ext_dirs:
            print("Loaded extensions:")
            for p in ext_dirs:
                print(f"  - {p}")
        else:
            print("No extension folders were loaded.")
        return 0
    finally:
        if (
            host_sysname == "windows"
            and not getattr(args, "no_cleanup_startup_shortcut", False)
        ):
            if getattr(args, "cleanup_shortcut_path", None):
                delete_windows_shortcut_path(args.cleanup_shortcut_path)
            elif getattr(args, "cleanup_startup_shortcut", None):
                delete_windows_startup_shortcut(args.cleanup_startup_shortcut)
            elif (cfg_cleanup_shortcut_path or "").strip():
                delete_windows_shortcut_path(cfg_cleanup_shortcut_path)


if __name__ == "__main__":
    raise SystemExit(main())
