"""Single source of the app version for the desktop build, the APK (android/build.sh) and the
web app (tools/export_web.py). Release tags must match it (v + __version__)."""
__version__ = "1.5.0"

# Public repository that only holds the release files; every app updates itself from here.
RELEASES_REPO = "CamiloFerreira/tankg-control-center-releases"
