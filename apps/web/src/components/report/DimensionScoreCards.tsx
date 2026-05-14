import type { CountedQuestion, DimensionScore } from '@/types/analysis';
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
const COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN = /^(L[1-5])(?:\s+[^：:]{1,40})?[：:]\s*(.+)$/u;
const COUNTED_QUESTION_SCORE_DESCRIPTOR_PATTERN = /^(\d+(?:\.\d+)?)分[：:]\s*(.+)$/u;
const DIM1_DIFFICULTY_LABELS: Record<string, string> = {
  L1: '简单（2.0）',
  L2: '较易（4.0）',
  L3: '中等（6.0）',
  L4: '较难（8.0）',
  L5: '困难（9.5）',
};

function buildDim1ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '说明本卷计算要求很高，包含较强的多步、结构化或拓展计算，对综合计算能力要求突出。';
  } else if (scoreValue >= 8) {
    explanation = '说明本卷计算难度较高，计算题和应用题中的核心计算都会拉开学生差距。';
  } else if (scoreValue >= 6) {
    explanation = '说明本卷有一定计算难度，除准确率外，也考查多步运算和常见转化。';
  } else if (scoreValue >= 4) {
    explanation = '说明本卷计算难度整体偏常规，重点考查校内计算的熟练度和稳定性。';
  } else {
    explanation = '说明本卷计算要求以基础运算为主，主要看基本规则掌握和计算准确率。';
  }
  return `计算维度，综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
}

function buildDim2ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '说明本卷几何与空间要求很高，包含高强度空间重构、多视图或高阶几何模型。';
  } else if (scoreValue >= 8) {
    explanation = '说明本卷几何难度较高，复合图形、隐含关系或空间转换会明显拉开差距。';
  } else if (scoreValue >= 6) {
    explanation = '说明本卷有一定几何与空间难度，除基本公式外，也考查图形关系整理和模型识别。';
  } else if (scoreValue >= 4) {
    explanation = '说明本卷以常规图形关系为主，重点考查读图准确性和单步空间转化。';
  } else {
    explanation = '说明本卷主要覆盖基础识图和直接几何公式，重点看图形概念和基本关系是否掌握。';
  }
  return `几何直观与空间想象维度，综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
}

function buildDim3ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '说明本卷读题场景理解与信息重构要求很高，包含复杂规则、多源材料、嵌套关系或自建表示。';
  } else if (scoreValue >= 8) {
    explanation = '说明本卷读题与信息组织难度较高，分散条件、规则理解、隐含关系或表示转化会拉开差距。';
  } else if (scoreValue >= 6) {
    explanation = '说明本卷有一定场景理解和信息整理难度，需要读懂题意规则、筛选多条条件并建立数量关系。';
  } else if (scoreValue >= 4) {
    explanation = '说明本卷以常规场景理解和信息转化为主，重点看能否把题意条件对应到算式或关系。';
  } else {
    explanation = '说明本卷信息处理要求较基础，主要是直接读懂题干并定位有效条件。';
  }
  return `信息提取与转化维度，综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
}

function buildDim4ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '说明本卷题目创新要求很高，核心题多需要开放探索、全局构造或最优/唯一性证明。';
  } else if (scoreValue >= 8) {
    explanation = '说明本卷实践创新要求较高，较多题不能直接套模板，需要构造中间量、分类回查或重组关系。';
  } else if (scoreValue >= 6) {
    explanation = '说明本卷有一定变式要求，部分题需要一次策略转换、模型迁移或关系重排。';
  } else if (scoreValue >= 4) {
    explanation = '说明本卷主要是轻度变式，通常在常规模板上作少量调整即可推进。';
  } else {
    explanation = '说明本卷以基础模板题为主，主要考查直接套用和常规迁移。';
  }
  return `实践创新综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
}

