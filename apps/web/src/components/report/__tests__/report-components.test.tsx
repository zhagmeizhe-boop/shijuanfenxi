import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { DimensionScoreCards } from '@/components/report/DimensionScoreCards';
import { DifficultyPositioning } from '@/components/report/DifficultyPositioning';
import { SixDimensionsRadar } from '@/components/report/SixDimensionsRadar';
import {
  getDifficultyLabel,
  REPORT_DIMENSIONS,
  REPORT_DIFFICULTY_META,
} from '@/components/report/reportMeta';
import type { DifficultyPosition, DimensionScore } from '@/types/analysis';

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

describe('DifficultyPositioning', () => {
  const mockDifficulty: DifficultyPosition = {
    level: 4,
    label: '选拔卷',
    overall_score: 7.8,
    target_students: '适合基础扎实、需要面向选拔场景提升综合稳定性的学生。',
    description: '面向选拔区分场景，重视复杂问题解决、策略迁移与稳定性。',
    parent_summary: [
      '这张试卷难度偏高，已经不只是考会不会知识点，更看孩子综合解题是否稳定。',
      '从题目结构看，较难题约占 33.3%。最明显的压力在读题理解和推理链条：孩子需要把题目里的对象、规则、过程和问法分清楚，也要一步一步往下推，并在关键条件上回查。',
    ],
    question_distribution: {
      basis: 'question_count',
      classification: 'average_applicable_dimension_score',
      total_count: 4,
      classified_count: 3,
      unclassified_count: 1,
      buckets: [
        {
          key: 'basic',
          label: '基础题',
          description: '主要检查基本概念、直接计算和常规方法。',
          count: 1,
          percentage: 33.3,
          questions: [{ question_no: '18', question_display_label: '（18）', average_score: 3.0 }],
        },
        {
          key: 'medium',
          label: '中等题',
          description: '需要一定转化、综合运用或稳定的解题步骤。',
          count: 1,
          percentage: 33.3,
          questions: [{ question_no: '15', question_display_label: '三-15', average_score: 5.0 }],
        },
        {
          key: 'hard',
          label: '较难题',
          description: '更容易拉开差距，通常涉及复杂条件、方法迁移或多步推理。',
          count: 1,
          percentage: 33.3,
          questions: [{ question_no: '1', question_display_label: '1.', average_score: 8.0 }],
        },
      ],
    },
    dimension_distribution: [],
  };

  it('renders parent summary and question difficulty distribution', () => {
    render(<DifficultyPositioning data={mockDifficulty} />);

    expect(screen.getByText('家长速读')).toBeInTheDocument();
    expect(screen.getByText('这张试卷难度偏高，已经不只是考会不会知识点，更看孩子综合解题是否稳定。')).toBeInTheDocument();
    expect(screen.getByText(/最明显的压力在读题理解和推理链条/)).toBeInTheDocument();
    expect(screen.getByText('题目难度结构')).toBeInTheDocument();
    expect(screen.getByText('基础题')).toBeInTheDocument();
    expect(screen.getByText('中等题')).toBeInTheDocument();
    expect(screen.getByText('较难题')).toBeInTheDocument();
    expect(screen.getAllByText('33.3%')).toHaveLength(3);
    expect(screen.getByText('18')).toBeInTheDocument();
    expect(screen.getByText('15')).toBeInTheDocument();
    expect(screen.queryByText('（18）')).not.toBeInTheDocument();
    expect(screen.queryByText('三-15')).not.toBeInTheDocument();
    expect(screen.getByText('另有 1 道题缺少可用于分桶的维度分，未强行归类。')).toBeInTheDocument();
  });

  it('uses parent-friendly fallback summary when parent summary is missing', () => {
    const { parent_summary: _parentSummary, ...difficultyWithoutSummary } = mockDifficulty;

    render(<DifficultyPositioning data={difficultyWithoutSummary} />);

    expect(screen.getByText(/这张试卷整体定位为/)).toBeInTheDocument();
    expect(
      screen.getByText('具体难点要结合各维度得分看，重点关注计算、几何、读题、解题组织、知识跨度和推理链条里分数偏高的部分。'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/六维评价明细/)).not.toBeInTheDocument();
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
    expect(screen.getAllByText('得分概览')).toHaveLength(2);
    expect(screen.getByText(/计算维度，综合得分 7.5 分/)).toBeInTheDocument();
    expect(screen.getByText(/几何直观与空间想象维度，综合得分 6.0 分/)).toBeInTheDocument();
    expect(screen.getByText(/图形关系整理和模型识别/)).toBeInTheDocument();
  });

  it('explains dim3 score as scenario comprehension complexity', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim3',
        name: '场景理解复杂度',
        score: 8.6,
        level: 4,
        level_label: '较难',
        evidence: '共 4 道相关题目；题级平均维度分 8.6 分，判定为拔高。',
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    const evidence = screen.getByText(/场景理解复杂度维度，综合得分 8.6 分/);
    expect(evidence).toHaveTextContent('学生读题理解题意上设置了明显难度');
    expect(evidence).toHaveTextContent('场景相对复杂');
    expect(evidence).not.toHaveTextContent('按题目等级加权');
    expect(evidence).not.toHaveTextContent('高等级题');
    expect(evidence).not.toHaveTextContent('共 4 道相关题目');
    expect(evidence).not.toHaveTextContent('题级平均维度分');
  });

  it('explains dim6 score as logic-chain evaluation point', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim6',
        name: '逻辑链条长度',
        score: 8.6,
        level: 4,
        level_label: '较难',
        evidence: '共 4 道相关题目；题级平均维度分 8.6 分，判定为拔高。',
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    expect(screen.getByText('逻辑链条')).toBeInTheDocument();
    expect(screen.queryByText('逻辑链条长度')).not.toBeInTheDocument();
    const evidence = screen.getByText(/逻辑推理综合得分 8.6 分/);
    expect(evidence).toHaveTextContent('这张试卷不少题解题链条较长');
    expect(evidence).toHaveTextContent('连续推进 3-4 步');
    expect(evidence).not.toHaveTextContent('逻辑链条维度，综合得分');
    expect(evidence).not.toHaveTextContent('共 4 道相关题目');
    expect(evidence).not.toHaveTextContent('题级平均维度分');
  });

  it('explains dim5 score as knowledge breadth level', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim5',
        name: '知识广度',
        score: 8.6,
        level: 4,
        level_label: '较难',
        evidence: '按知识范围等级权重计算，权重得分 8.6 分。',
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    const evidence = screen.getByText(/知识广度综合得分 8.6 分/);
    expect(evidence).toHaveTextContent('说明本卷知识广度较高');
    expect(evidence).toHaveTextContent('五六年级奥数典型方法或七年级基础前置知识');
    expect(evidence).not.toHaveTextContent('按知识范围等级权重计算');
  });

  it('prefers disambiguated display labels in counted questions', () => {
    render(<DimensionScoreCards dimensions={mockDimensions} />);

    expect(screen.getByText('二-4')).toBeInTheDocument();
    expect(screen.queryByText(/第 4 题/)).not.toBeInTheDocument();
  });

  it('explains dim1 score instead of showing audit wording', () => {
    const dimensions: DimensionScore[] = [
      {
        ...mockDimensions[0],
        evidence: '共 5 道相关题目；纯计算 1 道，均分 9.5，权重 50%；嵌入式计算 4 道，均分 7.0，权重 50%。',
        score: 8.2,
        score_breakdown: {
          pure_calculation: { question_count: 1, average_score: 9.5, weight: 0.5 },
          embedded_calculation: { question_count: 4, average_score: 7.0, weight: 0.5 },
        },
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    const evidence = screen.getByText(/计算维度，综合得分 8.2 分/);
    expect(evidence).toHaveTextContent('说明本卷计算难度较高');
    expect(evidence).not.toHaveTextContent('共 5 道题计入数学运算评分');
    expect(evidence).not.toHaveTextContent('1 道纯计算题和 4 道应用题中的核心计算');
    expect(screen.queryByText(/权重/)).not.toBeInTheDocument();
  });

  it('renders compact counted-question text plus full analysis for hover and print', () => {
    const fullReason = 'L5 高阶结构巧算：完整分析：需要识别结构特征。核心事实：结构特征、依据来源。依据来源：文本。';
    const displayedFullReason = '困难（9.5）：完整分析：需要识别结构特征';
    const dimensions: DimensionScore[] = [
      {
        ...mockDimensions[0],
        counted_questions: [
          {
            question_no: '9',
            question_display_label: '9',
            summary: '结构计算',
            score: 9.5,
            level_code: 'L5',
            difficulty_label: '困难（9.5）',
            reason: 'L5 高阶结构巧算：短摘要：结构计算题',
            full_reason: fullReason,
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    expect(screen.getByText('困难（9.5）：短摘要：结构计算题')).toBeInTheDocument();
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

  it('normalizes historical counted-question prefixes to dim1 difficulty labels', () => {
    const dimensions: DimensionScore[] = [
      {
        ...mockDimensions[0],
        counted_questions: [
          {
            question_no: '1',
            question_display_label: '1',
            summary: '分数裂项',
            score: 8.0,
            reason: '8.0分：主要考查分数裂项；常见失分点是连续化简。',
          },
          {
            question_no: '2',
            question_display_label: '2',
            summary: '百分数应用',
            level_code: 'L3',
            reason: 'L3：主要考查百分数应用；常见失分点是算式落地。',
          },
          {
            question_no: '3',
            question_display_label: '3',
            summary: '小数除法',
            difficulty_label: '较易（4.0）',
            reason: 'L2 常规运算：主要考查小数除法；主要区分熟练度和准确率。',
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    expect(screen.getAllByText('较难（8.0）：主要考查分数裂项；常见失分点是连续化简').length).toBeGreaterThan(0);
    expect(screen.getAllByText('中等（6.0）：主要考查百分数应用；常见失分点是算式落地').length).toBeGreaterThan(0);
    expect(screen.getAllByText('较易（4.0）：主要考查小数除法；主要区分熟练度和准确率').length).toBeGreaterThan(0);
  });

  it('normalizes dim3 counted-question prefixes to difficulty labels', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim3',
        name: '场景理解复杂度',
        score: 8.0,
        level: 4,
        level_label: '较难',
        evidence: '旧概览。',
        counted_questions: [
          {
            question_no: '1',
            question_display_label: '1',
            summary: '百分数变化',
            score: 8.0,
            reason: '8.0分：主要考查比较基准理解；本题难点在于要分清变化前后的基准量。',
          },
          {
            question_no: '2',
            question_display_label: '2',
            summary: '表格对应',
            level_code: 'L3',
            reason: 'L3：主要考查图文对应理解；本题难点在于要先看懂表格项目和题目问法的对应关系。',
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    expect(screen.getAllByText('较难（8.0）：主要考查比较基准理解；本题难点在于要分清变化前后的基准量').length).toBeGreaterThan(0);
    expect(screen.getAllByText('中等（6.0）：主要考查图文对应理解；本题难点在于要先看懂表格项目和题目问法的对应关系').length).toBeGreaterThan(0);
  });

  it('normalizes dim6 counted-question prefixes to difficulty labels', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim6',
        name: '逻辑链条',
        score: 8.0,
        level: 4,
        level_label: '较难',
        evidence: '旧概览。',
        counted_questions: [
          {
            question_no: '1',
            question_display_label: '1',
            summary: '多轮变化',
            score: 8.0,
            reason: '8.0分：本题逻辑链条难在多轮变化前后衔接；依据是题目包含多轮状态变化。',
          },
          {
            question_no: '2',
            question_display_label: '2',
            summary: '两步条件',
            level_code: 'L3',
            reason: 'L3：本题逻辑链条难在连续推出中间结论；依据是题目需要把前一步结果接到下一步条件中。',
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    expect(screen.getAllByText('较难（8.0）：这题的解题链条较长，通常需要多步推进，并伴随分类、倒推、回查或多条件检查；学生需要按阶段记录变化，把上一阶段的结果接到下一阶段条件中').length).toBeGreaterThan(0);
    expect(screen.getAllByText('中等（6.0）：这题的解题链条有一定长度，通常需要把前后条件连续接起来；学生需要把前一步得到的结果接到下一步条件里，连续推出中间结论').length).toBeGreaterThan(0);
    expect(screen.queryByText(/依据是/)).not.toBeInTheDocument();
  });

  it('renders dim5 counted questions as one continuous structured sentence', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim5',
        name: '知识广度',
        score: 8.0,
        level: 4,
        level_label: '较难',
        evidence: '旧概览。',
        counted_questions: [
          {
            question_no: '8',
            question_display_label: '8',
            summary: '面积比模型',
            score: 8.0,
            level_code: 'L4',
            difficulty_label: '较难（8.0）',
            knowledge_source_text: '五六年级奥数',
            knowledge_point_text: '面积比模型',
            score_reason: '难点在于要识别等高、共边或割补关系，并把图形面积关系转化为比例关系。',
            reason: '旧文案：奥数面积比，因此计为较难。',
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    const expected = (
      '较难（8.0）：本题属于五六年级奥数的面积比模型；' +
      '难点在于要识别等高、共边或割补关系，并把图形面积关系转化为比例关系。'
    );
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
    expect(screen.queryByText(/命中/)).not.toBeInTheDocument();
    expect(screen.queryByText(/因此计为/)).not.toBeInTheDocument();
  });

  it('explains dim4 score as modeling solution complexity', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim4',
        name: '建模解题复杂度',
        score: 8.2,
        level: 4,
        level_label: '拔高',
        evidence: '共 15 道题纳入建模解题复杂度评分；L3 1 道、L4 13 道、L5 1 道；人工复核 1 道未计入；权重得分 8.2 分，判定为 拔高。',
        score_breakdown: {
          valid_score_question_count: 15,
          review_count: 1,
          fallback_count: 1,
          auto_ignored_count: 2,
          weighted_question_average: 8.2,
          raw_question_average: 8.0,
          level_counts: {
            L3: 1,
            L4: 13,
            L5: 1,
          },
        },
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    const evidence = screen.getByText(/综合得分为 8.2 分/);
    expect(evidence).toHaveTextContent('在解题思路上有较明显难度');
    expect(evidence).toHaveTextContent('先把条件之间的关系理清楚');
    expect(evidence).not.toHaveTextContent('建模解题复杂度综合得分');
    expect(evidence).not.toHaveTextContent('按题目等级加权');
    expect(evidence).not.toHaveTextContent('列表');
    expect(evidence).not.toHaveTextContent('画图');
    expect(evidence).not.toHaveTextContent('比例');
    expect(evidence).not.toHaveTextContent('方程');
    expect(evidence).not.toHaveTextContent('表格');
    expect(evidence).not.toHaveTextContent('共 15 道题纳入建模解题复杂度评分');
    expect(evidence).not.toHaveTextContent('按建模解题等级权重计算');
    expect(evidence).not.toHaveTextContent('权重得分');
    expect(screen.queryByText(/L4 13 道/)).not.toBeInTheDocument();
  });

  it('renders dim4 counted questions as one continuous structured sentence', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim4',
        name: '建模解题复杂度',
        score: 9.5,
        level: 5,
        level_label: '选拔',
        evidence: '旧概览。',
        counted_questions: [
          {
            question_no: '15',
            question_display_label: '15',
            summary: '数论约束',
            score: 9.5,
            level_code: 'L5',
            difficulty_label: '困难（9.5）',
            knowledge_point_text: '数论约束',
            practice_level_text: '综合构造建模',
            score_reason: '难点在于要把整除、余数和范围条件一起回查，逐步排除不满足条件的数。',
            reason: '高思题目级参考画像已校准到 L5。',
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    const expected = (
      '困难（9.5）：本题是数论约束中的综合构造建模；' +
      '难点在于要把整除、余数和范围条件一起回查，逐步排除不满足条件的数。'
    );
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
    expect(screen.queryByText(/校准/)).not.toBeInTheDocument();
    expect(screen.queryByText(/参考画像/)).not.toBeInTheDocument();
  });

  it('filters English dim4 counted-question score reasons from historical snapshots', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim4',
        name: '建模解题复杂度',
        score: 8.0,
        level: 4,
        level_label: '拔高',
        evidence: '旧概览。',
        counted_questions: [
          {
            question_no: '20',
            question_display_label: '20',
            summary: '反射路径',
            score: 8.0,
            level_code: 'L4',
            difficulty_label: '较难（8.0）',
            knowledge_point_text: '反射路径',
            practice_level_text: '多关系建模',
            score_reason:
              'This problem requires understanding the 90-degree reflection rule, then applying coordinate management through multiple reflections.',
            reason: '旧文案。',
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    const expected = (
      '较难（8.0）：本题是反射路径中的多关系建模；' +
      '难点在于不能直接套模板，需要构造中间量、分类回查或重组关系。'
    );
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
    expect(screen.queryByText(/This problem/)).not.toBeInTheDocument();
    expect(screen.queryByText(/requires understanding/)).not.toBeInTheDocument();
  });

  it('falls back for historical dim4 counted-question text', () => {
    const dimensions: DimensionScore[] = [
      {
        code: 'dim4',
        name: '建模解题复杂度',
        score: 8.0,
        level: 4,
        level_label: '拔高',
        evidence: '旧概览。',
        counted_questions: [
          {
            question_no: '2',
            question_display_label: '2',
            summary: '构造回查',
            score: 8.0,
            level_code: 'L4',
            reason: 'L4：构造中间量并约束回查。',
          },
        ],
      },
    ];

    render(<DimensionScoreCards dimensions={dimensions} />);

    expect(screen.getAllByText('较难（8.0）：构造中间量并约束回查').length).toBeGreaterThan(0);
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
