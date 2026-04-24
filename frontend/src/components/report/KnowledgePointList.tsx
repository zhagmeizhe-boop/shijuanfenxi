"use client";

import { KnowledgePoint } from "@/types/analysis";
import { BookOpen, ChevronRight, CheckCircle2 } from "lucide-react";

interface KnowledgePointListProps {
  knowledgePoints: KnowledgePoint[];
}

const getDifficultyColor = (difficulty: number) => {
  if (difficulty >= 4.5) return "text-red-600 bg-red-50";
  if (difficulty >= 3.5) return "text-orange-600 bg-orange-50";
  if (difficulty >= 2.5) return "text-yellow-600 bg-yellow-50";
  return "text-green-600 bg-green-50";
};

const getDifficultyLabel = (difficulty: number) => {
  if (difficulty >= 4.5) return "很难";
  if (difficulty >= 3.5) return "较难";
  if (difficulty >= 2.5) return "中等";
  return "简单";
};

export function KnowledgePointList({ knowledgePoints }: KnowledgePointListProps) {
  // 按类别分组
  const groupedByCategory = knowledgePoints.reduce((acc, kp) => {
    if (!acc[kp.category]) {
      acc[kp.category] = [];
    }
    acc[kp.category].push(kp);
    return acc;
  }, {} as Record<string, KnowledgePoint[]>);

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <BookOpen className="w-6 h-6 text-purple-500" />
        <h3 className="text-xl font-bold text-gray-900">知识点覆盖清单</h3>
      </div>

      <div className="space-y-6">
        {Object.entries(groupedByCategory).map(([category, points]) => (
          <div key={category} className="bg-gray-50 rounded-xl p-5">
            <h4 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-green-500" />
              {category}
            </h4>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {points.map((point, index) => (
                <div
                  key={index}
                  className="bg-white rounded-lg p-4 border border-gray-200 hover:shadow-md transition-shadow"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-gray-900 truncate">
                        {point.name}
                      </p>
                      <p className="text-xs text-gray-500 mt-1">
                        {point.count} 道题目
                      </p>
                    </div>
                    <div className={`px-2 py-1 rounded text-xs font-medium ${getDifficultyColor(point.difficulty_avg)}`}>
                      {getDifficultyLabel(point.difficulty_avg)}
                    </div>
                  </div>

                  <div className="mt-3 flex items-center gap-2">
                    <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-blue-400 to-purple-500"
                        style={{ width: `${Math.min((point.difficulty_avg / 5) * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500 min-w-[40px]">
                      {point.difficulty_avg.toFixed(1)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
