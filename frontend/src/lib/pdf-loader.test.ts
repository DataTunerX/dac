import { describe, expect, it } from "vitest"
import {
  formatGpuEnabledLabel,
  getPdfLoaderDescription,
  getPdfLoaderLabel,
} from "./pdf-loader"

describe("pdf-loader copy helpers", () => {
  it("maps policy values to stable labels", () => {
    expect(getPdfLoaderLabel("auto")).toBe("自动")
    expect(getPdfLoaderLabel("ocr")).toBe("OCR 解析")
    expect(getPdfLoaderLabel("text")).toBe("文本提取")
    expect(getPdfLoaderLabel(undefined)).toBe("自动")
  })

  it("describes auto mode relative to the GPU toggle", () => {
    expect(getPdfLoaderDescription("auto")).toContain("是否启用 GPU")
  })

  it("formats gpu enabled state for detail view", () => {
    expect(formatGpuEnabledLabel("yes")).toBe("启用")
    expect(formatGpuEnabledLabel("no")).toBe("未启用")
  })
})
