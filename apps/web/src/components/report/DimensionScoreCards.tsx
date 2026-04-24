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
                  {dim.level_label}
                </span>
                {dim.warning ? (
                  <span className="report-inline-tag report-status-tag">复核提示</span>
                ) : null}
              </div>
            </div>

            <div className="report-dimension-card__score">
              <strong style={{ color }}>{formatScore(dim.score)}</strong>
              <span>/ 10</span>
            </div>

            <div className="report-dimension-card__meter">
              <div
                style={{
                  width: `${Math.max(0, Math.min(dim.score * 10, 100))}%`,
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

                    return (
                      <li key={itemKey}>
                        <strong>{questionLabel}</strong>
                        <span title={item.summary || item.reason}>
                          {summarizeEvidence(item.reason || item.summary, 54)}
                        </span>
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