function buildDim5ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '说明本卷知识跨度很高，核心题多进入高思导引超越篇或跨专题竞赛层级，对竞赛型知识储备要求很强。';
  } else if (scoreValue >= 8) {
    explanation = '说明本卷知识广度较高，较多题目需要高思导引专题或跨专题知识，适合区分高水平学生。';
  } else if (scoreValue >= 6) {
    explanation = '说明本卷有一定知识拓展，除校内核心知识外，还覆盖入门专题或部分高思导引知识。';
  } else if (scoreValue >= 4) {
    explanation = '说明本卷主要落在小学高年级校内核心知识，少量题目涉及校内延伸。';
  } else {
    explanation = '说明本卷以基础校内知识为主，主要考查基本概念和直接应用。';
  }
  return `知识广度综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
}

function buildDim6ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '说明本卷逻辑链条很长，题目往往需要多次推出中间结论，并让多个条件同时对上。';
  } else if (scoreValue >= 8) {
    explanation = '说明本卷逻辑链条较长，较多题需要处理多轮变化、倒推或多种情况。';
  } else if (scoreValue >= 6) {
    explanation = '说明本卷有一定逻辑推进要求，部分题需要连续推出多个中间结论。';
  } else if (scoreValue >= 4) {
    explanation = '说明本卷逻辑链条整体偏常规，少量题需要把前一步结果接到下一步条件中。';
  } else {
    explanation = '说明本卷多数题的推理链较短，通常一步或直接条件判断即可完成。';
  }
  return `综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
}

function formatDimensionEvidence(dim: DimensionScore): string {
  if (dim.code === 'dim1') {
    if (dim.score_status === 'not_covered' || dim.level <= 0) {
      return dim.evidence;
    }
    return buildDim1ScoreOverview(dim.score);
  }

  if (dim.code === 'dim2') {
    if (dim.score_status === 'not_covered' || dim.level <= 0) {
      return dim.evidence;
    }
    return buildDim2ScoreOverview(dim.score);
  }

  if (dim.code === 'dim3') {
    if (dim.score_status === 'not_covered' || dim.level <= 0) {
      return dim.evidence;
    }
    return buildDim3ScoreOverview(dim.score);
  }

  if (dim.code === 'dim6') {
    if (dim.score_status === 'not_covered' || dim.level <= 0) {
      return dim.evidence;
    }
    return buildDim6ScoreOverview(dim.score);
  }

  if (dim.code === 'dim5') {
    if (dim.score_status === 'not_covered' || dim.level <= 0) {
      return dim.evidence;
    }
    return buildDim5ScoreOverview(dim.score);
  }

  if (dim.code !== 'dim4') {
    return dim.evidence;
  }

  if (dim.score_status === 'not_covered' || dim.level <= 0) {
    return dim.evidence;
  }

  return buildDim4ScoreOverview(dim.score);
}

function inferLevelCodeFromScore(score?: number): string {
  if (typeof score !== 'number' || !Number.isFinite(score)) {
    return '';
  }
  if (score >= 9) {
    return 'L5';
  }
  if (score >= 8) {
    return 'L4';
  }
  if (score >= 6) {
    return 'L3';
  }
  if (score >= 4) {
    return 'L2';
  }
  return 'L1';
}

type CountedQuestionDifficultyFields = Pick<
  CountedQuestion,
  'difficulty_label' | 'level_code' | 'score'
>;

function formatCountedQuestionDifficulty(item?: CountedQuestionDifficultyFields): string {
  const explicitLabel = item?.difficulty_label?.trim();
  if (explicitLabel) {
    return explicitLabel;
  }

  const levelCode = item?.level_code?.trim().toUpperCase();
  if (levelCode && DIM1_DIFFICULTY_LABELS[levelCode]) {
    return DIM1_DIFFICULTY_LABELS[levelCode];
  }

  const inferredLevel = inferLevelCodeFromScore(item?.score);
  return inferredLevel ? DIM1_DIFFICULTY_LABELS[inferredLevel] : '';
}

