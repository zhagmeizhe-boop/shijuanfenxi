import type { DimensionScore } from '@/types/analysis';
import {
  formatScore,
  getDimensionMetaByCode,
  getDimensionOrder,
  summarizeEvidence,
} from '@/components/report/reportMeta';

interface DimensionScoreCardsProps {
  dimensions: DimensionScore[];
}

const COUNTED_QUESTION_AUDIT_MARKERS = ['依据标签：', '核心事实：', '依据来源：'];
const COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN = /^(L[1-5])\s+[^：:]{1,40}[：:]\s*(.+)$/u;

function formatCountedQuestionAnalysis(text: string): string {
  let normalized = text.replace(/\s+/g, ' ').trim();
  for (const marker of COUNTED_QUESTION_AUDIT_MARKERS) {
    normalized = normalized.split(marker, 1)[0].trim();
  }
  normalized = normalized.replace(/[。；;，,\s]+$/u, '').trim();

  const levelMatch = normalized.match(COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN);
  if (levelMatch) {
    normalized = `${levelMatch[1]}：${levelMatch[2].trim()}`;
  }
  return normalized.replace(/[。；;，,\s]+$/u, '').trim();
}

export function DimensionScoreCards({ dimensions }: DimensionScoreCardsProps) {
  const orderedDimensions = [...dimensions].sort(
    (left, right) => getDimensionOrder(left.code) - getDimensionOrder(right.code),
  );

  return (
    <div className="report-dimension-grid">
      {orderedDimensions.map((dim) => {
        const meta = getDimensionMetaByCode(dim.code);
        const color = meta?.color || '#66737d';
        const name = meta?.name || dim.name;
        const countedQuestions = (dim.counted_questions || []).slice(0, 3);
        const isNotCovered = dim.score_status === 'not_covered' || dim.level <= 0;

        return (
          <div
            key={dim.code}
            className="report-dimension-card"
            style={{ borderTopColor: color }}
          >
            <div className="report-dimension-card__header">
              <div className="report-dimension-card__title">
                <h3>{name}</h3>
                <p>{dim.code.toUpperCase()}</p>
              </div>

              <div className="report-dimension-card__badges">
                <span
                  className="report-level-pill"
                  style={{
                    color,
                    backgroundColor: `${color}14`,
                    borderColor: `${color}33`,
                  }}
                >
                  {isNotCovered ? '未覆盖' : dim.level_label}
                </span>
                {dim.warning && !isNotCovered ? (
                  <span className="report-inline-tag report-status-tag">评分提示</span>
                ) : null}
              </div>
            </div>

            <div className="report-dimension-card__score">
              {isNotCovered ? (
                <strong style={{ color }}>未覆盖</strong>
              ) : (
                <>
                  <strong style={{ color }}>{formatScore(dim.score)}</strong>
                  <span>/ 10</span>
                </>
              )}
            </div>

            <div className="report-dimension-card__meter">
              <div
                style={{
                  width: isNotCovered ? '0%' : `${Math.max(0, Math.min(dim.score * 10, 100))}%`,
                  backgroundColor: color,
                }}
              />
            </div>

            <div className="report-dimension-card__evidence">
              <span className="report-dimension-card__label">评分依据摘要</span>
              <p title={dim.evidence}>{summarizeEvidence(dim.evidence)}</p>
            </div>

            {countedQuestions.length > 0 ? (
              <div className="report-dimension-card__questions">
                <span className="report-dimension-card__label">计入题目</span>
                <ul className="report-counted-question-list">
                  {countedQuestions.map((item, index) => {
                    const questionLabel =
                      item.question_display_label || item.question_label_raw || item.question_no;
                    const itemKey = `${dim.code}-${index}-${questionLabel}-${item.summary}`;
                    const compactReason = formatCountedQuestionAnalysis(
                      item.reason || item.summary || item.full_reason || '',
                    );
                    const fullReason = formatCountedQuestionAnalysis(
                      item.full_reason || item.reason || item.summary || '',
                    );
                    const tooltipId = `counted-question-${dim.code}-${index}`;

                    return (
                      <li key={itemKey}>
                        <strong>{questionLabel}</strong>
                        <span
                          className="report-counted-question-summary"
                          tabIndex={fullReason ? 0 : undefined}
                          aria-describedby={fullReason ? tooltipId : undefined}
                        >
                          {summarizeEvidence(compactReason, 54)}
                        </span>
                        {fullReason ? (
                          <>
                            <span
                              id={tooltipId}
                              role="tooltip"
                              className="report-counted-question-tooltip"
                            >
                              {fullReason}
                            </span>
                            <span className="report-counted-question-print">{fullReason}</span>
                          </>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
