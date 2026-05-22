import { SixDimensions } from '@/types/analysis';

export interface ReportDimensionMeta {
  code: string;
  field: keyof SixDimensions;
  name: string;
  shortName: string;
  chartName: string;
  color: string;
}

export interface ReportDifficultyMeta {
  label: string;
  color: string;
  surface: string;
  border: string;
  description: string;
  positionSummary: string;
  targetStudents: string;
}

export const REPORT_DIMENSIONS: ReportDimensionMeta[] = [
  {
    code: 'dim1',
    field: 'computation',
    name: '数学运算',
    shortName: '数学运算',
    chartName: '数学运算',
    color: '#295d8a',
  },
  {
    code: 'dim2',
    field: 'concept',
    name: '几何直观与空间想象',
    shortName: '几何直观',
    chartName: '几何直观\n与空间想象',
    color: '#3d7a85',
  },
  {
    code: 'dim3',
    field: 'logic',
    name: '场景理解复杂度',
    shortName: '场景理解',
    chartName: '场景理解\n复杂度',
    color: '#6f7d48',
  },
  {
    code: 'dim4',
    field: 'spatial',
    name: '建模解题复杂度',
    shortName: '建模解题',
    chartName: '建模解题\n复杂度',
    color: '#8a6842',
  },
  {
    code: 'dim5',
    field: 'application',
    name: '知识广度',
    shortName: '知识广度',
    chartName: '知识广度',
    color: '#8b5754',
  },
  {
    code: 'dim6',
    field: 'innovation',
    name: '逻辑链条',
    shortName: '逻辑链条',
    chartName: '逻辑链条',
    color: '#5f567c',
  },
];

export const REPORT_DIFFICULTY_META: Record<number, ReportDifficultyMeta> = {
  1: {
    label: '基础卷',
    color: '#3f7a57',
    surface: '#f1f7f2',
    border: '#c9ddce',
    description: '整体更强调基础概念与常规运算，适合夯实基本能力。',
    positionSummary: '课内基础巩固型试卷，主要看孩子基础概念和常规计算是否过关。',
    targetStudents: '适合基础薄弱、需要巩固基本概念的学生。',
  },
  2: {
    label: '提升卷',
    color: '#356a7c',
    surface: '#eef5f8',
    border: '#c7d9e0',
    description: '注重知识覆盖、基本应用和稳定解题能力，适合从课内掌握走向稳步提升。',
    positionSummary: '课内核心提升型试卷，主要看孩子能不能把学过的知识稳定用出来。',
    targetStudents: '适合基础一般、希望从课内掌握走向稳定提升的学生。',
  },
  3: {
    label: '拔高卷',
    color: '#8a6b2d',
    surface: '#fbf6ea',
    border: '#e6d9b4',
    description: '强调综合运用、方法迁移和拔高训练，适合基础较好的学生。',
    positionSummary: '校内期中期末考试难度试卷，题目有一定变化，适合检验孩子能否稳定拿到中高分。',
    targetStudents: '适合基础较好、需要强化综合运用和拔高训练的学生。',
  },
  4: {
    label: '选拔卷',
    color: '#8b5a3c',
    surface: '#fbf2ee',
    border: '#e6cfc1',
    description: '面向选拔区分场景，重视复杂问题解决、策略迁移与稳定性。',
    positionSummary: '小升初分班考难度试卷，题目更绕、步骤更多，用来拉开学生差距。',
    targetStudents: '适合基础扎实、需要面向选拔场景提升综合稳定性的学生。',
  },
  5: {
    label: '竞赛卷',
    color: '#6b557f',
    surface: '#f4f0f8',
    border: '#d9d0e6',
    description: '整体强度高，突出竞赛型思维、跨模块综合和高难度解题技巧。',
    positionSummary: '奥数杯赛竞赛难度试卷，难度很高，适合挑战高难题和竞赛题。',
    targetStudents: '适合成绩优秀、准备挑战竞赛或高强度选拔的学生。',
  },
};

const DIMENSION_BY_CODE = new Map(REPORT_DIMENSIONS.map((item) => [item.code, item]));
const DIMENSION_BY_FIELD = new Map(REPORT_DIMENSIONS.map((item) => [item.field, item]));

export function getDimensionMetaByCode(code: string): ReportDimensionMeta | undefined {
  return DIMENSION_BY_CODE.get(code);
}

export function getDimensionMetaByField(
  field: keyof SixDimensions,
): ReportDimensionMeta | undefined {
  return DIMENSION_BY_FIELD.get(field);
}

export function getDimensionOrder(code: string): number {
  const index = REPORT_DIMENSIONS.findIndex((item) => item.code === code);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

export function getDifficultyMeta(level: number): ReportDifficultyMeta {
  return REPORT_DIFFICULTY_META[level] ?? REPORT_DIFFICULTY_META[3];
}

export function getDifficultyLabel(level: number, fallback?: string): string {
  return REPORT_DIFFICULTY_META[level]?.label ?? fallback ?? getDifficultyMeta(level).label;
}

export function getDifficultyDescription(level: number, fallback?: string): string {
  return REPORT_DIFFICULTY_META[level]?.description ?? fallback ?? getDifficultyMeta(level).description;
}

export function getDifficultyPositionSummary(level: number, fallback?: string): string {
  return REPORT_DIFFICULTY_META[level]?.positionSummary ?? fallback ?? '未提供';
}

export function getDifficultyTargetStudents(level: number, fallback?: string): string {
  return REPORT_DIFFICULTY_META[level]?.targetStudents ?? fallback ?? '未提供';
}

export function formatGeneratedAt(value?: string): string {
  if (!value) {
    return '未提供';
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed);
}

export function summarizeEvidence(text: string, maxLength = 72): string {
  const normalized = text.replace(/\s+/g, ' ').trim();

  if (!normalized) {
    return '暂无评分依据说明。';
  }

  if (normalized.length <= maxLength) {
    return normalized;
  }

  return `${normalized.slice(0, maxLength).trimEnd()}…`;
}

export function formatScore(value: number, digits = 1): string {
  return Number.isFinite(value) ? value.toFixed(digits) : '0.0';
}

export function getRadarValues(
  dimensions: SixDimensions,
  notCoveredCodes: ReadonlySet<string> = new Set(),
): (number | null)[] {
  return REPORT_DIMENSIONS.map((item) => {
    if (notCoveredCodes.has(item.code)) {
      return null;
    }

    const rawValue = dimensions[item.field];
    return Number.isFinite(rawValue) ? rawValue : 0;
  });
}
