import { describe, expect, it } from "vitest";

import { creationMethodLabels, editionRoleLabel } from "../src/shared/labels";

describe("edition labels", () => {
  it("uses explicit Chinese text for every edition type", () => {
    expect(editionRoleLabel({ content_role: "source", translation_origin: null })).toBe("原文");
    expect(editionRoleLabel({ content_role: "translation", translation_origin: "ai" })).toBe("AI 译文");
    expect(editionRoleLabel({ content_role: "translation", translation_origin: "human" })).toBe("人工译文");
    expect(editionRoleLabel({ content_role: "translation", translation_origin: "mixed" })).toBe("混合译文");
    expect(editionRoleLabel({ content_role: "translation", translation_origin: "unknown" })).toBe("来源未知译文");
  });

  it("uses the required creation-method labels", () => {
    expect(creationMethodLabels).toEqual({
      uploaded: "用户上传",
      generated: "系统生成",
      edited: "人工编辑",
      converted: "格式转换",
    });
  });
});

