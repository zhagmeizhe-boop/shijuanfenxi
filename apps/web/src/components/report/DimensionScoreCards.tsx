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
const DIM4_LEVEL_COUNT_SEGMENT_PATTERN = /(?:^|[、，,\s])L[1-5]\s*\d+\s*道/u;

function getBreakdownNumber(breakdown: Record<string, unknown> | undefined, key: string): number | null {
  const value = breakdown?.[key];
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function getDim4LevelCountTotal(breakdown: Record<string, unknown> | undefined): number | null {
  const levelCounts = breakdown?.level_counts;
  if (!levelCounts || typeof levelCounts !== 'object' || Array.isArray(levelCounts)) {
    return null;
  }

  let total = 0;
  let hasCount = false;
  for (const level of ['L1', 'L2', 'L3', 'L4', 'L5']) {
    const raw = (levelCounts as Record<string, unknown>)[level];
    const value = typeof raw === 'number' ? raw : typeof raw === 'string' ? Number(raw) : NaN;
    if (Number.isFinite(value)) {
      total += value;
      hasCount = true;
    }
  }
  return hasCount ? total : null;
}

function cleanDim4EvidenceText(text: string): string {
  const segments = text
    .replace(/\s+/g, ' ')
    .trim()
    .split(/[；;]/u)
    .map((segment) => segment.replace(/[。；;，,\s]+$/u, '').trim())
    .filter(Boolean)
    .filter((segment) => !DIM4_LEVEL_COUNT_SEGMENT_PATTERN.test(segment));

  if (segments.length === 0) {
    return text.replace(/\s+/g, ' ').trim();
  }
  return `${segments.join('；')}。`;
}

function formatDimensionEvidence(dim: DimensionScore): string {
  if (dim.code !== 'dim4') {
    return dim.evidence;
  }

  const breakdown = dim.score_breakdown;
  const includedCount =
    getBreakdownNumber(breakdown, 'valid_score_question_count') ??
    getDim4LevelCountTotal(breakdown);

  if (includedCount !== null) {
    const parts = [`共 ${includedCount} 道题纳入实践创新均分`];
    if (dim.score_status !== 'not_covered' && dim.level > 0) {
      parts.push(`题级均分 ${formatScore(dim.score)} 分`);
    }

    const reviewCount =
      getBreakdownNumber(breakdown, 'review_count') ??
      getBreakdownNumber(breakdown, 'review_question_count');
    const unscoredCount = getBreakdownNumber(breakdown, 'unscored_question_count');

    if (reviewCount !== null && reviewCount > 0) {
      parts.push(`人工复核 ${reviewCount} 道未计入`);
    }
    if (unscoredCount !== null && unscoredCount > 0) {
      parts.push(`缺少合法题级分 ${unscoredCount} 道未计入`);
    }

    return `${parts.join('；')}。`;
  }

  return cleanDim4EvidenceText(dim.evidence);
}

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
        const displayEvidence = formatDimensionEvidence(dim);

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
              <p title={displayEvidence}>{summarizeEvidence(displayEvidence)}</p>
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
