import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { DimensionScoreCards } from '@/components/report/DimensionScoreCards';
import { SixDimensionsRadar } from '@/components/report/SixDimensionsRadar';
import {
  getDifficultyLabel,
  REPORT_DIMENSIONS,
  REPORT_DIFFICULTY_META,
} from '@/components/report/reportMeta';
import type { DimensionScore } from '@/types/analysis';

describe('SixDimensionsRadar', () => {
  const mockDimensions = {
    computation: 75,
    concept: 82,
    logic: 68,
    spatial: 70,
    application: 65,
    innovation: 58,
  };

  it('renders radar panel title', () => {
    render(<SixDimensionsRadar dimensions={mockDimensions} />);

    expect(screen.getByTestId('radar-svg')).toBeInTheDocument();
    expect(screen.getByTestId('radar-data-area')).toHaveAttribute('points');
    expect(screen.getByTestId('radar-data-line')).toHaveAttribute('stroke', '#294766');
  });

  it('uses zero chart values for not-covered dimensions while keeping labels', () => {
    const dimensionDetails: DimensionScore[] = [
      {
        code: 'dim2',
        name: REPORT_DIMENSIONS[1].name,
        score: 0,
        level: 0,
        level_label: '未覆盖',
        score_status: 'not_covered',
        evidence: '该维度未覆盖。',
      },
    ];

    render(<SixDimensionsRadar dimensions={mockDimensions} dimensionDetails={dimensionDetails} />);

    expect(screen.getByText('未覆盖')).toBeInTheDocument();
    const areaPoints = screen.getByTestId('radar-data-area').getAttribute('points') ?? '';
    const linePoints = screen.getByTestId('radar-data-line').getAttribute('points') ?? '';
    const dataPoints = screen.getAllByTestId('radar-data-point');

    expect(`${areaPoints} ${linePoints}`).not.toMatch(/NaN|null/);
    expect(dataPoints[1]).toHaveAttribute('cx', '180.00');
    expect(dataPoints[1]).toHaveAttribute('cy', '168.00');
  });

  it('shows an empty radar state when all dimensions are not covered', () => {
    const dimensionDetails: DimensionScore[] = REPORT_DIMENSIONS.map((item) => ({
      code: item.code,
      name: item.name,
      score: 0,
      level: 0,
      level_label: '未覆盖',
      score_status: 'not_covered' as const,
      evidence: '该维度未覆盖。',
    }));

    render(<SixDimensionsRadar dimensions={mockDimensions} dimensionDetails={dimensionDetails} />);

    expect(screen.getByText('暂无可绘制维度')).toBeInTheDocument();
    expect(screen.queryByTestId('radar-svg')).not.toBeInTheDocument();
    expect(screen.queryByTestId('radar-data-line')).not.toBeInTheDocument();
  });
});

describe('DimensionScoreCards', () => {
  const mockDimensions: DimensionScore[] = [
    {
      code: 'dim1',
      name: '数学运算',
      score: 7.5,
      level: 4,
      level_label: '较难',
      evidence: '涉及分数与小数的混合计算，计算门槛较高。',
      counted_questions: [
        {
          question_no: '4',
          question_label_raw: '（4）',
          question_display_label: '二-4',
          summary: '分数混合运算',
          reason: '卷面原样题号展示',
        },
      ],
    },
    {
      code: 'dim2',
      name: '几何直观与空间想象',
      score: 6.0,
      level: 3,
      level_label: '中等',
      evidence: '需要根据图形关系完成空间判断。',
    },
  ];

  it('renders all dimension cards', () => {
    render(<DimensionScoreCards dimensions={mockDimensions} />);

    expect(screen.getByText('数学运算')).toBeInTheDocument();
    expect(screen.getByText('几何直观与空间想象')).toBeInTheDocument();
  });

  it('displays correct scores and evidence', () => {
    render(<DimensionScoreCards dimensions={mockDimensions} />);

    expect(screen.getByText('7.5')).toBeInTheDocument();
    expect(screen.getByText('6.0')).toBeInTheDocument();
    expect(screen.getByText(/涉及分数与小数的混合计算/)).toBeInTheDocument();
  });

  it('prefers disambiguated display labels in counted questions', () => {
    render(<DimensionScoreCards dimensions={mockDimensions} />);

    expect(screen.getByText('二-4')).toBeInTheDocument();
    expect(screen.queryByText(/第 4 题/)).not.toBeInTheDocument();
  });

  it('renders compact counted-question text plus full analysis for hover and print', () => {
    const fullReason = 'L5 高阶结构巧算：完整分析：需要识别结构特征。核心事实：结构特征、依据来源。依据来源：文本。';
    const displayedFullReason = 'L5：完整分析：需要识别结构特征';
    const dimensions: DimensionScore[] = [
      {
        ...mockDimensions[0],
        counted_questions: [
          {
            question_no: '9',
            question_display_label: '9',
            summary: '结构计算',
            reason: 'L5 高阶结构巧算：短摘要：结构计算题',
            full_reason: fullReason,
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    expect(screen.getByText('L5：短摘要：结构计算题')).toBeInTheDocument();
    const fullReasonNodes = screen.getAllByText(displayedFullReason);
    expect(fullReasonNodes).toHaveLength(2);
    expect(screen.queryByText(/高阶结构巧算/)).not.toBeInTheDocument();
    expect(screen.queryByText(/核心事实：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/依据来源：/)).not.toBeInTheDocument();
    expect(
      fullReasonNodes.some((node: Element) =>
        node.classList.contains('report-counted-question-tooltip'),
      ),
    ).toBe(true);
    expect(
      fullReasonNodes.some((node: Element) =>
        node.classList.contains('report-counted-question-print'),
      ),
    ).toBe(true);
  });
});

describe('report difficulty metadata', () => {
  it('uses the unified five paper-level labels', () => {
    expect(Object.fromEntries(
      Object.entries(REPORT_DIFFICULTY_META).map(([level, meta]) => [level, meta.label]),
    )).toEqual({
      '1': '基础卷',
      '2': '提升卷',
      '3': '拔高卷',
      '4': '选拔卷',
      '5': '竞赛卷',
    });
  });

  it('normalizes historical report labels by known level', () => {
    expect(getDifficultyLabel(4, '拔高卷')).toBe('选拔卷');
    expect(getDifficultyLabel(99, '历史标签')).toBe('历史标签');
  });
});
