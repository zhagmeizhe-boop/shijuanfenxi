import { DifficultyPosition, QuestionDifficultyBucket } from '@/types/analysis';
import {
  formatScore,
  getDifficultyDescription,
  getDifficultyLabel,
  getDifficultyMeta,
  getDifficultyPositionSummary,
  REPORT_DIFFICULTY_META,
} from '@/components/report/reportMeta';

interface DifficultyPositioningProps {
  data: DifficultyPosition;
}

const QUESTION_BUCKET_ORDER = ['basic', 'medium', 'hard'];

function formatPercentage(value: number): string {
  return Number.isFinite(value) ? value.toFixed(1) : '0.0';
}

function normalizeQuestionShortLabel(value?: string): string {
  let text = String(value || '').trim();
  if (!text) {
    return '';
  }

  text = text.replace(/（/g, '(').replace(/）/g, ')').trim();
  const sectionMatch = text.match(/^[第\s]*[一二三四五六七八九十百千万零〇]+[部分卷题组]*[-－—]\s*(.+)$/u);
  if (sectionMatch) {
    text = sectionMatch[1].trim();
  }

  const bracketMatch = text.match(/^[([]\s*(.+?)\s*[\])]$/u);
  if (bracketMatch) {
    text = bracketMatch[1].trim();
  }

  const questionMatch = text.match(/^第\s*(.+?)\s*题$/u);
  if (questionMatch) {
    text = questionMatch[1].trim();
  }

  return text.replace(/[\s.．、，,。:：]+$/u, '').trim();
}

function getQuestionLabel(item: QuestionDifficultyBucket['questions'][number]): string {
  return (
    item.question_short_label ||
    normalizeQuestionShortLabel(item.question_display_label) ||
    normalizeQuestionShortLabel(item.question_label_raw) ||
    normalizeQuestionShortLabel(item.question_no) ||
    item.question_display_label ||
    item.question_label_raw ||
    item.question_no
  );
}

function getOrderedBuckets(buckets: QuestionDifficultyBucket[] = []): QuestionDifficultyBucket[] {
  return [...buckets].sort((a, b) => {
    const left = QUESTION_BUCKET_ORDER.indexOf(a.key);
    const right = QUESTION_BUCKET_ORDER.indexOf(b.key);
    return (left === -1 ? 99 : left) - (right === -1 ? 99 : right);
  });
}

export function DifficultyPositioning({ data }: DifficultyPositioningProps) {
  const config = getDifficultyMeta(data.level);
  const levelLabel = getDifficultyLabel(data.level, data.label);
  const description = getDifficultyDescription(data.level, data.description);
  const positionSummary = getDifficultyPositionSummary(
    data.level,
    data.position_summary || data.description || data.target_students,
  );
  const parentSummary =
    Array.isArray(data.parent_summary) && data.parent_summary.length >= 2
      ? data.parent_summary.slice(0, 2)
      : [
          `这张试卷整体定位为${levelLabel}，${positionSummary}`,
          '具体卡点要结合各维度得分看，重点关注计算准确率、看图找关系、读懂题意、整理条件、知识混合使用和连续推理里分数偏高的部分。',
        ];
  const distribution = data.question_distribution;
  const distributionBuckets = getOrderedBuckets(distribution?.buckets || []);
  const levels = Object.entries(REPORT_DIFFICULTY_META).map(([level, meta]) => ({
    level: Number(level),
    label: meta.label,
  }));

  return (
    <div
      className="report-difficulty-card"
      style={{
        borderColor: config.border,
      }}
    >
      <div className="report-card-heading">
        <span className="report-card-eyebrow">核心结论</span>
        <h3>难度定位</h3>
        <p>{description}</p>
      </div>

      <div className="report-difficulty-card__top">
        <div
          className="report-score-panel"
          style={{
            backgroundColor: config.surface,
            borderColor: config.border,
          }}
        >
          <span className="report-score-panel__label">试卷难度综合分</span>
          <div className="report-score-panel__value">
            <strong style={{ color: config.color }}>{formatScore(data.overall_score)}</strong>
            <small>/ 10</small>
          </div>
          <span
            className="report-level-pill"
            style={{
              color: config.color,
              backgroundColor: `${config.color}14`,
              borderColor: `${config.color}33`,
              alignSelf: 'flex-start',
            }}
          >
            {levelLabel}
          </span>
        </div>

        <div>
          <span className="report-card-note">家长速读</span>
          <div className="report-parent-summary">
            {parentSummary.map((item, index) => (
              <p key={`${index}-${item}`}>{item}</p>
            ))}
          </div>
        </div>
      </div>

      <div className="report-difficulty-scale">
        {levels.map((item) => {
          const isActive = item.level === data.level;

          return (
            <div
              key={item.level}
              className={`report-difficulty-scale__item${isActive ? ' is-active' : ''}`}
            >
              <div
                className="report-difficulty-scale__dot"
                style={{ backgroundColor: isActive ? config.color : undefined }}
              />
              <strong>{item.label}</strong>
              <span>Level {item.level}</span>
            </div>
          );
        })}
      </div>

      <div className="report-question-distribution">
        <div className="report-question-distribution__header">
          <div>
            <span className="report-card-note">题目难度结构</span>
            <h4>基础题 / 中等题 / 较难题</h4>
          </div>
          {distribution ? (
            <span className="report-question-distribution__total">
              共 {distribution.classified_count || 0} 道已归类题
            </span>
          ) : null}
        </div>

        {distributionBuckets.length > 0 ? (
          <div className="report-question-distribution__grid">
            {distributionBuckets.map((bucket) => {
              const questions = Array.isArray(bucket.questions) ? bucket.questions : [];
              const questionLabels = questions.map(getQuestionLabel).filter(Boolean);
              return (
                <div key={bucket.key} className="report-question-bucket">
                  <div className="report-question-bucket__summary">
                    <span>{bucket.label}</span>
                    <strong>{formatPercentage(bucket.percentage)}%</strong>
                    <small>{bucket.count} 道</small>
                  </div>
                  <p>{bucket.description || '暂无说明。'}</p>
                  <div className="report-question-bucket__questions">
                    {questionLabels.length > 0 ? questionLabels.join('、') : '暂无题目'}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="report-question-distribution__empty">暂无题目难度结构数据。</div>
        )}

      </div>
    </div>
  );
}
