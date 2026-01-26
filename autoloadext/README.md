# run_chrome_with_extension.py

Launch Google Chrome with unpacked extension(s) loaded from local folder(s).

Important notes:
- Chrome does not provide an official way to "permanently install" an unpacked extension without UI or enterprise policy.
- This script loads unpacked extensions for the launched Chrome instance via `--load-extension` (similar to clicking "Load unpacked" in `chrome://extensions`).
- True headless + extensions is not reliably supported by Chrome. Use `--background` (best-effort) instead.

## Requirements

- Python 3.9+ (recommended)
- Google Chrome installed

Optional:
- Set `CHROME_BIN` env var to explicitly point to the Chrome executable.

## Prepare Your Extension

Your extension folder must contain a `manifest.json`, e.g.:

```
my_ext/
  manifest.json
  ...
```

## Configuration (conf.ini)

The script will load `conf.ini` from the same directory as the program (regardless of your current working directory). If it does not exist, the script will create a template `conf.ini` on first run.

If you build a PyInstaller one-file executable, the bundled `conf.ini` is also available at runtime under `sys._MEIPASS` and will be used as a fallback when no external `conf.ini` exists next to the executable.

Config keys (see `conf.ini` in this repo):

- `platform`: `auto` / `win` / `mac`
- `extension_dir`: unpacked extension folder path (must contain `manifest.json`); can be multiple paths separated by `,` or `;`
- `cleanup_shortcut_path` (Windows only): shortcut file to delete when the script exits (absolute path recommended; `test.lnk` means "try to delete from Startup folders")

CLI arguments override `conf.ini`. If you don't pass `--ext`, the script will use `extension_dir` from `conf.ini` (if set).

## Usage

Show help:

```bash
python3 run_chrome_with_extension.py -h
```

### macOS

Load one extension folder and start Chrome in background (hidden, no focus), also open `chrome://extensions`:

```bash
python3 run_chrome_with_extension.py --ext ./my_ext --background --dev-mode --url chrome://extensions
```

Load all extension folders under current directory (all subfolders that contain `manifest.json`):

```bash
python3 run_chrome_with_extension.py --all --background --dev-mode
```

### Windows

Load one extension folder (PowerShell/CMD):

```bat
python run_chrome_with_extension.py --ext .\my_ext --background --dev-mode --url chrome://extensions
```

Load all extensions under current directory:

```bat
python run_chrome_with_extension.py --all --background --dev-mode
```

Best-effort "background" behavior on Windows:
- Adds `--start-minimized`
- Detaches the Chrome process from the console

### Linux

Load one extension folder:

```bash
python3 run_chrome_with_extension.py --ext ./my_ext --dev-mode --url chrome://extensions
```

You can also pass the Chrome binary explicitly:

```bash
python3 run_chrome_with_extension.py --chrome /usr/bin/google-chrome --ext ./my_ext
```

## Options

- `--config PATH`: path to `conf.ini` (default: `conf.ini` next to the script)
- `--platform auto|win|mac`: override platform detection (uses `conf.ini` then host OS by default)
- `--ext PATH` (repeatable): extension folder path; must contain `manifest.json`
- `--ext-root PATH`: scan for extension folders under this directory (default: `.`)
- `--all`: load all discovered extension folders under `--ext-root`
- `--user-data-dir PATH`: Chrome user data dir (default: new temp dir each run)
- `--dev-mode`: set `"extensions.ui.developer_mode" = true` in the launched profile
- `--background`: best-effort background launch (macOS hidden; Windows minimized+detached)
- `--headless`: try headless mode (extensions may not work)
- `--allow-no-ext`: allow launching Chrome even if no extension folder is found
- `--cleanup-shortcut-path PATH` (Windows only): delete this `.lnk` on exit (CLI overrides `conf.ini`)
- `--cleanup-startup-shortcut NAME` (Windows only): delete this `.lnk` name from Startup folders on exit (CLI overrides `conf.ini`)
- `--no-cleanup-startup-shortcut` (Windows only): disable shortcut cleanup on exit

Pass extra Chrome flags after `--`, for example:

```bash
python3 run_chrome_with_extension.py --ext ./my_ext -- --remote-debugging-port=9222
```

## Windows Startup Shortcut Cleanup

On Windows, when the script exits it will (by default) attempt to delete a shortcut configured by `cleanup_shortcut_path` in `conf.ini` (default: `test.lnk` from the Startup folders):

- `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\test.lnk`
- `%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\Startup\test.lnk`

Control this behavior:

- Change the shortcut path (CLI):

```bat
python run_chrome_with_extension.py --ext .\my_ext --cleanup-shortcut-path "C:\Path\To\Startup\my.lnk"
```

- Disable cleanup:

```bat
python run_chrome_with_extension.py --ext .\my_ext --no-cleanup-startup-shortcut
```


pycache python3 -m PyInstaller -y --workpath build --distpath dist run_chrome_with_extension.spec