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
    explanation = '说明这张试卷在学生读题理解题意上设置了较高难度，不少题目需要完整读懂多条规则、多阶段过程或复杂图文关系。';
  } else if (scoreValue >= 8) {
    explanation = '说明这张试卷在学生读题理解题意上设置了明显难度，部分题目的场景相对复杂，学生需要先理清对象、阶段、规则或图文关系。';
  } else if (scoreValue >= 6) {
    explanation = '说明这张试卷在学生读题理解题意上设置了一定难度，部分题目需要先读懂关键问法、比较标准或简单规则。';
  } else if (scoreValue >= 4) {
    explanation = '说明这张试卷在学生读题和理解题意上有常规要求，部分题目需要分清对象、顺序或图文对应关系。';
  } else {
    explanation = '说明这张试卷在学生读题和理解题意上的要求比较基础，大多数题目读完后能较快明白题目在说什么。';
  }
  return `场景理解复杂度维度，综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
}

function buildDim4ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '说明本卷在解题思路上难度很高。孩子做核心题时，通常不能只按常规步骤推进，需要先找到关键突破口，再持续检查每一步是否和题目条件一致。';
  } else if (scoreValue >= 8) {
    explanation = '说明本卷在解题思路上有较明显难度。孩子做这类题时，往往需要先把条件之间的关系理清楚，再选择合适的切入方式逐步推进。';
  } else if (scoreValue >= 6) {
    explanation = '说明本卷在解题思路上有一定难度。部分题目不是读完就能直接下手，需要孩子先整理已知条件和目标之间的关系，再按较清晰的步骤推进。';
  } else if (scoreValue >= 4) {
    explanation = '说明本卷在解题思路上的要求整体偏常规。多数题目读懂后可以沿常见思路完成，少量题需要先做简单整理再下手。';
  } else {
    explanation = '说明本卷在解题思路上的要求比较基础。多数题目读懂题意后，可以直接找到主要关系并完成解答。';
  }
  return `综合得分为 ${formatScore(scoreValue)} 分，${explanation}`;
}

function buildDim5ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '说明本卷知识门槛很高，核心题多接近六年级奥数较难题、小升初压轴题或七年级核心前置知识。';
  } else if (scoreValue >= 8) {
    explanation = '说明本卷知识广度较高，较多题目需要五六年级奥数典型方法或七年级基础前置知识。';
  } else if (scoreValue >= 6) {
    explanation = '说明本卷有一定知识拓展，除校内核心知识外，还覆盖校内综合或三四年级奥数入门模型。';
  } else if (scoreValue >= 4) {
    explanation = '说明本卷主要落在四至六年级校内核心知识，常规两三步应用、比例、图形公式等是主要要求。';
  } else {
    explanation = '说明本卷以一至三年级校内基础知识为主，主要考查基本概念、基础计算和直接应用。';
  }
  return `知识广度综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
}

function buildDim6ScoreOverview(score: number): string {
  const scoreValue = Number.isFinite(score) ? score : 0;
  let explanation: string;
  if (scoreValue >= 9) {
    explanation = '这张试卷有少量解题链条很长的压轴题，通常要连续推进 5 步以上，并检查多个条件。';
  } else if (scoreValue >= 8) {
    explanation = '这张试卷不少题解题链条较长，通常要连续推进 3-4 步，并穿插分类、倒推或回查。';
  } else if (scoreValue >= 6) {
    explanation = '这张试卷部分题解题链条有一定长度，通常要把前后条件接起来推进 2-4 步。';
  } else if (scoreValue >= 4) {
    explanation = '这张试卷整体解题链条偏短，少量题需要 1-2 步衔接。';
  } else {
    explanation = '这张试卷多数题解题链条很短，通常读懂条件后一步判断即可。';
  }
  return `逻辑推理综合得分 ${formatScore(scoreValue)} 分，${explanation}`;
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
    .replace(/竞赛数学导引/g, '奥数')
    .replace(/高思导引/g, '奥数')
    .trim();
}

