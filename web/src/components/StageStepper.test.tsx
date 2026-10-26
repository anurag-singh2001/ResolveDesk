import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { STAGE_ORDER, stepperModel } from "../lib/stages";
import { StageStepper } from "./StageStepper";

function states(stage: string) {
  return stepperModel(stage).map((s) => `${s.key}:${s.state}`);
}

describe("stepperModel", () => {
  it("walks the happy path", () => {
    expect(states("received")[0]).toBe("received:current");
    expect(states("investigating").slice(0, 3)).toEqual(["received:done", "investigating:current", "awaiting_approval:upcoming"]);
    expect(states("processing")).toEqual([
      "received:done",
      "investigating:done",
      "awaiting_approval:done",
      "processing:current",
      "confirmed:upcoming",
    ]);
    expect(stepperModel("confirmed").every((s) => s.state === "done")).toBe(true);
  });

  it("shows awaiting_info, declined, escalated and closed as their own states", () => {
    expect(states("awaiting_info")[1]).toBe("awaiting_info:current");
    expect(stepperModel("awaiting_info")[1].tone).toBe("warning");

    const declined = stepperModel("declined");
    expect(declined[2]).toMatchObject({ key: "declined", state: "current", tone: "danger" });
    expect(declined.slice(3).every((s) => s.state === "skipped")).toBe(true);

    const escalated = stepperModel("escalated");
    expect(escalated[2]).toMatchObject({ key: "escalated", state: "current", tone: "info" });
    expect(escalated.slice(3).every((s) => s.state === "upcoming")).toBe(true);

    const closed = stepperModel("closed");
    expect(closed.at(-1)).toMatchObject({ key: "closed", state: "current" });
  });

  it("gives every stage exactly one current step except confirmed", () => {
    for (const stage of STAGE_ORDER) {
      const current = stepperModel(stage).filter((s) => s.state === "current");
      expect(current.length).toBe(stage === "confirmed" ? 0 : 1);
    }
  });
});

describe("<StageStepper>", () => {
  it("marks the current step for assistive tech", () => {
    render(<StageStepper stage="awaiting_approval" />);
    const current = screen.getByRole("listitem", { current: "step" });
    expect(current).toHaveTextContent("Awaiting approval");
    expect(current).toHaveAttribute("data-state", "current");
  });

  it("labels a declined case distinctly", () => {
    render(<StageStepper stage="declined" />);
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("Declined");
    expect(screen.queryByText(/^Awaiting approval/)).not.toBeInTheDocument();
  });

  it("labels awaiting_info as waiting for the customer's reply", () => {
    render(<StageStepper stage="awaiting_info" />);
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("Waiting for your reply");
  });
});
