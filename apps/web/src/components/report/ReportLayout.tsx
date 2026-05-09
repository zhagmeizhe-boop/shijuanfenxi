import { AlertCircle, ArrowLeft, Loader2, RefreshCcw } from 'lucide-react';
import { FullReportData } from '@/types/analysis';
import { DimensionScoreCards } from '@/components/report/DimensionScoreCards';
import { DifficultyPositioning } from '@/components/report/DifficultyPositioning';
import { PDFExportButton } from '@/components/report/PDFExportButton';
import { SixDimensionsRadar } from '@/components/report/SixDimensionsRadar';
import {
  formatScore,
  getDifficultyTargetStudents,
  getDifficultyLabel,
} from '@/components/report/reportMeta';
import './ReportTheme.css';

interface ReportLayoutProps {
  reportData: FullReportData;
  exportId?: string;
  onBack?: () => void;
}

interface ReportLoadingStateProps {
  message?: string;
}

interface ReportErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  onBack?: () => void;
}

export function ReportLayout({ reportData, exportId, onBack }: ReportLayoutProps) {
  const overallLevel = getDifficultyLabel(
    reportData.difficulty_position.level,
    reportData.difficulty_position.label,
  );
  const targetStudents = getDifficultyTargetStudents(
    reportData.difficulty_position.level,
    reportData.difficulty_position.target_students,
  );
  const pdfExportId = exportId || reportData.paper_id || reportData.report_id;

  return (
    <div className="report-shell">
      <div className="report-canvas">
        <header className="report-header">
          <div className="report-header__top">
            <div>
              <span className="report-eyebrow">专业教研版报告</span>
              <h1>六维评价分析报告</h1>
              <p className="report-header__paper">{reportData.paper_title}</p>
            </div>

            <div className="report-header__actions">
              <PDFExportButton reportId={pdfExportId} />
              {onBack ? (
                <button
                  type="button"
                  className="report-action-button report-action-button--secondary"
                  onClick={onBack}
                >
                  <ArrowLeft className="report-action-button__icon" />
                  <span className="report-action-button__label">返回首页</span>
                </button>
              ) : null}
            </div>
          </div>
          <div className="report-overview-strip">
            <div className="report-overview-item">
              <span>整卷等级</span>
              <strong>{overallLevel}</strong>
            </div>
            <div className="report-overview-item">
              <span>综合分</span>
              <strong>{formatScore(reportData.difficulty_position.overall_score)} / 10</strong>
            </div>
            <div className="report-overview-item">
              <span>目标学生</span>
              <strong>{targetStudents}</strong>
            </div>
          </div>
        </header>

        <main className="report-body">
          <section className="report-core-grid">
            <DifficultyPositioning data={reportData.difficulty_position} />
            <SixDimensionsRadar
              dimensions={reportData.dimensions}
              dimensionDetails={reportData.dimension_details}
            />
          </section>

          <section className="report-section">
            <div className="report-section__header">
              <div>
                <span className="report-section__eyebrow">六维评分</span>
                <h2>六维评价明细</h2>
              </div>
              <p>统一呈现维度名称、得分、等级与评分依据摘要，减少冗余噪音，突出可读性。</p>
            </div>
            <DimensionScoreCards dimensions={reportData.dimension_details} />
          </section>

        </main>

        <footer className="report-footer">
          本报告仅调整呈现方式，不涉及六维算法口径与后端接口变更。
        </footer>
      </div>
    </div>
  );
}

export function ReportLoadingState({
  message = '正在加载六维评价报告，请稍候。',
}: ReportLoadingStateProps) {
  return (
    <div className="report-state">
      <div className="report-state__panel">
        <div className="report-state__icon">
          <Loader2 className="report-state__spinner" size={32} />
        </div>
        <h2>报告加载中</h2>
        <p>{message}</p>
      </div>
    </div>
  );
}

export function ReportErrorState({
  title = '报告加载失败',
  message,
  onRetry,
  onBack,
}: ReportErrorStateProps) {
  return (
    <div className="report-state">
      <div className="report-state__panel">
        <div className="report-state__icon">
          <AlertCircle size={32} />
        </div>
        <h2>{title}</h2>
        <p>{message}</p>

        <div className="report-state__actions">
          {onRetry ? (
            <button
              type="button"
              className="report-action-button report-action-button--primary"
              onClick={onRetry}
            >
              <RefreshCcw className="report-action-button__icon" />
              <span className="report-action-button__label">重新加载</span>
            </button>
          ) : null}

          {onBack ? (
            <button
              type="button"
              className="report-action-button report-action-button--secondary"
              onClick={onBack}
            >
              <ArrowLeft className="report-action-button__icon" />
              <span className="report-action-button__label">返回首页</span>
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
