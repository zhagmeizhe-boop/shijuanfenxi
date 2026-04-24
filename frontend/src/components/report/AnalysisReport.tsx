"use client";

import { AnalysisResult } from "@/types/analysis";
import { SixDimensionsRadar } from "./SixDimensionsRadar";
import { DimensionScoreCard } from "./DimensionScoreCard";
import { KnowledgePointList } from "./KnowledgePointList";
import { DifficultyBadge } from "./DifficultyBadge";
import { ComparisonChart } from "./ComparisonChart";
import { ArrowLeft, Download, FileText, Calendar, Target, Users, BookOpen } from "lucide-react";

interface AnalysisReportProps {
  result: AnalysisResult;
  onReset: () => void;
}

const dimensionNames: Record<string, { name: string; desc: string; color: string }> = {
  computation: { name: "计算熟练度", desc: "口算、笔算、估算等计算能力", color: "#3B82F6" },
  concept: { name: "概念清晰度", desc: "数学概念、定义、符号的理解", color: "#8B5CF6" },
  logic: { name: "逻辑推理力", desc: "数学推理、证明、归纳能力", color: "#EC4899" },
  spatial: { name: "空间想象力", desc: "几何、图形、空间关系理解", color: "#10B981" },
  application: { name: "应用实践力", desc: "实际问题建模与解决能力", color: "#F59E0B" },
  innovation: { name: "创新思维力", desc: "开放题、拓展题的创造性解答", color: "#EF4444" },
};

export function AnalysisReport({ result, onReset }: AnalysisReportProps) {
  const handleDownloadPDF = () => {
    // TODO: 实现 PDF 下载功能
    console.log("下载 PDF 报告", result.id);
  };

  return (
    <div className="space-y-8">
      {/* Header Actions */}
      <div className="flex items-center justify-between">
        <button
          onClick={onReset}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
          <span>返回上传</span>
        </button>
        <button
          onClick={handleDownloadPDF}
          className="flex items-center gap-2 bg-gradient-to-r from-blue-500 to-purple-600 text-white px-6 py-2.5 rounded-xl font-medium hover:shadow-lg hover:shadow-blue-500/25 transition-all"
        >
          <Download className="w-5 h-5" />
          <span>下载 PDF 报告</span>
        </button>
      </div>

      {/* Paper Info Card */}
      <div className="bg-white rounded-2xl shadow-lg shadow-gray-200/50 overflow-hidden">
        <div className="bg-gradient-to-r from-blue-500 to-purple-600 px-8 py-6">
          <h1 className="text-2xl font-bold text-white mb-2">
            {result.paper_info.title}
          </h1>
          <p className="text-blue-100">
            {result.paper_info.grade} · {result.paper_info.subject}
          </p>
        </div>
        <div className="p-8">
          <div className="grid grid-cols-4 gap-6">
            <div className="flex items-center gap-4 p-4 bg-gray-50 rounded-xl">
              <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6 text-blue-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">总题数</p>
                <p className="text-xl font-bold text-gray-900">{result.paper_info.question_count} 题</p>
              </div>
            </div>
            <div className="flex items-center gap-4 p-4 bg-gray-50 rounded-xl">
              <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                <Target className="w-6 h-6 text-purple-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">总分</p>
                <p className="text-xl font-bold text-gray-900">{result.paper_info.total_score} 分</p>
              </div>
            </div>
            <div className="flex items-center gap-4 p-4 bg-gray-50 rounded-xl">
              <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
                <Calendar className="w-6 h-6 text-green-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">分析时间</p>
                <p className="text-sm font-semibold text-gray-900">
                  {new Date(result.generated_at).toLocaleDateString('zh-CN')}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4 p-4 bg-gray-50 rounded-xl">
              <div className="w-12 h-12 bg-orange-100 rounded-lg flex items-center justify-center">
                <BookOpen className="w-6 h-6 text-orange-600" />
              </div>
              <div>
                <p className="text-sm text-gray-500">来源</p>
                <p className="text-sm font-semibold text-gray-900 truncate max-w-[120px]">
                  {result.paper_info.source || '未知来源'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Six Dimensions Radar Chart */}
      <div className="grid grid-cols-3 gap-8">
        <div className="col-span-2 bg-white rounded-2xl shadow-lg shadow-gray-200/50 p-8">
          <SixDimensionsRadar dimensions={result.dimensions} />
        </div>
        <div className="space-y-4">
          <DifficultyBadge difficulty={result.difficulty} />
          <div className="bg-white rounded-2xl shadow-lg shadow-gray-200/50 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Users className="w-5 h-5 text-purple-500" />
              适合学生群体
            </h3>
            <div className="space-y-2">
              {result.target_students.map((student, i) => (
                <div key={i} className="flex items-center gap-2 text-sm text-gray-600">
                  <div className="w-1.5 h-1.5 bg-purple-400 rounded-full" />
                  {student}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Dimension Score Cards */}
      <div className="bg-white rounded-2xl shadow-lg shadow-gray-200/50 p-8">
        <h2 className="text-xl font-bold text-gray-900 mb-6">六维能力详细评分</h2>
        <DimensionScoreCard dimensions={result.dimensions} dimensionNames={dimensionNames} />
      </div>

      {/* Comparison Chart */}
      <div className="bg-white rounded-2xl shadow-lg shadow-gray-200/50 p-8">
        <ComparisonChart comparison={result.comparison} />
      </div>

      {/* Knowledge Points */}
      <div className="bg-white rounded-2xl shadow-lg shadow-gray-200/50 p-8">
        <KnowledgePointList knowledgePoints={result.knowledge_points} />
      </div>
    </div>
  );
}
