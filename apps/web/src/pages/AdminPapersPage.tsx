import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock3,
  ExternalLink,
  FileText,
  KeyRound,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { Link } from 'react-router-dom';

type AdminStatusFilter = 'failed' | 'parsing' | 'success' | 'all';

type AdminPaperItem = {
  paper_id: string;
  paper_name: string;
  parse_status: string;
  last_stage: string | null;
  stage_display: string;
  error_message: string | null;
  failure_reason_display: string | null;
  failure_solution_display: string | null;
  cancel_requested: boolean;
  cancel_requested_at: string | null;
  can_cancel: boolean;
  total_question_count: number;
  created_at: string;
  updated_at: string;
};

type AdminPaperListResponse = {
  summary: {
    total: number;
    parsing: number;
    success: number;
    failed: number;
  };
  items: AdminPaperItem[];
  page: number;
  page_size: number;
  total: number;
};

const TOKEN_STORAGE_KEY = 'math_analysis_admin_token';
const PAGE_SIZE = 20;

const statusOptions: Array<{ value: AdminStatusFilter; label: string }> = [
  { value: 'failed', label: '失败' },
  { value: 'parsing', label: '分析中' },
  { value: 'success', label: '成功' },
  { value: 'all', label: '全部' },
];

function getStoredToken() {
  if (typeof window === 'undefined') {
    return '';
  }
  return window.sessionStorage.getItem(TOKEN_STORAGE_KEY) ?? '';
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getStatusLabel(status: string) {
  if (status === 'parse_success') {
    return '成功';
  }
  if (status === 'parse_failed') {
    return '失败';
  }
  if (status === 'parsing') {
    return '分析中';
  }
  if (status === 'pending') {
    return '排队中';
  }
  return status;
}

function statusBadgeClass(status: string) {
  if (status === 'parse_failed') {
    return 'bg-red-50 text-red-700 ring-red-200';
  }
  if (status === 'parse_success') {
    return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
  }
  return 'bg-amber-50 text-amber-700 ring-amber-200';
}

function PaperCard({
  canceling,
  item,
  onCancel,
}: {
  canceling: boolean;
  item: AdminPaperItem;
  onCancel: (item: AdminPaperItem) => void;
}) {
  const isFailed = item.parse_status === 'parse_failed';
  const isSuccess = item.parse_status === 'parse_success';
  const showCancel = item.can_cancel && !isFailed && !isSuccess;

  return (
    <article className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm text-gray-500">
            <span>{formatDateTime(item.created_at)}</span>
            <span className={`rounded-full px-2 py-1 text-xs font-medium ring-1 ${statusBadgeClass(item.parse_status)}`}>
              {getStatusLabel(item.parse_status)}
            </span>
          </div>
          <h2 className="truncate text-base font-semibold text-gray-950">{item.paper_name}</h2>
          <p className="mt-1 break-all text-xs text-gray-500">paper_id: {item.paper_id}</p>
        </div>

        <div className="flex shrink-0 gap-2">
          {showCancel ? (
            <button
              className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 text-sm font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={canceling || item.cancel_requested}
              onClick={() => onCancel(item)}
              type="button"
            >
              <Ban className="h-4 w-4" />
              {item.cancel_requested ? '正在终止' : '终止分析'}
            </button>
          ) : null}
          {isSuccess ? (
            <Link
              className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-gray-950 px-3 text-sm font-medium text-white transition hover:bg-gray-800"
              to={`/report/${item.paper_id}`}
            >
              <ExternalLink className="h-4 w-4" />
              查看报告
            </Link>
          ) : null}
        </div>
      </div>

      {isFailed ? (
        <div className="mt-4 grid gap-3">
          <div>
            <div className="text-xs font-medium text-gray-500">失败阶段</div>
            <div className="mt-1 text-sm text-gray-900">{item.stage_display}</div>
          </div>
          <div>
            <div className="text-xs font-medium text-gray-500">失败原因</div>
            <div className="mt-1 text-sm text-red-700">{item.failure_reason_display || item.error_message || '暂无详细错误'}</div>
          </div>
          <div className="rounded-md bg-blue-50 p-3">
            <div className="text-xs font-medium text-blue-700">建议解决方案</div>
            <div className="mt-1 text-sm leading-6 text-blue-950">
              {item.failure_solution_display || '复制 paper_id 后查看 api/worker 日志，再根据具体错误处理。'}
            </div>
          </div>
        </div>
      ) : null}

      {!isFailed && !isSuccess ? (
        <div className="mt-4 grid gap-2 text-sm">
          {item.cancel_requested ? <div className="font-medium text-amber-700">正在终止，等待当前阶段安全退出</div> : null}
          <div>
            <span className="text-gray-500">当前阶段：</span>
            <span className="text-gray-900">{item.stage_display}</span>
          </div>
          <div>
            <span className="text-gray-500">最近更新：</span>
            <span className="text-gray-900">{formatDateTime(item.updated_at)}</span>
          </div>
        </div>
      ) : null}

      {isSuccess ? (
        <div className="mt-4 text-sm text-gray-700">
          <span className="text-gray-500">题目数：</span>
          {item.total_question_count}
        </div>
      ) : null}
    </article>
  );
}

export default function AdminPapersPage() {
  const [adminToken, setAdminToken] = useState(getStoredToken);
  const [tokenInput, setTokenInput] = useState('');
  const [status, setStatus] = useState<AdminStatusFilter>('failed');
  const [searchInput, setSearchInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AdminPaperListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [cancelingIds, setCancelingIds] = useState<Set<string>>(() => new Set());

  const hasNextPage = useMemo(() => {
    if (!data) {
      return false;
    }
    return data.page * data.page_size < data.total;
  }, [data]);

  const loadPapers = useCallback(async () => {
    if (!adminToken) {
      return;
    }

    setLoading(true);
    setErrorMessage('');
    try {
      const params = new URLSearchParams({
        status,
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (keyword.trim()) {
        params.set('keyword', keyword.trim());
      }

      const response = await fetch(`/api/v1/admin/papers?${params.toString()}`, {
        headers: {
          'X-Admin-Token': adminToken,
        },
      });

      if (response.status === 401 || response.status === 403) {
        window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
        setAdminToken('');
        setErrorMessage('后台口令不正确，请重新输入。');
        return;
      }

      if (response.status === 503) {
        setErrorMessage('服务器还没有配置 ADMIN_TOKEN，请先在 .env 中设置后台访问口令并重启服务。');
        return;
      }

      if (!response.ok) {
        setErrorMessage(`后台记录加载失败，HTTP ${response.status}`);
        return;
      }

      const payload = (await response.json()) as AdminPaperListResponse;
      setData(payload);
    } catch {
      setErrorMessage('无法连接后台接口，请检查 API 服务是否正常。');
    } finally {
      setLoading(false);
    }
  }, [adminToken, keyword, page, status]);

  useEffect(() => {
    void loadPapers();
  }, [loadPapers]);

  useEffect(() => {
    if (!adminToken || status !== 'parsing') {
      return undefined;
    }
    const timer = window.setInterval(() => {
      void loadPapers();
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [adminToken, loadPapers, status]);

  function submitToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = tokenInput.trim();
    if (!token) {
      setErrorMessage('请输入后台访问口令。');
      return;
    }
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
    setAdminToken(token);
    setTokenInput('');
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setKeyword(searchInput);
  }

  function changeStatus(nextStatus: AdminStatusFilter) {
    setStatus(nextStatus);
    setPage(1);
  }

  async function cancelPaper(item: AdminPaperItem) {
    const confirmed = window.confirm(`确定终止“${item.paper_name}”的分析吗？终止后不会继续生成报告，需要重新上传才能重新分析。`);
    if (!confirmed) {
      return;
    }

    setCancelingIds((current) => {
      const next = new Set(current);
      next.add(item.paper_id);
      return next;
    });
    setErrorMessage('');

    try {
      const response = await fetch(`/api/v1/admin/papers/${item.paper_id}/cancel`, {
        method: 'POST',
        headers: {
          'X-Admin-Token': adminToken,
        },
      });

      if (response.status === 401 || response.status === 403) {
        window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
        setAdminToken('');
        setErrorMessage('后台口令不正确，请重新输入。');
        return;
      }

      if (!response.ok) {
        setErrorMessage(response.status === 409 ? '当前试卷已经结束，不能终止分析。' : `终止分析失败，HTTP ${response.status}`);
        return;
      }

      await loadPapers();
    } catch {
      setErrorMessage('终止分析请求失败，请检查 API 服务是否正常。');
    } finally {
      setCancelingIds((current) => {
        const next = new Set(current);
        next.delete(item.paper_id);
        return next;
      });
    }
  }

  if (!adminToken) {
    return (
      <main className="min-h-screen bg-gray-50 px-4 py-10">
        <section className="mx-auto max-w-md rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-gray-950 text-white">
              <KeyRound className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-gray-950">后台上传记录</h1>
              <p className="text-sm text-gray-500">查看试卷状态、失败原因和解决方案</p>
            </div>
          </div>

          <form className="grid gap-4" onSubmit={submitToken}>
            <label className="grid gap-2 text-sm font-medium text-gray-700">
              后台访问口令
              <input
                className="h-11 rounded-md border border-gray-300 px-3 text-base outline-none transition focus:border-gray-950 focus:ring-2 focus:ring-gray-200"
                onChange={(event) => setTokenInput(event.target.value)}
                type="password"
                value={tokenInput}
              />
            </label>
            {errorMessage ? <p className="text-sm text-red-600">{errorMessage}</p> : null}
            <button className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-gray-950 px-4 text-sm font-medium text-white transition hover:bg-gray-800">
              <ShieldCheck className="h-4 w-4" />
              进入后台
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50 px-4 py-6">
      <div className="mx-auto grid max-w-6xl gap-5">
        <header className="flex flex-col gap-4 border-b border-gray-200 pb-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-500">
              <FileText className="h-4 w-4" />
              内部后台
            </div>
            <h1 className="text-2xl font-semibold text-gray-950">上传记录</h1>
            <p className="mt-1 text-sm text-gray-500">重点排查失败试卷；成功记录保留报告入口。</p>
          </div>
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-gray-300 bg-white px-3 text-sm font-medium text-gray-800 transition hover:bg-gray-100"
            disabled={loading}
            onClick={() => void loadPapers()}
            type="button"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </header>

        <section className="grid gap-3 sm:grid-cols-4">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="text-xs font-medium text-gray-500">总上传数</div>
            <div className="mt-2 text-2xl font-semibold text-gray-950">{data?.summary.total ?? '-'}</div>
          </div>
          <div className="rounded-lg border border-amber-200 bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-amber-700">
              <Clock3 className="h-4 w-4" />
              分析中
            </div>
            <div className="mt-2 text-2xl font-semibold text-gray-950">{data?.summary.parsing ?? '-'}</div>
          </div>
          <div className="rounded-lg border border-emerald-200 bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-emerald-700">
              <CheckCircle2 className="h-4 w-4" />
              成功
            </div>
            <div className="mt-2 text-2xl font-semibold text-gray-950">{data?.summary.success ?? '-'}</div>
          </div>
          <div className="rounded-lg border border-red-200 bg-white p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-red-700">
              <AlertTriangle className="h-4 w-4" />
              失败
            </div>
            <div className="mt-2 text-2xl font-semibold text-gray-950">{data?.summary.failed ?? '-'}</div>
          </div>
        </section>

        <section className="flex flex-col gap-3 rounded-lg border border-gray-200 bg-white p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap gap-2">
            {statusOptions.map((option) => (
              <button
                className={`h-9 rounded-md px-3 text-sm font-medium transition ${
                  status === option.value ? 'bg-gray-950 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
                key={option.value}
                onClick={() => changeStatus(option.value)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>

          <form className="flex w-full gap-2 sm:w-auto" onSubmit={submitSearch}>
            <label className="relative min-w-0 flex-1 sm:w-80">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                className="h-10 w-full rounded-md border border-gray-300 pl-9 pr-3 text-sm outline-none transition focus:border-gray-950 focus:ring-2 focus:ring-gray-200"
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="搜索试卷名或 paper_id"
                value={searchInput}
              />
            </label>
            <button className="h-10 rounded-md bg-gray-950 px-4 text-sm font-medium text-white transition hover:bg-gray-800">
              搜索
            </button>
          </form>
        </section>

        {errorMessage ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{errorMessage}</div>
        ) : null}

        <section className="grid gap-3">
          {loading && !data ? <div className="rounded-lg border border-gray-200 bg-white p-5 text-sm text-gray-500">正在加载...</div> : null}
          {!loading && data && data.items.length === 0 ? (
            <div className="rounded-lg border border-gray-200 bg-white p-5 text-sm text-gray-500">当前筛选下没有上传记录。</div>
          ) : null}
          {data?.items.map((item) => (
            <PaperCard
              canceling={cancelingIds.has(item.paper_id)}
              item={item}
              key={item.paper_id}
              onCancel={cancelPaper}
            />
          ))}
        </section>

        {data ? (
          <footer className="flex items-center justify-between pb-4 text-sm text-gray-600">
            <span>
              第 {data.page} 页，共 {data.total} 条
            </span>
            <div className="flex gap-2">
              <button
                className="h-9 rounded-md border border-gray-300 bg-white px-3 font-medium disabled:cursor-not-allowed disabled:opacity-50"
                disabled={page <= 1 || loading}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                type="button"
              >
                上一页
              </button>
              <button
                className="h-9 rounded-md border border-gray-300 bg-white px-3 font-medium disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!hasNextPage || loading}
                onClick={() => setPage((current) => current + 1)}
                type="button"
              >
                下一页
              </button>
            </div>
          </footer>
        ) : null}
      </div>
    </main>
  );
}
