"""Single source of the app version for the desktop build, the APK (android/build.sh) and the
Android UI (tools/export_ui.py). Release tags must match it (v + __version__)."""
__version__ = "1.11.1"
# Oldest version still allowed to run. Raise it to this release's version when the release fixes
# something important (security): older apps then refuse to work until they update. The release
# workflow writes it into the release notes as <!-- tankg-min-version: X --> and every app reads it
# from there (updater.required on the desktop, checkUpdate in android/ui/js/app.js).
MIN_VERSION = "1.11.1"

# Public repository that only holds the release files; every app updates itself from here.
RELEASES_REPO = "CamiloFerreira/tankg-control-center-releases"
# Project site (GitHub Pages from docs/), privacy policy and terms; linked from "Acerca de"
SITE_URL = "https://camiloferreira.github.io/tankg-control-center/"
PRIVACY_URL = SITE_URL + "PRIVACY.html"
TERMS_URL = SITE_URL + "TERMS.html"
