import { FullReportData } from '@/types/analysis';

async function extractErrorMessage(response: Response, fallback: string): Promise<string> {
  const contentType = response.headers.get('content-type') || '';

  try {
    if (contentType.includes('application/json')) {
      const payload = await response.json();
      if (typeof payload?.detail === 'string' && payload.detail.trim()) {
        return payload.detail;
      }
      if (typeof payload?.message === 'string' && payload.message.trim()) {
        return payload.message;
      }
    } else {
      const text = await response.text();
      if (text.trim()) {
        return text.trim();
      }
    }
  } catch {
    // Fall through to fallback.
  }

  return fallback;
}

export async function fetchReportData(reportId: string): Promise<FullReportData> {
  const response = await fetch(`/api/v1/reports/${reportId}`);

  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('报告不存在或试卷尚未分析完成。');
    }

    throw new Error(`获取报告失败: ${response.status}`);
  }

  const payload = (await response.json()) as FullReportData;
  payload.report_warnings = Array.isArray(payload.report_warnings) ? payload.report_warnings : [];
  payload.dimension_details = Array.isArray(payload.dimension_details)
    ? payload.dimension_details.map((detail) => ({
        ...detail,
        score_status:
          detail.score_status || (detail.level <= 0 || detail.score <= 0 ? 'not_covered' : 'scored'),
      }))
    : [];
  return payload;
}

export async function generatePDF(reportId: string): Promise<Blob> {
  try {
    const response = await fetch(`/api/v1/reports/${reportId}/pdf`, {
      method: 'POST',
    });

    if (!response.ok) {
      const fallback = `PDF 导出失败（HTTP ${response.status}）`;
      const message = await extractErrorMessage(response, fallback);
      throw new Error(message);
    }

    return response.blob();
  } catch (error) {
    if (error instanceof Error) {
      const normalized = error.message.toLowerCase();
      if (normalized.includes('failed to fetch') || normalized.includes('networkerror')) {
        throw new Error('无法连接到后端导出服务，请确认后端已启动。');
      }
      throw error;
    }

    throw new Error('PDF 导出失败，请稍后重试。');
  }
}
