"use client";

import { ComparisonData } from "@/types/analysis";
import { BarChart2, TrendingUp, Users, Award } from "lucide-react";

interface ComparisonChartProps {
  comparison: ComparisonData;
}

export function ComparisonChart({ comparison }: ComparisonChartProps) {
  const percentile = comparison.percentile;
  const isAboveAverage = percentile > 50;

  // 计算在分布曲线上的位置
  const position = Math.min(Math.max(percentile, 5), 95);

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <BarChart2 className="w-6 h-6 text-purple-500" />
        <h3 className="text-xl font-bold text-gray-900">与参照系对比</h3>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 统计卡片 */}
        <div className="space-y-4">
          <div className="bg-gradient-to-br from-blue-50 to-blue-100 rounded-xl p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-blue-500 rounded-lg flex items-center justify-center">
                <Award className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-sm text-blue-600 font-medium">当前试卷</p>
                <p className="text-2xl font-bold text-blue-700">{comparison.currentScore}分</p>
              </div>
            </div>
          </div>

          <div className="bg-gradient-to-br from-purple-50 to-purple-100 rounded-xl p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-purple-500 rounded-lg flex items-center justify-center">
                <Users className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-sm text-purple-600 font-medium">{comparison.benchmark}</p>
                <p className="text-2xl font-bold text-purple-700">{comparison.averageScore}分</p>
              </div>
            </div>
          </div>

          <div className={`rounded-xl p-4 ${isAboveAverage ? 'bg-green-50' : 'bg-orange-50'}`}>
            <div className="flex items-center justify-between">
              <div>
                <p className={`text-sm font-medium ${isAboveAverage ? 'text-green-600' : 'text-orange-600'}`}>
                  超越比例
                </p>
                <p className={`text-2xl font-bold ${isAboveAverage ? 'text-green-700' : 'text-orange-700'}`}>
                  前 {100 - percentile}%
                </p>
              </div>
              <div className={`w-14 h-14 rounded-full flex items-center justify-center ${isAboveAverage ? 'bg-green-100' : 'bg-orange-100'}`}>
                <TrendingUp className={`w-7 h-7 ${isAboveAverage ? 'text-green-600' : 'text-orange-600'}`} />
              </div>
            </div>
          </div>
        </div>

        {/* 分布图 */}
        <div className="lg:col-span-2 bg-gray-50 rounded-xl p-6">
          <h4 className="text-sm font-medium text-gray-700 mb-4">成绩分布对比</h4>

          {/* 分布曲线示意 */}
          <div className="relative h-40 mb-6">
            {/* 正态分布曲线 */}
            <svg viewBox="0 0 400 100" className="w-full h-full">
              {/* 曲线 */}
              <path
                d="M 0,90 Q 50,85 100,60 Q 150,35 200,20 Q 250,35 300,60 Q 350,85 400,90"
                fill="none"
                stroke="#E5E7EB"
                strokeWidth="2"
              />
              {/* 填充区域 */}
              <path
                d="M 0,90 Q 50,85 100,60 Q 150,35 200,20 Q 250,35 300,60 Q 350,85 400,90 L 400,100 L 0,100 Z"
                fill="url(#gradient)"
                opacity="0.3"
              />
              <defs>
                <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#3B82F6" />
                  <stop offset="50%" stopColor="#8B5CF6" />
                  <stop offset="100%" stopColor="#EC4899" />
                </linearGradient>
              </defs>
            </svg>

            {/* 当前位置标记 */}
            <div
              className="absolute top-0 transform -translate-x-1/2"
              style={{ left: `${position}%` }}
            >
              <div className="flex flex-col items-center">
                <div className="bg-blue-500 text-white text-xs font-bold px-2 py-1 rounded mb-1 whitespace-nowrap">
                  当前试卷
                </div>
                <div className="w-0.5 h-20 bg-blue-500"></div>
                <div className="w-4 h-4 bg-blue-500 rounded-full border-2 border-white shadow-lg"></div>
              </div>
            </div>

            {/* 平均线标记 */}
            <div className="absolute top-0 left-1/2 transform -translate-x-1/2">
              <div className="flex flex-col items-center">
                <div className="w-4 h-4 bg-gray-400 rounded-full border-2 border-white shadow-lg"></div>
                <div className="w-0.5 h-16 bg-gray-300"></div>
                <div className="bg-gray-100 text-gray-600 text-xs font-medium px-2 py-1 rounded mt-1">
                  平均分
                </div>
              </div>
            </div>
          </div>

          {/* 图例 */}
          <div className="flex items-center justify-center gap-8 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-blue-500 rounded-full"></div>
              <span className="text-gray-600">当前试卷</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-gray-400 rounded-full"></div>
              <span className="text-gray-600">平均分</span>
            </div>
          </div>

          {/* 结论 */}
          <div className={`mt-6 p-4 rounded-lg ${isAboveAverage ? 'bg-green-50 border border-green-200' : 'bg-orange-50 border border-orange-200'}`}>
            <p className={`text-sm ${isAboveAverage ? 'text-green-800' : 'text-orange-800'}`}>
              <span className="font-semibold">
                {isAboveAverage ? '表现优异！' : '还有提升空间。'}
              </span>
              该试卷难度{isAboveAverage ? '高于' : '接近'}平均水平，
              {isAboveAverage
                ? `超越了 ${percentile}% 的同类试卷，适合作为拔高训练使用。`
                : `适合用于巩固基础，建议适当增加挑战难度。`}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
