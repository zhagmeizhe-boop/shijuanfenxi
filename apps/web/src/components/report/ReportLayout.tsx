import { AlertCircle, ArrowLeft, Loader2, RefreshCcw } from 'lucide-react';
import { FullReportData } from '@/types/analysis';
import { DimensionScoreCards } from '@/components/report/DimensionScoreCards';
import { DifficultyPositioning } from '@/components/report/DifficultyPositioning';
import { PDFExportButton } from '@/components/report/PDFExportButton';
import { SixDimensionsRadar } from '@/components/report/SixDimensionsRadar';
import {
  formatScore,
  getDifficultyMeta,
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

function getSummaryParagraphs(summary: string): string[] {
  const paragraphs = summary
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean);

  if (paragraphs.length > 0) {
    return paragraphs;
  }

  return ['暂无总体评价。'];
}

function getAdviceNote(reportData: FullReportData): string {
  const warningCount = reportData.dimension_details.filter((item) => item.warning).length;

  if (warningCount > 0) {
    return `当前六维明细中有 ${warningCount} 个维度带有复核提示，建议结合题号、题目摘要与计入理由做二次核对后再制定训练重点。`;
  }

  return '建议先依据整卷等级与综合分确定训练强度，再按六维得分和计入题号安排分层巩固与专项提升。';
}

export function ReportLayout({ reportData, exportId, onBack }: ReportLayoutProps) {
  const difficultyMeta = getDifficultyMeta(reportData.difficulty_position.level);
  const overallLevel = reportData.difficulty_position.label || difficultyMeta.label;
  const summaryParagraphs = getSummaryParagraphs(reportData.overall_summary);
  const adviceNote = getAdviceNote(reportData);
  const pdfExportId = exportId || reportData.paper_id || reportData.report_id;
  const reportWarnings = reportData.report_warnings || [];

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
              <strong>{reportData.difficulty_position.target_students || '未提供'}</strong>
            </div>
          </div>
        </header>

        <main className="report-body">
          {reportWarnings.length > 0 ? (
            <section className="report-warning-banner" aria-label="OCR warnings">
              <div className="report-warning-banner__header">
                <AlertCircle size={18} />
                <strong>OCR 识别提示</strong>
              </div>
              <ul className="report-warning-banner__list">
                {reportWarnings.map((warning, index) => (
                  <li key={`${index}-${warning.slice(0, 12)}`}>{warning}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="report-core-grid">
            <DifficultyPositioning data={reportData.difficulty_position} />
            <SixDimensionsRadar dimensions={reportData.dimensions} />
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

          <section className="report-section">
            <div className="report-section__header">
              <div>
                <span className="report-section__eyebrow">总体评价</span>
                <h2>整卷结论</h2>
              </div>
              <p>以正文报告块呈现总体判断，弱化普通卡片感，增强正式报告语境下的阅读节奏。</p>
            </div>

            <article className="report-prose-block">
              <span className="report-prose-block__note">报告正文</span>
              {summaryParagraphs.map((paragraph, index) => (
                <p key={`${index}-${paragraph.slice(0, 8)}`}>{paragraph}</p>
              ))}
            </article>
          </section>

          <section className="report-section report-section--light">
            <div className="report-section__header">
              <div>
                <span className="report-section__eyebrow">学习建议</span>
                <h2>后续训练建议</h2>
              </div>
              <p>采用编号建议列表，保留重点提示，但整体视觉层级低于核心结论与总体评价。</p>
            </div>

            <div className="report-advice-note">
              <strong>重点提示</strong>
              <p>{adviceNote}</p>
            </div>

            <ol className="report-advice-list">
              {reportData.recommendations.map((recommendation, index) => (
                <li key={`${index}-${recommendation.slice(0, 8)}`} className="report-advice-item">
                  <span className="report-advice-item__index">{String(index + 1).padStart(2, '0')}</span>
                  <p>{recommendation}</p>
                </li>
              ))}
            </ol>
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
