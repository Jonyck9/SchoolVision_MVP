# SchoolVision MVP — RTSP test build

SchoolVision is a Windows desktop prototype for managing schools and their IP cameras.
This build adds live RTSP playback to the existing camera cards.

## Included
- Local SQLite database stored at `%USERPROFILE%\\.schoolvision\\schoolvision.db`.
- 30 demo schools on first launch and school search.
- Add schools; add, edit and delete cameras.
- Save each camera's full RTSP URL.
- Start/stop live RTSP playback in a background thread using OpenCV/FFmpeg.
- Existing local database is preserved; this update does not delete it.

## Run on Windows 10/11

Install Python 3.11 or 3.12 from https://www.python.org/downloads/ and enable **Add python.exe to PATH**.

Open PowerShell in the extracted project folder and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, use:

```powershell
py -m pip install -r requirements.txt
py main.py
```

## Add the iCSee camera

1. Confirm the camera and PC are on the same local network.
2. In VLC, use the RTSP URL format that successfully displayed your camera.
3. In SchoolVision, select a school and click **+ Добавить камеру** (or **Настроить** for an existing camera).
4. Enter a camera name and paste the complete RTSP URL into **RTSP-адрес**.
5. Save, then click **Запустить видео**.

Do not share the RTSP URL if it contains a username or password. The prototype stores the URL in the local SQLite database without encryption, so restrict access to your Windows account and PC.

## Notes and limitations
- RTSP playback depends on the camera's stream format and the FFmpeg support bundled with OpenCV. A URL that works in VLC may need a different stream/substream URL or transport setting for OpenCV.
- This is a local-network test. `192.168.x.x` addresses are not reachable from other schools over the public internet. Do not expose camera ports directly to the internet; use a secure VPN or an outbound encrypted gateway/server for remote sites.
- The hierarchy is currently school → cameras. District grouping and multi-user remote administration are not implemented in this MVP.
