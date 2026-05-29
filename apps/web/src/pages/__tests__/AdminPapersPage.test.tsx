import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminPapersPage from '@/pages/AdminPapersPage';

const failedPayload = {
  summary: {
    total: 3,
    parsing: 1,
    success: 1,
    failed: 1,
  },
  items: [
    {
      paper_id: 'paper-failed',
      paper_name: '三年级期中试卷.pdf',
      parse_status: 'parse_failed',
      last_stage: 'ocr_parse',
      stage_display: 'OCR/试卷题目提取',
      error_message: 'Vision LLM 页面解析超时',
      failure_reason_display: 'Vision LLM 页面解析超时',
      failure_solution_display: '检查 LLM 网关是否可访问；确认服务器公网 IP 已加入白名单；稍后重试或降低 OCR 并发。',
      cancel_requested: false,
      cancel_requested_at: null,
      can_cancel: false,
      total_question_count: 0,
      created_at: '2026-05-28T10:00:00',
      updated_at: '2026-05-28T10:05:00',
    },
  ],
  page: 1,
  page_size: 20,
  total: 1,
};

function mockFetch(payload: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response);
}

function renderPage() {
  render(
    <MemoryRouter>
      <AdminPapersPage />
    </MemoryRouter>,
  );
}

afterEach(() => {
  window.sessionStorage.clear();
  vi.restoreAllMocks();
});

describe('AdminPapersPage', () => {
  it('shows token form before entering admin page', () => {
    renderPage();

    expect(screen.getByText('后台上传记录')).toBeInTheDocument();
    expect(screen.getByLabelText('后台访问口令')).toBeInTheDocument();
  });

  it('stores token and loads failed papers by default', async () => {
    const fetchMock = mockFetch(failedPayload);
    vi.stubGlobal('fetch', fetchMock);
    renderPage();

    fireEvent.change(screen.getByLabelText('后台访问口令'), { target: { value: 'secret' } });
    fireEvent.click(screen.getByRole('button', { name: /进入后台/ }));

    await screen.findByText('三年级期中试卷.pdf');

    expect(window.sessionStorage.getItem('math_analysis_admin_token')).toBe('secret');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/admin/papers?status=failed'),
      expect.objectContaining({
        headers: {
          'X-Admin-Token': 'secret',
        },
      }),
    );
    expect(screen.getByText('失败原因')).toBeInTheDocument();
    expect(screen.getByText('Vision LLM 页面解析超时')).toBeInTheDocument();
    expect(screen.getByText('建议解决方案')).toBeInTheDocument();
    expect(screen.getByText(/公网 IP 已加入白名单/)).toBeInTheDocument();
  });

  it('renders success paper report link', async () => {
    const successPayload = {
      ...failedPayload,
      items: [
        {
          ...failedPayload.items[0],
          paper_id: 'paper-success',
          paper_name: '成功试卷.pdf',
          parse_status: 'parse_success',
          failure_reason_display: null,
          failure_solution_display: null,
          total_question_count: 12,
        },
      ],
    };
    vi.stubGlobal('fetch', mockFetch(successPayload));
    window.sessionStorage.setItem('math_analysis_admin_token', 'secret');

    renderPage();

    await screen.findByText('成功试卷.pdf');
    expect(screen.getByText('题目数：')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /查看报告/ })).toHaveAttribute('href', '/report/paper-success');
  });

  it('renders parsing stage', async () => {
    const parsingPayload = {
      ...failedPayload,
      items: [
        {
          ...failedPayload.items[0],
          paper_id: 'paper-parsing',
          paper_name: '分析中试卷.pdf',
          parse_status: 'parsing',
          stage_display: '题目 LLM 分析',
          failure_reason_display: null,
          failure_solution_display: null,
          cancel_requested: false,
          cancel_requested_at: null,
          can_cancel: true,
        },
      ],
    };
    vi.stubGlobal('fetch', mockFetch(parsingPayload));
    window.sessionStorage.setItem('math_analysis_admin_token', 'secret');

    renderPage();

    await screen.findByText('分析中试卷.pdf');
    expect(screen.getByText('当前阶段：')).toBeInTheDocument();
    expect(screen.getByText('题目 LLM 分析')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /终止分析/ })).toBeInTheDocument();
  });

  it('cancels parsing paper with admin token and refreshes', async () => {
    const parsingPayload = {
      ...failedPayload,
      items: [
        {
          ...failedPayload.items[0],
          paper_id: 'paper-parsing',
          paper_name: '分析中试卷.pdf',
          parse_status: 'parsing',
          stage_display: '题目 LLM 分析',
          failure_reason_display: null,
          failure_solution_display: null,
          cancel_requested: false,
          cancel_requested_at: null,
          can_cancel: true,
        },
      ],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => parsingPayload,
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ paper_id: 'paper-parsing', parse_status: 'parsing', cancel_requested: true, message: 'ok' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => parsingPayload,
      } as Response);

    vi.stubGlobal('fetch', fetchMock);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    window.sessionStorage.setItem('math_analysis_admin_token', 'secret');

    renderPage();

    await screen.findByText('分析中试卷.pdf');
    fireEvent.click(screen.getByRole('button', { name: /终止分析/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/admin/papers/paper-parsing/cancel',
        expect.objectContaining({
          method: 'POST',
          headers: {
            'X-Admin-Token': 'secret',
          },
        }),
      );
    });
  });

  it('changes status filter and searches by keyword', async () => {
    const fetchMock = mockFetch(failedPayload);
    vi.stubGlobal('fetch', fetchMock);
    window.sessionStorage.setItem('math_analysis_admin_token', 'secret');
    renderPage();

    await screen.findByText('三年级期中试卷.pdf');
    fireEvent.click(screen.getByRole('button', { name: '成功' }));
    fireEvent.change(screen.getByPlaceholderText('搜索试卷名或 paper_id'), { target: { value: 'paper-1' } });
    fireEvent.click(screen.getByRole('button', { name: '搜索' }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('status=success'), expect.anything());
      expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('keyword=paper-1'), expect.anything());
    });
  });
});
