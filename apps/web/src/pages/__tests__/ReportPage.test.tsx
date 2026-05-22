import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ReportPage } from '@/pages/ReportPage';
import { fetchReportData } from '@/services/reportData';
import type { FullReportData } from '@/types/analysis';

vi.mock('@/services/reportData', () => ({
  fetchReportData: vi.fn(),
}));

vi.mock('@/components/report/SixDimensionsRadar', () => ({
  SixDimensionsRadar: () => <div data-testid="radar-chart">Radar Chart</div>,
}));

vi.mock('@/components/report/DimensionScoreCards', () => ({
  DimensionScoreCards: () => <div data-testid="score-cards">Score Cards</div>,
}));

describe('ReportPage', () => {
  const mockedFetchReportData = vi.mocked(fetchReportData);

  const mockReportData: FullReportData = {
    report_id: 'rpt-test-001',
    paper_id: 'paper-test-001',
    paper_title: '测试试卷',
    generated_at: '2024-04-07T10:00:00Z',
    dimensions: {
      computation: 75,
      concept: 82,
      logic: 68,
      spatial: 70,
      application: 65,
      innovation: 58,
    },
    dimension_details: [
      {
        code: 'dim1',
        name: '数学运算',
        score: 7.5,
        level: 4,
        level_label: '较难',
        evidence: '测试证据',
      },
    ],
    report_warnings: [],
    difficulty_position: {
      level: 4,
      label: '拔高卷',
      overall_score: 7.0,
      position_summary: '旧定位描述',
      target_students: '目标学生描述',
      description: '定位描述',
      dimension_distribution: [],
    },
    benchmark_comparisons: [],
    knowledge_points: [],
    representative_questions: [],
    overall_summary: '总体评价内容',
    recommendations: ['建议1', '建议2'],
  };

  it('renders loading state initially', () => {
    mockedFetchReportData.mockReturnValue(new Promise(() => {}));

    render(<ReportPage reportId="rpt-test-001" />);

    expect(screen.getByText(/正在加载分析报告/)).toBeInTheDocument();
  });

  it('renders report data after loading', async () => {
    mockedFetchReportData.mockResolvedValue(mockReportData);

    render(<ReportPage reportId="rpt-test-001" />);

    await waitFor(() => {
      expect(screen.getByText('六维评价分析报告')).toBeInTheDocument();
    });

    expect(screen.getByText('测试试卷')).toBeInTheDocument();
    expect(screen.getAllByText('选拔卷').length).toBeGreaterThan(0);
    expect(screen.getAllByText('试卷难度综合分').length).toBeGreaterThan(0);
    expect(screen.getByText('试卷定位')).toBeInTheDocument();
    expect(screen.getByText('小升初分班考难度试卷，题目更绕、步骤更多，用来拉开学生差距。')).toBeInTheDocument();
    expect(screen.getByTestId('radar-chart')).toBeInTheDocument();
    expect(screen.getByTestId('score-cards')).toBeInTheDocument();
  });

  it('renders error state on fetch failure', async () => {
    mockedFetchReportData.mockRejectedValue(new Error('Fetch failed'));

    render(<ReportPage reportId="rpt-test-001" />);

    await waitFor(() => {
      expect(screen.getByText('报告加载失败')).toBeInTheDocument();
    });

    expect(screen.getByText('Fetch failed')).toBeInTheDocument();
  });

  it('does not render overall summary section', async () => {
    mockedFetchReportData.mockResolvedValue(mockReportData);

    render(<ReportPage reportId="rpt-test-001" />);

    await waitFor(() => {
      expect(screen.getByText('六维评价分析报告')).toBeInTheDocument();
    });

    expect(screen.queryByText('总体评价')).not.toBeInTheDocument();
    expect(screen.queryByText('整卷结论')).not.toBeInTheDocument();
    expect(screen.queryByText('报告正文')).not.toBeInTheDocument();
    expect(screen.queryByText('总体评价内容')).not.toBeInTheDocument();
  });

  it('does not render recommendations section', async () => {
    mockedFetchReportData.mockResolvedValue(mockReportData);

    render(<ReportPage reportId="rpt-test-001" />);

    await waitFor(() => {
      expect(screen.getByText('六维评价分析报告')).toBeInTheDocument();
    });

    expect(screen.queryByText('学习建议')).not.toBeInTheDocument();
    expect(screen.queryByText('后续训练建议')).not.toBeInTheDocument();
    expect(screen.queryByText('建议1')).not.toBeInTheDocument();
    expect(screen.queryByText('建议2')).not.toBeInTheDocument();
  });
});
