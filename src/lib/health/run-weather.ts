/**
 * The weather for the hour an outdoor run started in (#131), as the app reads
 * it from `weather.run_weather`. There is deliberately no place in it: the
 * table stores none (ADR 0001).
 */
export type RunWeather = {
  temperatureC: number;
  apparentTemperatureC: number;
  relativeHumidityPercent: number;
  windSpeedMph: number;
  precipitationMm: number;
};

/** The columns of a `weather.run_weather` row the app reads. */
export type RunWeatherRow = {
  temperature_c: number;
  apparent_temperature_c: number;
  relative_humidity_percent: number;
  wind_speed_mph: number;
  precipitation_mm: number;
};

/**
 * The generated `Database` type covers `public` only, so the `weather` schema is
 * described here, just far enough for the one read. Cast a request client to
 * `SupabaseClient<WeatherDatabase, "weather">` to query it typed.
 */
export type WeatherDatabase = {
  weather: {
    Tables: {
      run_weather: {
        Row: RunWeatherRow & { user_id: string; fitness_activity_id: string };
        Insert: never;
        Update: never;
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
};

export const RUN_WEATHER_COLUMNS =
  "temperature_c, apparent_temperature_c, relative_humidity_percent, wind_speed_mph, precipitation_mm";

export function toRunWeather(row: RunWeatherRow): RunWeather {
  return {
    temperatureC: row.temperature_c,
    apparentTemperatureC: row.apparent_temperature_c,
    relativeHumidityPercent: row.relative_humidity_percent,
    windSpeedMph: row.wind_speed_mph,
    precipitationMm: row.precipitation_mm,
  };
}

/** Whole degrees; `+ 0` turns a rounded -0 into 0 so "-0°C" never shows. */
function degrees(celsius: number): string {
  return `${Math.round(celsius) + 0}°C`;
}

/**
 * The full set for the run page, one tile per value. A run with no weather
 * (indoor, or not fetched yet) gives no tiles, so the page shows nothing.
 */
export function runWeatherTiles(weather: RunWeather | null): { label: string; value: string }[] {
  if (!weather) return [];
  return [
    { label: "Temperature", value: degrees(weather.temperatureC) },
    { label: "Feels like", value: degrees(weather.apparentTemperatureC) },
    { label: "Humidity", value: `${Math.round(weather.relativeHumidityPercent)}%` },
    { label: "Wind", value: `${Math.round(weather.windSpeedMph)} mph` },
    {
      label: "Rain",
      value: `${weather.precipitationMm.toLocaleString("en-GB", { maximumFractionDigits: 1 })} mm`,
    },
  ];
}
