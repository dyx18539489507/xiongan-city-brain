import {describe, expect, it} from "vitest";
import {isHeroArchitectureName} from "./HeroContextManager";

describe("HeroContextManager", () => {
  it("keeps Blender architecture but never imports the authored road as truth", () => {
    expect(isHeroArchitectureName("K06_Architecture_Pearl")).toBe(true);
    expect(isHeroArchitectureName("K06_Architecture_LowEGlass")).toBe(true);
    expect(isHeroArchitectureName("K06_Road_Asphalt_PBR")).toBe(false);
    expect(isHeroArchitectureName("K06_Signal_Housing")).toBe(false);
  });
});
