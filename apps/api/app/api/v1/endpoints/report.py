import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.report.pdf_generator import PDFExportService
from app.services.report.report_service import ReportService

router = APIRouter()
logger = logging.getLogger(__name__)

pdf_service = PDFExportService()
report_service = ReportService()


def _describe_exception(exc: Exception) -> str:
    parts: list[str] = []
    current: Exception | None = exc

    while current is not None and len(parts) < 3:
        current_type = current.__class__.__name__
        current_text = str(current).strip() or current_type
        parts.append(f"{current_type}：{current_text}")
        next_exc = current.__cause__ or current.__context__
        current = next_exc if isinstance(next_exc, Exception) else None

    return " | 原因链: ".join(parts)


@router.post("/{report_id}/pdf")
async def generate_pdf_report(report_id: str):
    """
    Generate a report PDF.

    Note: the route parameter still uses the historic `report_id` name, but in
    the active flow it is effectively the current paper id.
    """
    try:
        logger.info("PDF export request stage=load_report report=%s", report_id)
        report_data = await report_service.get_report_data(report_id)
        if not report_data:
            raise HTTPException(status_code=404, detail="未找到对应的报告数据。")

        logger.info("PDF export request stage=generate_bytes report=%s", report_id)
        pdf_bytes = await pdf_service.generate_report_pdf_bytes(report_data=report_data)

        filename = f"六维分析报告_{report_id}.pdf"
        logger.info("PDF export request stage=response_ready report=%s", report_id)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF export request failed report=%s", report_id)
        raise HTTPException(status_code=500, detail=f"PDF 生成失败：{_describe_exception(exc)}") from exc


@router.get("/{report_id}")
async def get_report_data(report_id: str):
    """Get report data."""
    try:
        report_data = await report_service.get_report_data(report_id)
        if not report_data:
            raise HTTPException(status_code=404, detail="报告不存在。")
        return report_data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取报告失败：{_describe_exception(exc)}") from exc