function trimTrailingPunctuation(text: string): string {
  return text.replace(/[。；;，,\s]+$/u, '').trim();
}

function cleanDim4DisplayText(value: string | undefined): string {
  return (value || '').replace(/\s+/g, ' ').trim();
}

function isProbablyEnglishDisplayText(value: string): boolean {
  const text = cleanDim4DisplayText(value);
  if (!text) {
    return false;
  }

  const englishWords = text.match(/[A-Za-z][A-Za-z'-]{2,}/g) || [];
  if (englishWords.length === 0) {
    return false;
  }

  const cjkCount = (text.match(/[\u4e00-\u9fff]/g) || []).length;
  const asciiLetterCount = (text.match(/[A-Za-z]/g) || []).length;
  const stopwords = new Set([
    'and',
    'are',
    'but',
    'either',
    'for',
    'from',
    'into',
    'requires',
    'that',
    'the',
    'then',
    'this',
    'through',
    'to',
    'with',
  ]);
  const stopwordHits = englishWords.filter((word) => stopwords.has(word.toLowerCase())).length;
  const hasEnglishSentence = englishWords.length >= 4 || stopwordHits >= 2;

  if (cjkCount === 0) {
    return hasEnglishSentence || asciiLetterCount >= 20;
  }

  return asciiLetterCount >= 30 && asciiLetterCount > Math.max(12, cjkCount * 2.5) && stopwordHits >= 1;
}

function dim4FallbackScoreReason(item: CountedQuestion): string {
  const levelCode = item.level_code?.trim().toUpperCase() || inferLevelCodeFromScore(item.score);
  if (levelCode === 'L5') {
    return '难点在于要从全局构造或证明可行性，局部算对还不够';
  }
  if (levelCode === 'L4') {
    return '难点在于不能直接套模板，需要构造中间量、分类回查或重组关系';
  }
  if (levelCode === 'L3') {
    return '难点在于要完成一次策略转换或模型迁移，再沿新关系推进';
  }
  if (levelCode === 'L2') {
    return '难点在于要在常规模板上做少量调整，分清变化后的条件';
  }
  return '难点在于要识别基础模板，并按常规关系直接推进';
}

function formatDim4CountedQuestionText(item: CountedQuestion, fallbackText: string): string {
  const difficultyLabel = formatCountedQuestionDifficulty(item);
  const point = cleanDim4DisplayText(item.knowledge_point_text);
  const practiceLevel = cleanDim4DisplayText(item.practice_level_text);
  const rawReason = trimTrailingPunctuation(cleanDim4DisplayText(item.score_reason));
  const reason = rawReason && !isProbablyEnglishDisplayText(rawReason)
    ? rawReason
    : dim4FallbackScoreReason(item);

  if (difficultyLabel && reason && (point || practiceLevel)) {
    let target: string;
    if (point && practiceLevel) {
      target = `本题是${point}中的${practiceLevel}`;
    } else if (point) {
      target = `本题是${point}的建模解题题`;
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

function dim6StudentActionFromTask(task: string, evidence: string): string {
  if (task.includes('周期')) {
    return '找准循环节和目标位置，再把余数对应回具体状态';
  }
  if (task.includes('方案')) {
    return '先列出可行方案，再按同一个标准比较，并检查限制条件是否都满足';
  }
  if (task.includes('情况')) {
    return '把可能情况分完整，逐一代回条件检查，避免漏掉或重复';
  }
  if (task.includes('倒推') || task.includes('还原')) {
    return '从结果往前还原每一步，再检查是否符合原条件';
  }
  if (task.includes('条件同时')) {
    return '同时盯住多个条件，先缩小范围，再确认每个条件都成立';
  }
  if (task.includes('变化') || task.includes('阶段')) {
    return '按阶段记录变化，把上一阶段的结果接到下一阶段条件中';
  }
  if (task.includes('中间结论') || evidence.includes('前一步')) {
    return '把前一步得到的结果接到下一步条件里，连续推出中间结论';
  }
  return '把已有条件一步步接起来，并在最后检查结论是否符合题意';
}

function cleanDim6StudentAction(value: string): string {
  let text = trimTrailingPunctuation(value.replace(/\s+/g, ' ').trim());
  const forbidden = ['reasoning_role', 'chain_span', 'constraint_coupling', '高阶收束', '逻辑负担', '依据是'];
  if (!text || forbidden.some((term) => text.includes(term))) {
    return '把已有条件一步步接起来，并在最后检查结论是否符合题意';
  }

  const prefixes = ['学生需要', '题目需要', '需要', '要', '难点在于', '这题难在', '本题难在'];
  let changed = true;
  while (changed) {
    changed = false;
    for (const prefix of prefixes) {
      if (text.startsWith(prefix)) {
        text = trimTrailingPunctuation(text.slice(prefix.length).trim());
        changed = true;
      }
    }
  }
  return text || '把已有条件一步步接起来，并在最后检查结论是否符合题意';
}

function dim6ChainDescriptionFromItem(item: CountedQuestion): string {
  const chainSpan = String((item as CountedQuestion & { chain_span?: string }).chain_span || '').trim();
  if (chainSpan === '1') {
    return '很短，通常一步判断即可';
  }
  if (chainSpan === '2') {
    return '较短，大约需要连续推进 1-2 步';
  }
  if (chainSpan === '3-4') {
    return '较长，大约需要连续推进 3-4 步';
  }
  if (chainSpan === '5+') {
    return '很长，通常需要连续推进 5 步以上';
  }

  const levelCode = item.level_code?.trim().toUpperCase() || inferLevelCodeFromScore(item.score);
  if (levelCode === 'L5') {
    return '很长，通常需要多步推进，并伴随分类、倒推、回查或多条件检查';
  }
  if (levelCode === 'L4') {
    return '较长，通常需要多步推进，并伴随分类、倒推、回查或多条件检查';
  }
  if (levelCode === 'L3') {
    return '有一定长度，通常需要把前后条件连续接起来';
  }
  if (levelCode === 'L2') {
    return '较短，通常需要一两步衔接';
  }
  return '很短，通常一步判断即可';
}

function formatDim6CountedQuestionText(item: CountedQuestion, fallbackText: string): string {
  const normalized = formatCountedQuestionAnalysis(fallbackText, item);
  if (!normalized) {
    return normalized;
  }
  if (normalized.includes('这题的解题链条') && normalized.includes('学生需要')) {
    return normalized;
  }

  const currentStyleMatch = normalized.match(/^(.+?)：这题难在(.+?)；学生需要(.+)$/u);
  if (currentStyleMatch) {
    const [, difficulty, , action] = currentStyleMatch;
    return `${difficulty}：这题的解题链条${dim6ChainDescriptionFromItem(
      item,
    )}；学生需要${action.trim()}`;
  }

  const oldStyleMatch = normalized.match(/^(.+?)：本题逻辑链条难在(.+?)；依据是(.+)$/u);
  if (oldStyleMatch) {
    const [, difficulty, task, evidence] = oldStyleMatch;
    return `${difficulty}：这题的解题链条${dim6ChainDescriptionFromItem(
      item,
    )}；学生需要${dim6StudentActionFromTask(
      task,
      evidence,
    )}`;
  }

  const action = cleanDim6StudentAction(normalized);
  const difficultyLabel = formatCountedQuestionDifficulty(item);
  if (difficultyLabel && action !== normalized) {
    return `${difficultyLabel}：这题的解题链条${dim6ChainDescriptionFromItem(
      item,
    )}；学生需要${action}`;
  }
  return normalized;
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
                        : dim.code === 'dim6'
                        ? formatDim6CountedQuestionText(item, compactSource)
                        : formatCountedQuestionAnalysis(compactSource, item);
                    const fullReason =
                      dim.code === 'dim4'
                        ? formatDim4CountedQuestionText(item, fullSource)
                        : dim.code === 'dim5'
                        ? formatDim5CountedQuestionText(item, fullSource)
                        : dim.code === 'dim6'
                        ? formatDim6CountedQuestionText(item, fullSource)
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
