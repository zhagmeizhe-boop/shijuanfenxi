import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios, { AxiosProgressEvent } from 'axios';
import { useDropzone } from 'react-dropzone';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  BarChart3,
  Brain,
  CheckCircle,
  FileCheck,
  FileText,
  Loader2,
  Shield,
  Sparkles,
  Target,
  Upload,
  Zap,
} from 'lucide-react';

interface UploadStatus {
  status: 'idle' | 'uploading' | 'processing' | 'completed' | 'error';
  message: string;
  progress?: number;
}

interface UploadedFile {
  name: string;
  size: number;
  paperId?: string;
}

interface PaperStatusPayload {
  parse_status: 'pending' | 'parsing' | 'parse_success' | 'parse_failed';
  last_stage?: string | null;
  error_message?: string | null;
}

interface AnalyzeResponsePayload {
  paper_id: string;
}

type ApiErrorPayload = { detail?: string } | string | undefined;

const ANALYZE_REQUEST_TIMEOUT_MS = 15000;
const POLL_INTERVAL_MS = 5000;
const MAX_POLL_ATTEMPTS = 120;

const STAGE_MESSAGES: Record<string, string> = {
  upload_saved: '文件已上传，等待分析任务启动',
  ocr_parse: '正在进行 OCR 解析',
  question_persist: '正在写入题目数据',
  llm_parse: '正在进行题目理解与六维分析',
  report_build: '正在生成报告',
  snapshot_save: '正在保存报告快照',
};

const STAGE_PROGRESS: Record<string, number> = {
  upload_saved: 10,
  ocr_parse: 28,
  question_persist: 42,
  llm_parse: 68,
  report_build: 84,
  snapshot_save: 94,
};

function extractAxiosDetail(error: unknown): string | null {
  if (!axios.isAxiosError(error)) {
    return null;
  }

  const data = error.response?.data as ApiErrorPayload;
  if (typeof data === 'string') {
    return data.trim() || null;
  }

  if (data && typeof data.detail === 'string' && data.detail.trim()) {
    return data.detail.trim();
  }

  return null;
}

function getProcessingMessage(payload: PaperStatusPayload, attempt: number): string {
  const dots = '.'.repeat((attempt % 3) + 1);

  if (payload.parse_status === 'pending') {
    return `分析任务已创建，等待 worker 接手${dots}`;
  }

  if (payload.last_stage && STAGE_MESSAGES[payload.last_stage]) {
    return `${STAGE_MESSAGES[payload.last_stage]}${dots}`;
  }

  return `正在分析试卷${dots}`;
}

function getProcessingProgress(payload: PaperStatusPayload, attempt: number): number {
  if (payload.parse_status === 'pending') {
    return 10;
  }

  if (payload.last_stage && STAGE_PROGRESS[payload.last_stage] !== undefined) {
    return STAGE_PROGRESS[payload.last_stage];
  }

  return Math.min(12 + attempt * 1.5, 90);
}

