"""Single source of the app version for the desktop build, the APK (android/build.sh) and the
Android UI (tools/export_ui.py). Release tags must match it (v + __version__)."""
__version__ = "1.7.1"

# Public repository that only holds the release files; every app updates itself from here.
RELEASES_REPO = "CamiloFerreira/tankg-control-center-releases"
# Privacy policy and terms (docs/ of the public source repository; linked from "Acerca de")
PRIVACY_URL = "https://github.com/CamiloFerreira/tankg-control-center/blob/main/docs/PRIVACY.md"
TERMS_URL = "https://github.com/CamiloFerreira/tankg-control-center/blob/main/docs/TERMS.md"
