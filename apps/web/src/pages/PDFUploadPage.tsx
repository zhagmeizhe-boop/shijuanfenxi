import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios, { AxiosProgressEvent } from 'axios';
import { useDropzone } from 'react-dropzone';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  BarChart3,
  Brain,
  CheckCircle,
  FileCheck,
  FileText,
  Image as ImageIcon,
  Loader2,
  Sparkles,
  Target,
  Upload,
  X,
  Zap,
} from 'lucide-react';

interface UploadStatus {
  status: 'idle' | 'uploading' | 'processing' | 'completed' | 'error';
  message: string;
  progress?: number;
  detail?: string;
}

interface UploadedFile {
  name: string;
  size: number;
  fileCount: number;
  kind: UploadKind;
  paperId?: string;
}

type UploadKind = 'pdf' | 'images';

interface SelectedUploadFile {
  id: string;
  file: File;
  kind: UploadKind;
  previewUrl?: string;
}

interface PaperStatusPayload {
  parse_status: 'pending' | 'parsing' | 'parse_success' | 'parse_failed';
  last_stage?: string | null;
  error_message?: string | null;
  progress_current?: number | null;
  progress_total?: number | null;
  progress_message?: string | null;
}

interface AnalyzeResponsePayload {
  paper_id: string;
}

type ApiErrorPayload = { detail?: string } | string | undefined;

const ANALYZE_REQUEST_TIMEOUT_MS = 15000;
const POLL_INTERVAL_MS = 5000;
const MAX_POLL_ATTEMPTS = 120;
const MAX_TOTAL_UPLOAD_SIZE = 50 * 1024 * 1024;
const MAX_SINGLE_IMAGE_SIZE = 10 * 1024 * 1024;
const MAX_IMAGE_COUNT = 20;
const PDF_EXTENSION = '.pdf';
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png']);

const STAGE_MESSAGES: Record<string, string> = {
  upload_saved: '文件已上传，等待分析任务启动',
  ocr_parse: '正在提取试卷信息中',
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
  const llmTotal = payload.progress_total ?? 0;
  const llmCurrent = payload.progress_current ?? 0;

  if (payload.parse_status === 'pending') {
    return `分析任务已创建，等待 worker 接手${dots}`;
  }

  if (payload.last_stage === 'llm_parse' && llmTotal > 0) {
    return `已完成 ${Math.min(llmCurrent, llmTotal)}/${llmTotal} 道，正在并行分析剩余题目`;
  }

  if (payload.last_stage && STAGE_MESSAGES[payload.last_stage]) {
    return `${STAGE_MESSAGES[payload.last_stage]}${dots}`;
  }

  return `正在分析试卷${dots}`;
}

function getProcessingProgress(payload: PaperStatusPayload, attempt: number): number {
  const llmTotal = payload.progress_total ?? 0;
  const llmCurrent = payload.progress_current ?? 0;

  if (payload.parse_status === 'pending') {
    return 10;
  }

  if (payload.last_stage === 'llm_parse' && llmTotal > 0) {
    const ratio = Math.min(Math.max(llmCurrent / llmTotal, 0), 1);
    return Math.min(52 + Math.round(ratio * 30), 82);
  }

  if (payload.last_stage && STAGE_PROGRESS[payload.last_stage] !== undefined) {
    return STAGE_PROGRESS[payload.last_stage];
  }

  return Math.min(12 + attempt * 1.5, 90);
}

function getProcessingDetail(payload: PaperStatusPayload): string | undefined {
  void payload;
  return undefined;
}

function getFileExtension(file: File): string {
  const match = file.name.toLowerCase().match(/\.[^.]+$/);
  return match ? match[0] : '';
}

function isPdfFile(file: File): boolean {
  return file.type === 'application/pdf' || getFileExtension(file) === PDF_EXTENSION;
}

function isImageFile(file: File): boolean {
  return file.type === 'image/jpeg' || file.type === 'image/png' || IMAGE_EXTENSIONS.has(getFileExtension(file));
}

function formatFileSize(size: number): string {
  return `${(size / 1024 / 1024).toFixed(2)} MB`;
}

function stripKnownExtension(fileName: string): string {
  return fileName.replace(/\.(pdf|jpe?g|png)$/i, '');
}

function getTotalSelectedSize(files: SelectedUploadFile[]): number {
  return files.reduce((total, item) => total + item.file.size, 0);
}

