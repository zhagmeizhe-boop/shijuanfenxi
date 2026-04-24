import { useState } from 'react';
import { Download } from 'lucide-react';
import { generatePDF } from '@/services/reportData';

interface PDFExportButtonProps {
  reportId: string;
  onExport?: () => void;
}

export function PDFExportButton({ reportId, onExport }: PDFExportButtonProps) {
  const [isExporting, setIsExporting] = useState(false);
  const [progress, setProgress] = useState(0);

  const handleExport = async () => {
    setIsExporting(true);
    setProgress(0);

    let progressInterval: ReturnType<typeof setInterval> | undefined;

    try {
      progressInterval = setInterval(() => {
        setProgress((prev) => {
          if (prev >= 90) {
            if (progressInterval) {
              clearInterval(progressInterval);
            }
            return 90;
          }
          return prev + 10;
        });
      }, 200);

      const blob = await generatePDF(reportId);
      if (progressInterval) {
        clearInterval(progressInterval);
      }

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `六维评价报告_${reportId}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      setProgress(100);
      onExport?.();
    } catch (error) {
      console.error('PDF export failed:', error);
      const message =
        error instanceof Error ? error.message : 'PDF 导出失败，请稍后重试。';
      alert(message);
    } finally {
      if (progressInterval) {
        clearInterval(progressInterval);
      }

      window.setTimeout(() => {
        setIsExporting(false);
        setProgress(0);
      }, 500);
    }
  };

  return (
    <button
      type="button"
      className="report-action-button report-action-button--primary"
      onClick={handleExport}
      disabled={isExporting}
    >
      {isExporting ? (
        <span className="report-action-button__progress" style={{ width: `${progress}%` }} />
      ) : null}
      <Download className="report-action-button__icon" />
      <span className="report-action-button__label">
        {isExporting ? `导出中 ${progress}%` : '导出 PDF 报告'}
      </span>
    </button>
  );
}
