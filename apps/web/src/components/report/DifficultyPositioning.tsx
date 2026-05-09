import { DifficultyPosition } from '@/types/analysis';
import {
  formatScore,
  getDifficultyDescription,
  getDifficultyLabel,
  getDifficultyMeta,
  getDifficultyTargetStudents,
  REPORT_DIFFICULTY_META,
} from '@/components/report/reportMeta';

interface DifficultyPositioningProps {
  data: DifficultyPosition;
}

export function DifficultyPositioning({ data }: DifficultyPositioningProps) {
  const config = getDifficultyMeta(data.level);
  const levelLabel = getDifficultyLabel(data.level, data.label);
  const description = getDifficultyDescription(data.level, data.description);
  const targetStudents = getDifficultyTargetStudents(data.level, data.target_students);
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
          <span className="report-score-panel__label">综合分</span>
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
          <span className="report-card-note">结论摘要</span>
          <p style={{ margin: '10px 0 0', color: '#5d6a72', lineHeight: 1.85 }}>
            {description}
          </p>

          <div className="report-target-block">
            <span>目标学生</span>
            <p>{targetStudents}</p>
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
    </div>
  );
}
