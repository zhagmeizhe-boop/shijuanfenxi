import { DifficultyPosition, SixDimensions } from '@/types/analysis';

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
    name: '信息提取与转化',
    shortName: '信息提取',
    chartName: '信息提取\n与转化',
    color: '#6f7d48',
  },
  {
    code: 'dim4',
    field: 'spatial',
    name: '实践创新',
    shortName: '实践创新',
    chartName: '实践创新',
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
    name: '逻辑链条长度',
    shortName: '逻辑链条',
    chartName: '逻辑链条\n长度',
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
  },
  2: {
    label: '常规卷',
    color: '#356a7c',
    surface: '#eef5f8',
    border: '#c7d9e0',
    description: '覆盖课程常规要求，兼顾熟练度、理解度与基础应用。',
  },
  3: {
    label: '提升卷',
    color: '#8a6b2d',
    surface: '#fbf6ea',
    border: '#e6d9b4',
    description: '强调综合运用能力，适合从熟练解题向稳定提分过渡。',
  },
  4: {
    label: '拔高卷',
    color: '#8b5a3c',
    surface: '#fbf2ee',
    border: '#e6cfc1',
    description: '试题更重视方法迁移、思维跨度与综合判断能力。',
  },
  5: {
    label: '选拔卷',
    color: '#6b557f',
    surface: '#f4f0f8',
    border: '#d9d0e6',
    description: '整体强度较高，适合区分高水平学生的思维品质与稳定性。',
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

export function getRadarValues(dimensions: SixDimensions): number[] {
  return REPORT_DIMENSIONS.map((item) => {
    const rawValue = dimensions[item.field];
    return Number.isFinite(rawValue) ? rawValue : 0;
  });
}

export function getOrderedDistribution(
  distribution: DifficultyPosition['dimension_distribution'],
) {
  const distributionByCode = new Map(distribution.map((item) => [item.code, item]));

  return REPORT_DIMENSIONS.map((item) => {
    const matched = distributionByCode.get(item.code);

    return {
      code: item.code,
      name: matched?.name || item.shortName,
      percentage: matched?.percentage ?? 0,
      color: matched?.color || item.color,
      fullName: item.name,
    };
  });
}
