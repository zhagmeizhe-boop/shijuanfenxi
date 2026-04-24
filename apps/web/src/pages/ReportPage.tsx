import { useEffect, useState } from 'react';
import {
  ReportErrorState,
  ReportLayout,
  ReportLoadingState,
} from '@/components/report/ReportLayout';
import { fetchReportData } from '@/services/reportData';
import { FullReportData } from '@/types/analysis';

interface ReportPageProps {
  reportId?: string;
}

export function ReportPage({ reportId = 'rpt-2024-001' }: ReportPageProps) {
  const [report, setReport] = useState<FullReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadReport();
  }, [reportId]);

  const loadReport = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchReportData(reportId);
      setReport(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '无法加载报告数据';
      setError(message);
      console.error('加载报告失败:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <ReportLoadingState message="正在加载分析报告..." />;
  }

  if (error || !report) {
    return (
      <ReportErrorState
        title="报告加载失败"
        message={error || '无法加载报告数据'}
        onRetry={() => {
          void loadReport();
        }}
      />
    );
  }

  return <ReportLayout reportData={report} />;
}

export default ReportPage;
