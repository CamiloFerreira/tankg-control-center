"""Single source of the app version for the desktop build, the APK (android/build.sh) and the
Android UI (tools/export_ui.py). Release tags must match it (v + __version__)."""
__version__ = "1.9.1"

# Public repository that only holds the release files; every app updates itself from here.
RELEASES_REPO = "CamiloFerreira/tankg-control-center-releases"
# Project site (GitHub Pages from docs/), privacy policy and terms; linked from "Acerca de"
SITE_URL = "https://camiloferreira.github.io/tankg-control-center/"
PRIVACY_URL = SITE_URL + "PRIVACY.html"
TERMS_URL = SITE_URL + "TERMS.html"
