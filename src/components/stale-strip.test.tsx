import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children, ...rest }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}));

import { StaleStrip } from "./stale-strip";

describe("StaleStrip", () => {
  it("renders nothing when no source is stale", () => {
    const { container } = render(<StaleStrip sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names every stale source and links to the sources page", () => {
    render(<StaleStrip sources={["Garmin", "GitHub"]} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/integrations");
    expect(link).toHaveTextContent("Garmin sync stopped");
    expect(link).toHaveTextContent("GitHub sync stopped");
  });
});
