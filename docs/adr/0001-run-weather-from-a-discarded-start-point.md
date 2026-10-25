# Run weather comes from a start point that is used and discarded

Weather for a run needs a place, but the app stores no location (NON_GOALS, #72). We decided (#131) that the Garmin worker reads each outdoor foot activity's start coordinate, rounds it to one decimal place (about 11 km), sends it to Open-Meteo's historical archive, and discards it. Only the weather for the hour the run started in is stored, in its own `weather` schema, fetched once. A rounded area cannot be traced back to a start position, and Open-Meteo's grid is coarser than that rounding anyway, so the data loses nothing.

## Considered options

- **A fixed home point from configuration.** Wrong whenever the owner runs elsewhere, and it would put a home area in worker configuration for a public repository.
- **Geocoding the town in the activity name.** Breaks when an activity is renamed or two towns share a name.
- **A point ten minutes into the run.** Needs an extra Garmin request per run and gains no accuracy, because the start and that point sit in the same weather cell.
- **Weather fetched when a run is opened, nothing stored.** Cannot be aggregated, which is the purpose.
- **Open-Meteo's forecast endpoints.** The aim is the weather that actually happened. The archive is a reanalysis of that, a couple of days behind real time, so a very recent run shows no weather until it catches up.

## Consequences

- The worker must never log or persist the coordinate, nor pass it to anything but Open-Meteo, which sees it at the rounded precision.
- Open-Meteo's values are modelled for an area, not measured at the runner's position, and are not revised after the single fetch.
- A `weather` schema is not exposed to the API by default; exposing it on hosted Supabase is a manual step for the owner.
