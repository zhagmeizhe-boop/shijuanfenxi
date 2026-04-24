import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ReportErrorState,
  ReportLayout,
  ReportLoadingState,
} from '@/components/report/ReportLayout';
import { fetchReportData } from '@/services/reportData';
import { FullReportData } from '@/types/analysis';

export default function ReportPage() {
  const { id: reportId } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reportData, setReportData] = useState<FullReportData | null>(null);

  useEffect(() => {
    if (!reportId) {
      setLoading(false);
      return;
    }

    const loadReport = async () => {
      try {
        setLoading(true);
        setError(null);

        const data = await fetchReportData(reportId);
        setReportData(data);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : '加载报告失败，请稍后重试。';
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    void loadReport();
  }, [reportId]);

  if (loading) {
    return <ReportLoadingState />;
  }

  if (!reportId) {
    return (
      <ReportErrorState
        title="缺少报告编号"
        message="当前地址中未包含报告编号，无法加载报告内容。"
        onBack={() => navigate('/')}
      />
    );
  }

  if (error) {
    return (
      <ReportErrorState
        message={error}
        onRetry={() => window.location.reload()}
        onBack={() => navigate('/')}
      />
    );
  }

  if (!reportData) {
    return (
      <ReportErrorState
        message="报告数据为空，当前无法渲染报告页面。"
        onBack={() => navigate('/')}
      />
    );
  }

  return (
    <ReportLayout
      reportData={reportData}
      exportId={reportId}
      onBack={() => navigate('/')}
    />
  );
}
