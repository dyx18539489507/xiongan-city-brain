import {describe, expect, it} from "vitest";
import {ComparisonDigitalTwinSocket} from "./ComparisonDigitalTwinSocket";
import {emptyPairedDigitalTwinState} from "./ComparisonDigitalTwinStore";
import {DigitalTwinSocket} from "./DigitalTwinSocket";
import {emptyDigitalTwinState} from "./DigitalTwinStore";

describe("runtime stream reset", () => {
  it("clears the single-run entity state without reconnecting", () => {
    const states: unknown[] = [];
    const client = new DigitalTwinSocket("ws://unused", {
      onConnection: () => undefined,
      onIssue: () => undefined,
      onState: (state) => states.push(state),
    });

    client.reset();

    expect(states).toEqual([emptyDigitalTwinState]);
  });

  it("clears both sides and the pair identity together", () => {
    const states: unknown[] = [];
    const client = new ComparisonDigitalTwinSocket("ws://unused", {
      onConnection: () => undefined,
      onIssue: () => undefined,
      onState: (state) => states.push(state),
    });

    client.reset();

    expect(states).toEqual([emptyPairedDigitalTwinState]);
  });
});
