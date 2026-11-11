# SuiteLocal Install Guide

How to build the Windows installer, share it through Google Drive, and install SuiteLocal on
each business's computer. The business owner does not need Python.

## 1. Build the installer (developer)

Run in PowerShell from the project folder, once dependencies are installed
(`python -m pip install -e ".[dev]"`):

```powershell
.\packaging\build.ps1
```

The script cleans `build\` and `dist\`, runs PyInstaller, and checks that
`dist\SuiteLocal\SuiteLocal.exe` exists. Then:

- With [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed, it produces
  `dist\SuiteLocal-Setup.exe`. **This is the file you share.**
- Without Inno Setup, it produces `dist\SuiteLocal.zip` as a fallback.

Check the build before sharing it:

```powershell
.\dist\SuiteLocal\SuiteLocal.exe --smoke-test
```

It starts without windows, uses a temporary database, and must exit with code 0.

## 2. Upload it to Google Drive (developer)

1. Open [drive.google.com](https://drive.google.com) and create a folder, for example
   `SuiteLocal 0.1.0`.
2. Upload `dist\SuiteLocal-Setup.exe` (or `dist\SuiteLocal.zip`) to that folder.
3. Right-click the file > **Share** > **General access** > **Anyone with the link**, role
   **Viewer**.
4. Copy the link and send it to the business owner.

Put the version in the folder name so each release stays separate.

## 3. Install it (business owner)

1. Open the Drive link and click **Download**. Drive may say it cannot scan the file for
   viruses because of its size; choose **Download anyway**.
2. Double-click `SuiteLocal-Setup.exe`.
3. The installer is not code-signed, so Windows SmartScreen may show
   "Windows protected your PC". Click **More info** > **Run anyway**.
4. Follow the wizard. It does not ask for administrator rights and installs into
   `%LOCALAPPDATA%\Programs\SuiteLocal`. Tick the desktop shortcut option if you want one.
5. Open SuiteLocal from the Start menu or the desktop shortcut.

With the zip instead: extract it and open `SuiteLocal\SuiteLocal.exe`.

On first launch, a setup wizard asks for the business name, business type, tax regime, and the
owner user.

## 4. Where the data lives

The database, backups, and certificates are stored in `%LOCALAPPDATA%\SuiteLocal`.
Uninstalling the application does **not** delete this folder.

Each installation is per Windows user: every computer (and every Windows user) has its own
separate database.

## 5. Updating to a new version

1. Build and upload the new installer (steps 1 and 2).
2. The owner closes SuiteLocal, downloads the new `SuiteLocal-Setup.exe`, and runs it.

The installer replaces the program files and keeps the data in `%LOCALAPPDATA%\SuiteLocal`.
Make a backup from the application before updating.
