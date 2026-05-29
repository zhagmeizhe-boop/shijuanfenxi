import axios from 'axios';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import {
  getNextStalledPollAttempts,
  getProcessingDetail,
  getProcessingMessage,
  getStatusActivityKey,
  PDFUploadPage,
  sanitizeProgressMessage,
} from '@/pages/PDFUploadPage';

describe('PDFUploadPage progress copy', () => {
  it('shows explicit queue copy before the worker starts analysis', () => {
    expect(
      getProcessingMessage(
        {
          parse_status: 'pending',
          last_stage: 'queued',
          progress_current: null,
          progress_total: null,
          progress_message: '已进入分析队列，等待 worker 处理',
        },
        2,
      ),
    ).toBe('已有试卷在分析，正在排队等待...');

    expect(
      getProcessingMessage(
        {
          parse_status: 'pending',
          last_stage: 'queued_waiting_for_analysis_slot',
          progress_current: null,
          progress_total: null,
          progress_message: '正在排队等待分析 worker 空闲槽位',
        },
        2,
      ),
    ).toBe('已有试卷在分析，正在排队等待...');
  });

  it('keeps the generic pending copy when no queue stage is available', () => {
    expect(
      getProcessingMessage(
        {
          parse_status: 'pending',
          last_stage: null,
          progress_current: null,
          progress_total: null,
          progress_message: null,
        },
        2,
      ),
    ).toBe('分析任务已创建，等待 worker 接手...');
  });

  it('shows fixed OCR extraction copy without animated dots', () => {
    expect(
      getProcessingMessage(
        {
          parse_status: 'parsing',
          last_stage: 'ocr_parse',
          progress_current: null,
          progress_total: null,
          progress_message: null,
        },
        2,
      ),
    ).toBe('LLM正在提取试卷题目，预计耗时1min');
  });

  it('keeps LLM progress count in detail instead of the main message', () => {
    const payload = {
      parse_status: 'parsing' as const,
      last_stage: 'llm_parse',
      progress_current: 5,
      progress_total: 20,
      progress_message: '最近完成第10题',
    };

    expect(getProcessingMessage(payload, 1)).toBe('LLM正在分析题目，预计总共耗时3min');
    expect(getProcessingDetail(payload)).toBe('已完成 5/20 道，最近完成第10题');
  });

  it('shows a neutral detail before any LLM question completes', () => {
    expect(
      getProcessingDetail({
        parse_status: 'parsing',
        last_stage: 'llm_parse',
        progress_current: 0,
        progress_total: 20,
        progress_message: 'LLM 分析已启动',
      }),
    ).toBe('已完成 0/20 道，题目正在并行分析');
  });

  it('hides backend failure details from user-facing progress copy', () => {
    expect(sanitizeProgressMessage('最近完成第10题（失败，已继续）')).toBe('最近完成第10题');
    expect(
      getProcessingDetail({
        parse_status: 'parsing',
        last_stage: 'llm_parse',
        progress_current: 5,
        progress_total: 20,
        progress_message: '最近完成第10题（失败，已继续）',
      }),
    ).toBe('已完成 5/20 道，最近完成第10题');
    expect(sanitizeProgressMessage('LLM request failed')).toBe('');
  });

  it('tracks stalled polling by backend activity instead of total elapsed polls', () => {
    const firstPayload = {
      parse_status: 'parsing' as const,
      last_stage: 'ocr_parse',
      progress_current: 1,
      progress_total: 3,
      progress_message: '最近完成第 1 页',
      updated_at: '2026-05-19T10:00:00',
    };
    const firstKey = getStatusActivityKey(firstPayload);

    expect(getNextStalledPollAttempts(firstPayload, '', 20)).toEqual({
      activityKey: firstKey,
      stalledAttempts: 0,
    });

    expect(getNextStalledPollAttempts(firstPayload, firstKey, 3)).toEqual({
      activityKey: firstKey,
      stalledAttempts: 4,
    });

    const progressedPayload = {
      ...firstPayload,
      progress_current: 2,
      updated_at: '2026-05-19T10:02:00',
    };
    expect(getNextStalledPollAttempts(progressedPayload, firstKey, 120).stalledAttempts).toBe(0);
  });

  it('shows dimension feature cards in the knowledge-first order', () => {
    render(
      <MemoryRouter>
        <PDFUploadPage />
      </MemoryRouter>,
    );

    const titles = [
      '知识广度',
      '计算',
      '几何',
      '信息提取',
      '实践创新',
      '逻辑链条',
    ].map((title) => screen.getByText(title));

    for (let index = 0; index < titles.length - 1; index += 1) {
      expect(titles[index].compareDocumentPosition(titles[index + 1])).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    }
  });

  it('alerts when the analysis queue is full', async () => {
    const postSpy = vi.spyOn(axios, 'post').mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 429,
        data: {
          detail: '当前分析队列已满（3/3），请稍后再上传。',
        },
      },
    });
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined);

    render(
      <MemoryRouter>
        <PDFUploadPage />
      </MemoryRouter>,
    );

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['paper'], 'paper.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [file] } });

    await screen.findByRole('button', { name: /开始分析/ });
    fireEvent.click(screen.getByRole('button', { name: /开始分析/ }));

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalled();
      expect(alertSpy).toHaveBeenCalledWith('提示，现在分析队列已经满了，请稍后重试');
      expect(screen.getByText('提示，现在分析队列已经满了，请稍后重试')).toBeInTheDocument();
    });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});
