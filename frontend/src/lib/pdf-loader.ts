export type PdfLoaderPolicy = "auto" | "ocr" | "text"

export const PDF_LOADER_OPTIONS: ReadonlyArray<{
  value: PdfLoaderPolicy
  label: string
  description: string
}> = [
  {
    value: "auto",
    label: "自动",
    description: "跟随上方「是否启用 GPU」：启用时用 OCR，未启用时读文本层",
  },
  {
    value: "ocr",
    label: "OCR 解析",
    description: "始终使用 OCR；未启用 GPU 时以 CPU 运行",
  },
  {
    value: "text",
    label: "文本提取",
    description: "仅提取 PDF 内嵌文本层，不走 OCR",
  },
] as const

const PDF_LOADER_LABEL_BY_VALUE = new Map(
  PDF_LOADER_OPTIONS.map((option) => [option.value, option.label] as const),
)

const PDF_LOADER_DESCRIPTION_BY_VALUE = new Map(
  PDF_LOADER_OPTIONS.map((option) => [option.value, option.description] as const),
)

export function getPdfLoaderLabel(value?: string): string {
  if (!value) return PDF_LOADER_LABEL_BY_VALUE.get("auto") ?? "自动"
  return PDF_LOADER_LABEL_BY_VALUE.get(value as PdfLoaderPolicy) ?? "自动"
}

export function getPdfLoaderDescription(value: PdfLoaderPolicy): string {
  return PDF_LOADER_DESCRIPTION_BY_VALUE.get(value) ?? ""
}

export function formatGpuEnabledLabel(value?: string): string {
  return value === "yes" ? "启用" : "未启用"
}
