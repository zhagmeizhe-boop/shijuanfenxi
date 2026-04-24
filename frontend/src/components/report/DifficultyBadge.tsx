"use client";

import { DifficultyLevel } from "@/types/analysis";
import { BarChart3, TrendingUp, TrendingDown, Minus } from "lucide-react";

interface DifficultyBadgeProps {
  difficulty: DifficultyLevel;
}

const difficultyConfig: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  very_easy: {
    label: "非常简单",
    color: "text-green-600",
    bg: "bg-green-50",
    icon: <TrendingDown className="w-5 h-5" />,
  },
  easy: {
    label: "简单",
    color: "text-emerald-600",
    bg: "bg-emerald-50",
    icon: <TrendingDown className="w-5 h-5" />,
  },
  medium: {
    label: "中等",
    color: "text-yellow-600",
    bg: "bg-yellow-50",
    icon: <Minus className="w-5 h-5" />,
  },
  hard: {
    label: "困难",
    color: "text-orange-600",
    bg: "bg-orange-50",
    icon: <TrendingUp className="w-5 h-5" />,
  },
  very_hard: {
    label: "非常困难",
    color: "text-red-600",
    bg: "bg-red-50",
    icon: <TrendingUp className="w-5 h-5" />,
  },
};

export function DifficultyBadge({ difficulty }: DifficultyBadgeProps) {
  const config = difficultyConfig[difficulty.overall] || difficultyConfig.medium;

  return (
    <div className="bg-white rounded-2xl shadow-lg shadow-gray-200/50 p-6">
      <div className="flex items-center gap-3 mb-4">
        <BarChart3 className="w-6 h-6 text-purple-500" />
        <h3 className="text-lg font-semibold text-gray-900">整体难度定位</h3>
      </div>

      <div className={`${config.bg} rounded-xl p-4 mb-4`}>
        <div className="flex items-center gap-3">
          <div className={`${config.color}`}>
            {config.icon}
          </div>
          <div>
            <p className={`text-2xl font-bold ${config.color}`}>
              {config.label}
            </p>
            <p className="text-sm text-gray-600 mt-1">
              难度评分: {difficulty.score}/100
            </p>
          </div>
        </div>
      </div>

      <p className="text-sm text-gray-600 leading-relaxed">
        {difficulty.description}
      </p>
    </div>
  );
}
