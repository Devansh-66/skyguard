/* What the ARM station codes actually mean.
 *
 * `sgpmetE37` is not a name anyone can read, and a maintenance board that asks
 * an operator to dispatch someone to "sgpmetE37" is asking them to dispatch to
 * nowhere. The code decomposes as:
 *
 *     sgp    met    E37
 *     site   platform   facility
 *
 *   site      the ARM observatory: sgp / nsa / ena
 *   platform  MET -- the surface meteorological system, the datastream that
 *             carries temperature, pressure and relative humidity
 *   facility  C = Central facility, E = Extended facility, then which one
 *
 * (The `.b1` on the raw filenames is ARM's data level: quality-controlled.)
 *
 * EVERY VALUE BELOW WAS READ OUT OF THE FILES, not looked up or remembered.
 * `location_description`, `lat` and `lon` are global attributes on each .cdf;
 * regenerate with:
 *
 *     python -c "import glob,netCDF4; ..."   (see the commit that added this)
 *
 * These are US and Portuguese instruments. That is not an accident and it is
 * not hidden: they are the validation set, because ARM publishes fault reports
 * written by humans who inspected the hardware, and no Indian network publishes
 * anything equivalent. The deployment target is the Indian network on the map
 * console. The two are never plotted together -- drawing an Oklahoma mast on
 * the India map would claim this monitors Oklahoma, which it does not.
 */

export interface SiteInfo {
  /** Human place name: the town the mast actually stands in. */
  place: string
  /** Region / country, for the second line. */
  region: string
  /** ARM observatory long name. */
  observatory: string
  facility: string
  lat: number
  lon: number
}

export const SITES: Record<string, SiteInfo> = {
  sgpmetE13: { place: 'Lamont', region: 'Oklahoma, USA', observatory: 'Southern Great Plains', facility: 'Extended Facility 13', lat: 36.605, lon: -97.485 },
  sgpmetE31: { place: 'Anthony', region: 'Kansas, USA', observatory: 'Southern Great Plains', facility: 'Extended Facility 31', lat: 37.1509, lon: -98.362 },
  sgpmetE32: { place: 'Medford', region: 'Oklahoma, USA', observatory: 'Southern Great Plains', facility: 'Extended Facility 32', lat: 36.819, lon: -97.8199 },
  sgpmetE33: { place: 'Newkirk', region: 'Oklahoma, USA', observatory: 'Southern Great Plains', facility: 'Extended Facility 33', lat: 36.9255, lon: -97.0817 },
  sgpmetE37: { place: 'Waukomis', region: 'Oklahoma, USA', observatory: 'Southern Great Plains', facility: 'Extended Facility 37', lat: 36.3106, lon: -97.928 },
  sgpmetE39: { place: 'Morrison', region: 'Oklahoma, USA', observatory: 'Southern Great Plains', facility: 'Extended Facility 39', lat: 36.3735, lon: -97.0691 },
  sgpmetE41: { place: 'Peckam', region: 'Oklahoma, USA', observatory: 'Southern Great Plains', facility: 'Extended Facility 41', lat: 36.8796, lon: -97.0864 },
  nsametC1: { place: 'Barrow', region: 'Alaska, USA', observatory: 'North Slope of Alaska', facility: 'Central Facility 1', lat: 71.323, lon: -156.609 },
  enametC1: { place: 'Graciosa Island', region: 'Azores, Portugal', observatory: 'Eastern North Atlantic', facility: 'Central Facility 1', lat: 39.0916, lon: -28.0257 },
}

/** "Waukomis, Oklahoma, USA" — or the raw code if we have not decoded it, which
 *  is honest rather than inventing a plausible-looking place. */
export function siteName(station: string): string {
  const s = SITES[station]
  return s ? s.place + ', ' + s.region : station
}

export function siteInfo(station: string): SiteInfo | undefined {
  return SITES[station]
}
