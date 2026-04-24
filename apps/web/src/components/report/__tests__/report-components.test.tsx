import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { DimensionScoreCards } from '@/components/report/DimensionScoreCards';
import { SixDimensionsRadar } from '@/components/report/SixDimensionsRadar';
import type { DimensionScore } from '@/types/analysis';

vi.mock('echarts', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  })),
}));

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

    expect(screen.getByText('六维分布')).toBeInTheDocument();
    expect(screen.getByText('数学运算')).toBeInTheDocument();
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
});
