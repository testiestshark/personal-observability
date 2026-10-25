import { describe, expect, it } from "vitest";

import { type RunWeather, runWeatherPreview, runWeatherTiles, withRunWeather } from "./run-weather";

const weather: RunWeather = {
  temperatureC: 14.26,
  apparentTemperatureC: 11.5,
  relativeHumidityPercent: 78.4,
  windSpeedMph: 9.04,
  precipitationMm: 0,
};

describe("runWeatherTiles", () => {
  it("shows temperature, humidity, wind and rain, rounded for reading", () => {
    expect(runWeatherTiles(weather)).toEqual([
      { label: "Temperature", value: "14°C" },
      { label: "Humidity", value: "78%" },
      { label: "Wind", value: "9 mph" },
      { label: "Rain", value: "0 mm" },
    ]);
  });

  it("keeps a tenth of a millimetre of rain, so a drizzle is not shown as none", () => {
    const tiles = runWeatherTiles({ ...weather, precipitationMm: 0.24 });
    expect(tiles.at(-1)).toEqual({ label: "Rain", value: "0.2 mm" });
  });

  it("does not show a freezing run as negative zero", () => {
    const tiles = runWeatherTiles({ ...weather, temperatureC: -0.2 });
    expect(tiles[0]?.value).toBe("0°C");
  });

  it("shows nothing for a run with no weather", () => {
    expect(runWeatherTiles(null)).toEqual([]);
  });
});

describe("runWeatherPreview", () => {
  it("shows temperature and wind, and no rain when it did not rain", () => {
    expect(runWeatherPreview(weather)).toBe("14°C · 9 mph wind");
  });

  it("adds rain when the precipitation is above zero", () => {
    expect(runWeatherPreview({ ...weather, precipitationMm: 0.24 })).toBe(
      "14°C · 9 mph wind · 0.2 mm rain",
    );
  });

  it("does not round a drizzle down to no rain", () => {
    expect(runWeatherPreview({ ...weather, precipitationMm: 0.04 })).toBe(
      "14°C · 9 mph wind · <0.1 mm rain",
    );
  });

  it("shows nothing for a run with no weather", () => {
    expect(runWeatherPreview(null)).toBeNull();
  });
});

describe("withRunWeather", () => {
  const row = {
    fitness_activity_id: "a",
    temperature_c: 10,
    apparent_temperature_c: 8,
    relative_humidity_percent: 70,
    wind_speed_mph: 5,
    precipitation_mm: 0,
  };

  it("gives each activity its own weather, and null when it has none", () => {
    const result = withRunWeather([{ id: "a" }, { id: "b" }], [row]);
    expect(result[0]?.weather?.temperatureC).toBe(10);
    expect(result[1]?.weather).toBeNull();
  });
});
