"use client"

/**
 * 재무제표 PDF 다운로드 — html2canvas + jsPDF.
 * SSR 안전 (dynamic import). 한글 폰트는 캡처 후 이미지화하므로 시스템 폰트 사용 가능.
 */
export async function exportElementToPdf(
  element: HTMLElement,
  filename: string,
): Promise<void> {
  const [{ default: html2canvas }, { default: jsPDF }] = await Promise.all([
    import("html2canvas"),
    import("jspdf"),
  ])

  // 1) DOM 캡처 (high-DPI)
  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    backgroundColor: "#ffffff",
    logging: false,
  })

  // 2) A4 portrait — 페이지 자동 분할
  const pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" })
  const pageWidth = pdf.internal.pageSize.getWidth()
  const pageHeight = pdf.internal.pageSize.getHeight()
  const margin = 10
  const usableWidth = pageWidth - margin * 2
  const usableHeight = pageHeight - margin * 2

  const imgWidth = usableWidth
  const imgHeight = (canvas.height * imgWidth) / canvas.width

  if (imgHeight <= usableHeight) {
    // 한 페이지에 들어감
    pdf.addImage(
      canvas.toDataURL("image/png"),
      "PNG",
      margin,
      margin,
      imgWidth,
      imgHeight,
    )
  } else {
    // 여러 페이지 분할 — 슬라이스 단위 다시 캡처
    const sliceHeightPx = Math.floor((usableHeight / imgWidth) * canvas.width)
    const sliceCanvas = document.createElement("canvas")
    sliceCanvas.width = canvas.width
    sliceCanvas.height = sliceHeightPx
    const sliceCtx = sliceCanvas.getContext("2d")
    if (!sliceCtx) throw new Error("PDF slice context 생성 실패")

    let renderedPx = 0
    let firstPage = true
    while (renderedPx < canvas.height) {
      const remaining = canvas.height - renderedPx
      const currentSliceHeight = Math.min(sliceHeightPx, remaining)
      sliceCanvas.height = currentSliceHeight

      sliceCtx.fillStyle = "#ffffff"
      sliceCtx.fillRect(0, 0, sliceCanvas.width, currentSliceHeight)
      sliceCtx.drawImage(
        canvas,
        0, renderedPx, canvas.width, currentSliceHeight,
        0, 0, canvas.width, currentSliceHeight,
      )

      if (!firstPage) pdf.addPage()
      firstPage = false

      const sliceImgHeight = (currentSliceHeight * imgWidth) / canvas.width
      pdf.addImage(
        sliceCanvas.toDataURL("image/png"),
        "PNG",
        margin,
        margin,
        imgWidth,
        sliceImgHeight,
      )

      renderedPx += currentSliceHeight
    }
  }

  pdf.save(filename)
}
