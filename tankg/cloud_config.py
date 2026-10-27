"""OAuth clients of the Google Cloud project used for Drive sync (scope drive.appdata), created once
by the author. For installed apps Google does not treat these secrets as confidential: they ship
inside the executables. Empty values disable the sync.

DESKTOP_*  client type "Desktop app": Windows/Linux sign in with one click (browser + loopback).
DEVICE_*   client type "TVs and Limited Input devices": Android signs in with a code (device flow);
           tools/export_ui.py copies these two to the APK.
"""
DESKTOP_CLIENT_ID = ""
DESKTOP_CLIENT_SECRET = ""
DEVICE_CLIENT_ID = ""
DEVICE_CLIENT_SECRET = ""