function formatCountedQuestionAnalysis(text: string, item?: CountedQuestion): string {
  let normalized = text.replace(/\s+/g, ' ').trim();
  for (const marker of COUNTED_QUESTION_AUDIT_MARKERS) {
    normalized = normalized.split(marker, 1)[0].trim();
  }
  normalized = normalized.replace(/[。；;，,\s]+$/u, '').trim();

  const difficultyLabel = formatCountedQuestionDifficulty(item);
  const levelMatch = normalized.match(COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN);
  if (levelMatch) {
    normalized = `${difficultyLabel || DIM1_DIFFICULTY_LABELS[levelMatch[1]] || levelMatch[1]}：${levelMatch[2].trim()}`;
  }

  const scoreMatch = normalized.match(COUNTED_QUESTION_SCORE_DESCRIPTOR_PATTERN);
  if (scoreMatch) {
    const score = Number(scoreMatch[1]);
    const fallbackLabel = formatCountedQuestionDifficulty({ score });
    normalized = `${difficultyLabel || fallbackLabel || scoreMatch[1]}：${scoreMatch[2].trim()}`;
  }
  return normalized.replace(/[。；;，,\s]+$/u, '').trim();
}

function cleanDim5DisplayText(value: string | undefined): string {
  return (value || '')
    .replace(/\s+/g, ' ')
    .replace(/竞赛数学导引/g, '高思导引')
    .replace(/奥数/g, '高思导引')
    .trim();
}

function trimTrailingPunctuation(text: string): string {
  return text.replace(/[。；;，,\s]+$/u, '').trim();
}

function cleanDim4DisplayText(value: string | undefined): string {
  return (value || '').replace(/\s+/g, ' ').trim();
}

function formatDim4CountedQuestionText(item: CountedQuestion, fallbackText: string): string {
  const difficultyLabel = formatCountedQuestionDifficulty(item);
  const point = cleanDim4DisplayText(item.knowledge_point_text);
  const practiceLevel = cleanDim4DisplayText(item.practice_level_text);
  const reason = trimTrailingPunctuation(cleanDim4DisplayText(item.score_reason));

  if (difficultyLabel && reason && (point || practiceLevel)) {
    let target: string;
    if (point && practiceLevel) {
      target = `本题是${point}中的${practiceLevel}`;
    } else if (point) {
      target = `本题是${point}的实践创新题`;
    } else {
      target = `本题属于${practiceLevel}题`;
    }
    return `${difficultyLabel}：${target}；${reason}。`;
  }

  return formatCountedQuestionAnalysis(fallbackText, item);
}

function formatDim5CountedQuestionText(item: CountedQuestion, fallbackText: string): string {
  const difficultyLabel = formatCountedQuestionDifficulty(item);
  const source = cleanDim5DisplayText(item.knowledge_source_text);
  const point = cleanDim5DisplayText(item.knowledge_point_text);
  const reason = trimTrailingPunctuation(cleanDim5DisplayText(item.score_reason));

  if (difficultyLabel && reason && (source || point)) {
    let target: string;
    if (source && point) {
      target = `本题属于${source}的${point}`;
    } else if (source) {
      target = `本题属于${source}知识范围`;
    } else {
      target = `本题主要考查${point}`;
    }
    return `${difficultyLabel}：${target}；${reason}。`;
  }

  return cleanDim5DisplayText(formatCountedQuestionAnalysis(fallbackText, item));
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
              <span className="report-dimension-card__label">得分概览</span>
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
                    const compactSource = item.reason || item.summary || item.full_reason || '';
                    const fullSource = item.full_reason || item.reason || item.summary || '';
                    const compactReason =
                      dim.code === 'dim4'
                        ? formatDim4CountedQuestionText(item, compactSource)
                        : dim.code === 'dim5'
                        ? formatDim5CountedQuestionText(item, compactSource)
                        : formatCountedQuestionAnalysis(compactSource, item);
                    const fullReason =
                      dim.code === 'dim4'
                        ? formatDim4CountedQuestionText(item, fullSource)
                        : dim.code === 'dim5'
                        ? formatDim5CountedQuestionText(item, fullSource)
                        : formatCountedQuestionAnalysis(fullSource, item);
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
