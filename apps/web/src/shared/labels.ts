import type {
  CreationMethod,
  CredentialCapability,
  Edition,
  EditionStatus,
  TranslationOrigin,
} from "../api/types";

export const credentialCapabilityLabels: Record<CredentialCapability, string> = {
  "library.read": "阅读馆藏",
  "library.upload": "上传作品与版本",
  "translation.use": "使用小说翻译",
};

export const translationOriginLabels: Record<TranslationOrigin, string> = {
  ai: "AI 译文",
  human: "人工译文",
  mixed: "混合译文",
  unknown: "来源未知译文",
};

export const creationMethodLabels: Record<CreationMethod, string> = {
  uploaded: "用户上传",
  generated: "系统生成",
  edited: "人工编辑",
  converted: "格式转换",
};

export const editionStatusLabels: Record<EditionStatus, string> = {
  draft: "草稿",
  ready: "可用",
  archived: "已归档",
};

export function editionRoleLabel(edition: Pick<Edition, "content_role" | "translation_origin">): string {
  if (edition.content_role === "source") {
    return "原文";
  }
  return edition.translation_origin
    ? translationOriginLabels[edition.translation_origin]
    : "译文";
}