function getSelectionKind(files: SelectedUploadFile[]): UploadKind | null {
  return files[0]?.kind ?? null;
}

function getSelectionDisplayName(files: SelectedUploadFile[]): string {
  const kind = getSelectionKind(files);
  if (!kind || files.length === 0) {
    return '未选择文件';
  }

  if (kind === 'pdf') {
    return files[0].file.name;
  }

  if (files.length === 1) {
    return files[0].file.name;
  }

  return `${files.length} 张图片（${files[0].file.name} 等）`;
}

function getPaperNameFromSelection(files: SelectedUploadFile[]): string {
  const kind = getSelectionKind(files);
  if (!kind || files.length === 0) {
    return '数学试卷';
  }

  if (kind === 'images' && files.length > 1) {
    return `${stripKnownExtension(files[0].file.name)} 等 ${files.length} 页`;
  }

  return stripKnownExtension(files[0].file.name);
}

function revokeSelectedFileUrls(files: SelectedUploadFile[]): void {
  files.forEach((item) => {
    if (item.previewUrl) {
      URL.revokeObjectURL(item.previewUrl);
    }
  });
}

export function PDFUploadPage() {
  const navigate = useNavigate();
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>({
    status: 'idle',
    message: '准备上传',
  });
  const [selectedFiles, setSelectedFiles] = useState<SelectedUploadFile[]>([]);
  const [uploadedFile, setUploadedFile] = useState<UploadedFile | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const selectedFilesRef = useRef<SelectedUploadFile[]>([]);

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

  useEffect(() => {
    selectedFilesRef.current = selectedFiles;
  }, [selectedFiles]);

  useEffect(
    () => () => {
      revokeSelectedFileUrls(selectedFilesRef.current);
    },
    [],
  );

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
              detail: undefined,
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
            detail: getProcessingDetail(payload),
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
    (acceptedFiles: File[]) => {
      if (!acceptedFiles.length) {
        return;
      }

      const pdfFiles = acceptedFiles.filter(isPdfFile);
      const imageFiles = acceptedFiles.filter(isImageFile);
      const unsupportedFiles = acceptedFiles.filter((item) => !isPdfFile(item) && !isImageFile(item));

      if (unsupportedFiles.length > 0) {
        setUploadStatus({ status: 'error', message: '仅支持 PDF、JPG、PNG 格式。' });
        return;
      }

      if (pdfFiles.length > 0 && imageFiles.length > 0) {
        setUploadStatus({ status: 'error', message: 'PDF 和图片不能混合上传。' });
        return;
      }

      if (pdfFiles.length > 1) {
        setUploadStatus({ status: 'error', message: 'PDF 只能上传一个文件。' });
        return;
      }

      if (imageFiles.length > MAX_IMAGE_COUNT) {
        setUploadStatus({ status: 'error', message: `图片最多上传 ${MAX_IMAGE_COUNT} 张。` });
        return;
      }

      const oversizedImage = imageFiles.find((item) => item.size > MAX_SINGLE_IMAGE_SIZE);
      if (oversizedImage) {
        setUploadStatus({ status: 'error', message: `图片 ${oversizedImage.name} 超过 10MB 限制。` });
        return;
      }

      const totalSize = acceptedFiles.reduce((total, item) => total + item.size, 0);
      if (totalSize > MAX_TOTAL_UPLOAD_SIZE) {
        setUploadStatus({ status: 'error', message: '上传文件总大小超过 50MB 限制。' });
        return;
      }

      const nextFiles: SelectedUploadFile[] = acceptedFiles.map((item, index) => ({
        id: `${item.name}-${item.size}-${item.lastModified}-${index}`,
        file: item,
        kind: isPdfFile(item) ? 'pdf' : 'images',
        previewUrl: isImageFile(item) ? URL.createObjectURL(item) : undefined,
      }));

      clearPollTimer();
      revokeSelectedFileUrls(selectedFilesRef.current);
      setSelectedFiles(nextFiles);
      setUploadedFile(null);
      setUploadStatus({
        status: 'idle',
        message:
          nextFiles[0].kind === 'images'
            ? `已选择 ${nextFiles.length} 张图片，请确认页序后开始分析。`
            : '已选择 PDF 文件，可以开始分析。',
      });
    },
    [clearPollTimer],
  );

  const onDropRejected = useCallback(() => {
    setUploadStatus({ status: 'error', message: '仅支持 PDF、JPG、PNG，图片最多 20 张。' });
  }, []);

  const handleStartAnalysis = useCallback(async () => {
    if (!selectedFiles.length) {
      setUploadStatus({ status: 'error', message: '请先选择试卷文件或图片。' });
      return;
    }

    const uploadKind = getSelectionKind(selectedFiles);
    const totalSize = getTotalSelectedSize(selectedFiles);
    const displayName = getSelectionDisplayName(selectedFiles);

    clearPollTimer();
    setUploadedFile({
      name: displayName,
      size: totalSize,
      fileCount: selectedFiles.length,
      kind: uploadKind || 'pdf',
    });
    setUploadStatus({
      status: 'uploading',
      message: '正在上传试卷文件...',
      progress: 2,
    });

    try {
      const formData = new FormData();
      if (uploadKind === 'images') {
        selectedFiles.forEach((item) => formData.append('files', item.file));
      } else {
        formData.append('file', selectedFiles[0].file);
      }
      formData.append('paper_name', getPaperNameFromSelection(selectedFiles));

      let requestSettled = false;

      const response = await axios.post<AnalyzeResponsePayload>('/api/v1/papers/analyze', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: ANALYZE_REQUEST_TIMEOUT_MS,
        onUploadProgress: (event: AxiosProgressEvent) => {
          if (requestSettled) {
            return;
          }

          const total = event.total ?? totalSize;
          if (!total) {
            setUploadStatus({
              status: 'uploading',
              message: '正在上传试卷文件...',
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
            message: '正在上传试卷文件...',
            progress: Math.max(percent, 2),
          });
        },
      });

      requestSettled = true;
      const paperId = response.data.paper_id;

      setUploadedFile({
        name: displayName,
        size: totalSize,
        fileCount: selectedFiles.length,
        kind: uploadKind || 'pdf',
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
  }, [clearPollTimer, pollPaperStatus, selectedFiles]);

  const handleReupload = useCallback(() => {
    clearPollTimer();
    revokeSelectedFileUrls(selectedFilesRef.current);
    selectedFilesRef.current = [];
    setSelectedFiles([]);
    setUploadedFile(null);
    setUploadStatus({
      status: 'idle',
      message: '准备上传',
    });
  }, [clearPollTimer]);

  const handleRemoveSelectedFile = useCallback(
    (fileId: string) => {
      const nextFiles = selectedFiles.filter((item) => item.id !== fileId);
      const removedFile = selectedFiles.find((item) => item.id === fileId);
      revokeSelectedFileUrls(removedFile ? [removedFile] : []);
      setSelectedFiles(nextFiles);
      setUploadStatus({
        status: 'idle',
        message: nextFiles.length ? `已选择 ${nextFiles.length} 张图片，请确认页序后开始分析。` : '准备上传',
      });
    },
    [selectedFiles],
  );

  const handleMoveSelectedFile = useCallback((index: number, direction: -1 | 1) => {
    setSelectedFiles((current) => {
      const targetIndex = index + direction;
      if (targetIndex < 0 || targetIndex >= current.length) {
        return current;
      }

      const nextFiles = [...current];
      const [moved] = nextFiles.splice(index, 1);
      nextFiles.splice(targetIndex, 0, moved);
      return nextFiles;
    });
  }, []);

  const isBusy = uploadStatus.status === 'uploading' || uploadStatus.status === 'processing';
  const selectedTotalSize = getTotalSelectedSize(selectedFiles);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: {
      'application/pdf': ['.pdf'],
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
    },
    maxFiles: MAX_IMAGE_COUNT,
    disabled: isBusy,
  });

  const submittedFile = uploadStatus.status !== 'idle' && uploadStatus.status !== 'error' ? uploadedFile : null;

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
          <div className="text-sm text-slate-500">上传 PDF 或图片并创建分析任务</div>
        </div>
      </nav>

      <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6 lg:px-8">
        <section>
          <div className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-[0_24px_70px_-42px_rgba(15,23,42,0.35)]">
            <div className="max-w-2xl">
              <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-blue-700">
                <FileText className="h-3.5 w-3.5" />
                Paper Upload
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-slate-900">上传试卷，进入分析队列</h1>
            </div>

            {uploadStatus.status !== 'idle' && (
              <div
                className={`mt-5 rounded-2xl border px-5 py-4 ${
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
                {uploadStatus.detail && (
                  <div className="mt-2 pl-8 text-xs opacity-80">{uploadStatus.detail}</div>
                )}
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

            {submittedFile ? (
              <div className="mt-5 rounded-[20px] border border-slate-200 bg-slate-50 p-6">
                <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-500">当前文件</div>
                    <div className="mt-2 text-xl font-semibold text-slate-900">{submittedFile.name}</div>
                    <div className="mt-1 text-sm text-slate-500">
                      {submittedFile.kind === 'images' ? `${submittedFile.fileCount} 张图片 · ` : ''}
                      {formatFileSize(submittedFile.size)}
                      {submittedFile.paperId ? ` · paper_id: ${submittedFile.paperId}` : ''}
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
            ) : selectedFiles.length > 0 ? (
              <div className="mt-5 rounded-[20px] border border-slate-200 bg-slate-50 p-5">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-500">
                      {getSelectionKind(selectedFiles) === 'images' ? '图片页序' : '已选择文件'}
                    </div>
                    <div className="mt-1 text-lg font-semibold text-slate-900">
                      {getSelectionDisplayName(selectedFiles)}
                    </div>
                    <div className="mt-1 text-sm text-slate-500">
                      {selectedFiles.length} 个文件 · {formatFileSize(selectedTotalSize)}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={handleReupload}
                      className="inline-flex items-center justify-center rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-100"
                    >
                      清空
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void handleStartAnalysis();
                      }}
                      disabled={isBusy}
                      className="inline-flex items-center justify-center gap-2 rounded-full border border-slate-900 bg-slate-900 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <Upload className="h-4 w-4" />
                      开始分析
                    </button>
                  </div>
                </div>

                <div className="mt-4 grid gap-3">
                  {selectedFiles.map((item, index) => (
                    <div
                      key={item.id}
                      className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-3"
                    >
                      <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-slate-100 text-slate-600">
                        {item.previewUrl ? (
                          <img src={item.previewUrl} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <FileText className="h-6 w-6" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold text-slate-900">
                          {item.kind === 'images' ? `第 ${index + 1} 页 · ` : ''}
                          {item.file.name}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">{formatFileSize(item.file.size)}</div>
                      </div>
                      {item.kind === 'images' ? (
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => handleMoveSelectedFile(index, -1)}
                            disabled={index === 0}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                            aria-label="上移图片"
                            title="上移"
                          >
                            <ArrowUp className="h-4 w-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleMoveSelectedFile(index, 1)}
                            disabled={index === selectedFiles.length - 1}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
                            aria-label="下移图片"
                            title="下移"
                          >
                            <ArrowDown className="h-4 w-4" />
                          </button>
                        </div>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => handleRemoveSelectedFile(item.id)}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600"
                        aria-label="移除文件"
                        title="移除"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div
                {...getRootProps()}
                className={`mt-5 rounded-[24px] border-2 border-dashed px-8 py-8 text-center transition ${
                  isDragActive
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-slate-300 bg-slate-50/70 hover:border-slate-400 hover:bg-white'
                } ${uploadStatus.status === 'uploading' ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}
              >
                <input {...getInputProps()} />
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900 text-white">
                  {isDragActive ? <ImageIcon className="h-6 w-6" /> : <Upload className="h-6 w-6" />}
                </div>
                <div className="mt-4 text-xl font-semibold text-slate-900">
                  {isDragActive ? '松开文件即可加入列表' : '点击或拖拽上传 PDF / 图片'}
                </div>
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  PDF 单文件；图片支持 JPG/PNG，最多 20 张，单张不超过 10MB。
                </p>
              </div>
            )}
          </div>

        </section>

        <section className="mt-6 rounded-[24px] border border-slate-200 bg-white p-6 shadow-[0_24px_70px_-42px_rgba(15,23,42,0.18)]">
          <div className="flex items-end justify-between gap-4">
            <div>
              <div className="text-sm font-semibold uppercase tracking-[0.22em] text-slate-500">Six Dimensions</div>
              <h2 className="mt-1 text-2xl font-semibold text-slate-900">分析维度概览</h2>
            </div>
            <div className="text-sm text-slate-500">上传成功后自动进入后台分析</div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {features.map((item) => (
              <div key={item.title} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <item.icon className="h-5 w-5 text-slate-700" />
                <div className="mt-2 text-sm font-semibold text-slate-900">{item.title}</div>
                <p className="mt-1 text-xs leading-5 text-slate-500">{item.desc}</p>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default PDFUploadPage;
