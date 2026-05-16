import { describe, expect, it } from 'vitest';
import {
  getProcessingDetail,
  getProcessingMessage,
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
    ).toBe('已进入分析队列，等待开始分析...');

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
    ).toBe('正在等待分析资源空闲...');
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
});
