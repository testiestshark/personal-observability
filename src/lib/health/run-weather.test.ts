import { describe, expect, it } from "vitest";

import { type RunWeather, runWeatherTiles } from "./run-weather";

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
