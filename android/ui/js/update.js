// Version rules of the self-update, same as tankg/updater.py (newer, min_version, required).

export const versionTuple = v => String(v).replace(/^v/, "").split(".").map(n => parseInt(n, 10) || 0);
export const newer = (a, b) => {
  const x = versionTuple(a), y = versionTuple(b);
  for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
};
/** Minimum version a release declares (<!-- tankg-min-version: 1.11.0 -->), or "". */
export const minVersion = body => (String(body || "").match(/<!--\s*tankg-min-version:\s*v?([0-9]+(?:\.[0-9]+){0,2})\s*-->/) || [])[1] || "";
/** This version is no longer allowed: the update is mandatory (security fixes). */
export const updateRequired = (latest, min, current) => !!min && newer(latest, current) && newer(min, current);