export function PDFUploadPage() {
  const navigate = useNavigate();
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>({
    status: 'idle',
    message: '准备上传',
  });
  const [uploadedFile, setUploadedFile] = useState<UploadedFile | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const redirectToReport = useCallback(
    (paperId: string) => {
      const targetPath = `/report/${paperId}`;
      navigate(targetPath);

      window.setTimeout(() => {
        if (window.location.pathname !== targetPath) {
          window.location.assign(targetPath);
        }
      }, 50);
    },
    [navigate],
  );

  useEffect(() => clearPollTimer, [clearPollTimer]);

  const pollPaperStatus = useCallback(
    (paperId: string, attempt = 0) => {
      if (attempt >= MAX_POLL_ATTEMPTS) {
        setUploadStatus({
          status: 'error',
          message: '分析超时，请检查后端日志或稍后重新上传。',
        });
        return;
      }

      pollTimerRef.current = setTimeout(async () => {
        try {
          const response = await axios.get<PaperStatusPayload>(`/api/v1/papers/${paperId}/status`);
          const payload = response.data;

          if (payload.parse_status === 'parse_success') {
            setUploadStatus({
              status: 'completed',
              message: '分析完成，正在跳转报告页',
              progress: 100,
            });
            clearPollTimer();
            redirectToReport(paperId);
            return;
          }

          if (payload.parse_status === 'parse_failed') {
            clearPollTimer();
            setUploadStatus({
              status: 'error',
              message: payload.error_message || '试卷分析失败，请重新上传。',
            });
            return;
          }

          setUploadStatus({
            status: 'processing',
            message: getProcessingMessage(payload, attempt),
            progress: getProcessingProgress(payload, attempt),
          });
          pollPaperStatus(paperId, attempt + 1);
        } catch (error: unknown) {
          const detail = extractAxiosDetail(error);

          if (axios.isAxiosError(error) && error.code === 'ERR_NETWORK') {
            clearPollTimer();
            setUploadStatus({
              status: 'error',
              message: '无法连接到后端服务，请确认 API、Redis 和 Celery worker 都已启动。',
            });
            return;
          }

          clearPollTimer();
          setUploadStatus({
            status: 'error',
            message: detail ? `状态查询失败：${detail}` : '状态查询失败，请检查后端日志。',
          });
        }
      }, POLL_INTERVAL_MS);
    },
    [clearPollTimer, redirectToReport],
  );

  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      const file = acceptedFiles[0];
      if (!file) {
        return;
      }

      if (file.type !== 'application/pdf') {
        setUploadStatus({ status: 'error', message: '请上传 PDF 格式的文件。' });
        return;
      }

      if (file.size > 10 * 1024 * 1024) {
        setUploadStatus({ status: 'error', message: '文件大小超过 10MB 限制。' });
        return;
      }

      clearPollTimer();
      setUploadedFile({
        name: file.name,
        size: file.size,
      });
      setUploadStatus({
        status: 'uploading',
        message: '正在上传文件...',
        progress: 2,
      });

      try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('paper_name', file.name.replace(/\.pdf$/i, ''));

        let requestSettled = false;

        const response = await axios.post<AnalyzeResponsePayload>('/api/v1/papers/analyze', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: ANALYZE_REQUEST_TIMEOUT_MS,
          onUploadProgress: (event: AxiosProgressEvent) => {
            if (requestSettled) {
              return;
            }

            const total = event.total ?? file.size;
            if (!total) {
              setUploadStatus({
                status: 'uploading',
                message: '正在上传文件...',
                progress: 8,
              });
              return;
            }

            const percent = Math.min(Math.round((event.loaded / total) * 100), 100);
            if (percent >= 100) {
              setUploadStatus({
                status: 'uploading',
                message: '文件上传完成，正在创建分析任务...',
                progress: 96,
              });
              return;
            }

            setUploadStatus({
              status: 'uploading',
              message: '正在上传文件...',
              progress: Math.max(percent, 2),
            });
          },
        });

        requestSettled = true;
        const paperId = response.data.paper_id;

        setUploadedFile({
          name: file.name,
          size: file.size,
          paperId,
        });
        setUploadStatus({
          status: 'processing',
          message: '分析任务已创建，等待 worker 接手...',
          progress: 10,
        });

        pollPaperStatus(paperId);
      } catch (error: unknown) {
        const detail = extractAxiosDetail(error);
        let errorMessage = '上传失败，请重试。';

        if (axios.isAxiosError(error)) {
          if (error.code === 'ECONNABORTED') {
            errorMessage = '任务派发失败：请求超时，请检查 Redis 是否可用。';
          } else if (error.code === 'ERR_NETWORK') {
            errorMessage = '无法连接到后端服务，请确认 API 已启动。';
          } else if (detail) {
            errorMessage = detail;
          } else if (error.message) {
            errorMessage = `上传失败：${error.message}`;
          }
        }

        setUploadStatus({ status: 'error', message: errorMessage });
      }
    },
    [clearPollTimer, pollPaperStatus],
  );

  const handleReupload = useCallback(() => {
    clearPollTimer();
    setUploadedFile(null);
    setUploadStatus({
      status: 'idle',
      message: '准备上传',
    });
  }, [clearPollTimer]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    maxFiles: 1,
    disabled: uploadStatus.status === 'uploading' || uploadStatus.status === 'processing',
  });

  const features = [
    { icon: Zap, title: '数学运算', desc: '识别试卷中的核心计算难度' },
    { icon: Brain, title: '几何直观与空间想象', desc: '评估几何关系与图形推理要求' },
    { icon: Target, title: '信息提取与转化', desc: '分析条件读取与表达转化能力' },
    { icon: FileCheck, title: '实践与创新', desc: '关注应用建模与开放表达' },
    { icon: BarChart3, title: '知识点广度', desc: '总结整卷覆盖的知识层级' },
    { icon: Sparkles, title: '逻辑链条长度', desc: '衡量推理步骤与结构复杂度' },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50">
      <nav className="sticky top-0 z-50 border-b border-slate-200 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-semibold tracking-[0.18em] text-slate-500">RESEARCH REPORT</div>
              <div className="text-lg font-semibold text-slate-900">六维试卷分析</div>
            </div>
          </div>
          <div className="text-sm text-slate-500">上传 PDF 并创建分析任务</div>
        </div>
      </nav>

      <main className="mx-auto max-w-6xl px-4 py-12 sm:px-6 lg:px-8">
        <section className="grid gap-8 lg:grid-cols-[1.3fr_0.8fr]">
          <div className="rounded-[28px] border border-slate-200 bg-white p-8 shadow-[0_24px_70px_-42px_rgba(15,23,42,0.35)]">
            <div className="max-w-2xl">
              <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-blue-700">
                <FileText className="h-3.5 w-3.5" />
                PDF Upload
              </div>
              <h1 className="text-4xl font-semibold tracking-tight text-slate-900">上传试卷，进入分析队列</h1>
              <p className="mt-4 text-base leading-7 text-slate-600">
                系统会先完成文件上传，再创建 Celery 分析任务。若 Redis 不可用，页面会直接返回明确错误，不再长期卡在上传状态。
              </p>
            </div>

            {uploadStatus.status !== 'idle' && (
              <div
                className={`mt-8 rounded-2xl border px-5 py-4 ${
                  uploadStatus.status === 'error'
                    ? 'border-red-200 bg-red-50 text-red-700'
                    : uploadStatus.status === 'completed'
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                      : 'border-blue-200 bg-blue-50 text-blue-700'
                }`}
              >
                <div className="flex items-center gap-3">
                  {uploadStatus.status === 'uploading' || uploadStatus.status === 'processing' ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : uploadStatus.status === 'completed' ? (
                    <CheckCircle className="h-5 w-5" />
                  ) : (
                    <AlertCircle className="h-5 w-5" />
                  )}
                  <span className="text-sm font-medium">{uploadStatus.message}</span>
                </div>
                {uploadStatus.progress !== undefined && (
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/70">
                    <div
                      className="h-full rounded-full bg-current transition-all"
                      style={{ width: `${uploadStatus.progress}%` }}
                    />
                  </div>
                )}
              </div>
            )}

            {(uploadStatus.status === 'processing' || uploadStatus.status === 'completed') && uploadedFile ? (
              <div className="mt-8 rounded-[24px] border border-slate-200 bg-slate-50 p-8">
                <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-500">当前文件</div>
                    <div className="mt-2 text-xl font-semibold text-slate-900">{uploadedFile.name}</div>
                    <div className="mt-1 text-sm text-slate-500">
                      {(uploadedFile.size / 1024 / 1024).toFixed(2)} MB
                      {uploadedFile.paperId ? ` · paper_id: ${uploadedFile.paperId}` : ''}
                    </div>
                  </div>
                  <button
                    onClick={handleReupload}
                    className="inline-flex items-center justify-center rounded-full border border-slate-300 bg-white px-5 py-2.5 text-sm font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-100"
                  >
                    重新上传
                  </button>
                </div>
              </div>
            ) : (
              <div
                {...getRootProps()}
                className={`mt-8 rounded-[28px] border-2 border-dashed px-8 py-14 text-center transition ${
                  isDragActive
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-slate-300 bg-slate-50/70 hover:border-slate-400 hover:bg-white'
                } ${uploadStatus.status === 'uploading' ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}
              >
                <input {...getInputProps()} />
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-slate-900 text-white">
                  <Upload className="h-7 w-7" />
                </div>
                <div className="mt-6 text-xl font-semibold text-slate-900">
                  {isDragActive ? '松开文件即可开始上传' : '点击或拖拽上传 PDF'}
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-500">仅支持 PDF，单文件不超过 10MB。</p>
              </div>
            )}
          </div>

          <aside className="space-y-6">
            <div className="rounded-[28px] border border-slate-200 bg-slate-900 p-7 text-slate-100 shadow-[0_24px_70px_-42px_rgba(15,23,42,0.5)]">
              <div className="text-sm font-semibold uppercase tracking-[0.22em] text-slate-300">Processing Flow</div>
              <ol className="mt-5 space-y-4 text-sm leading-6 text-slate-300">
                <li>1. 上传 PDF 文件到后端。</li>
                <li>2. 创建 `paper` 记录并进行 Redis 队列预检。</li>
                <li>3. 预检通过后派发 Celery 任务，进入 `pending / parsing`。</li>
                <li>4. OCR、LLM、评分和报告生成在 worker 中执行。</li>
              </ol>
            </div>

            <div className="rounded-[28px] border border-slate-200 bg-white p-7">
              <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.22em] text-slate-500">
                <Shield className="h-4 w-4" />
                Runtime Guardrails
              </div>
              <ul className="mt-5 space-y-3 text-sm leading-6 text-slate-600">
                <li>Redis 不可用时，上传接口会快速返回 `503`。</li>
                <li>Celery worker 未启动时，任务会停在 `pending`，不会误报为上传失败。</li>
                <li>状态轮询会展示后端返回的 `last_stage` 和 `error_message`。</li>
              </ul>
            </div>
          </aside>
        </section>

        <section className="mt-10 rounded-[28px] border border-slate-200 bg-white p-8 shadow-[0_24px_70px_-42px_rgba(15,23,42,0.18)]">
          <div className="flex items-end justify-between gap-4">
            <div>
              <div className="text-sm font-semibold uppercase tracking-[0.22em] text-slate-500">Six Dimensions</div>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">分析维度概览</h2>
            </div>
            <div className="text-sm text-slate-500">上传成功后自动进入后台分析</div>
          </div>

          <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {features.map((item) => (
              <div key={item.title} className="rounded-2xl border border-slate-200 bg-slate-50 p-5">
                <item.icon className="h-5 w-5 text-slate-700" />
                <div className="mt-3 text-base font-semibold text-slate-900">{item.title}</div>
                <p className="mt-2 text-sm leading-6 text-slate-500">{item.desc}</p>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default PDFUploadPage;
