"use client";

import { SixDimensions } from "@/types/analysis";
import { BarChart3, Brain, Calculator, Lightbulb, Puzzle, Ruler, Shapes } from "lucide-react";

interface DimensionScoreCardProps {
  dimensions: SixDimensions;
  dimensionNames: Record<string, { name: string; desc: string; color: string }>;
}

const dimensionIcons: Record<string, React.ReactNode> = {
  computation: <Calculator className="w-5 h-5" />,
  concept: <Brain className="w-5 h-5" />,
  logic: <Puzzle className="w-5 h-5" />,
  spatial: <Shapes className="w-5 h-5" />,
  application: <Ruler className="w-5 h-5" />,
  innovation: <Lightbulb className="w-5 h-5" />,
};

const getScoreLevel = (score: number) => {
  if (score >= 90) return { level: "优秀", color: "text-green-600", bg: "bg-green-50" };
  if (score >= 80) return { level: "良好", color: "text-blue-600", bg: "bg-blue-50" };
  if (score >= 70) return { level: "中等", color: "text-yellow-600", bg: "bg-yellow-50" };
  if (score >= 60) return { level: "及格", color: "text-orange-600", bg: "bg-orange-50" };
  return { level: "需加强", color: "text-red-600", bg: "bg-red-50" };
};

export function DimensionScoreCard({ dimensions, dimensionNames }: DimensionScoreCardProps) {
  const dimensionEntries = Object.entries(dimensions);

  return (
    <div className="grid grid-cols-2 gap-4">
      {dimensionEntries.map(([key, score]) => {
        const config = dimensionNames[key];
        const icon = dimensionIcons[key];
        const scoreLevel = getScoreLevel(score);
        const percentage = score;

        return (
          <div key={key} className="bg-gray-50 rounded-xl p-4 hover:bg-gray-100 transition-colors">
            <div className="flex items-start gap-4">
              {/* Icon */}
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center text-white shrink-0"
                style={{ backgroundColor: config.color }}
              >
                {icon}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <h4 className="font-semibold text-gray-900">{config.name}</h4>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${scoreLevel.bg} ${scoreLevel.color}`}>
                    {scoreLevel.level}
                  </span>
                </div>
                <p className="text-xs text-gray-500 mb-2">{config.desc}</p>

                {/* Score Bar */}
                <div className="flex items-center gap-3">
                  <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${percentage}%`,
                        backgroundColor: config.color,
                      }}
                    />
                  </div>
                  <span className="text-sm font-bold text-gray-900 w-10 text-right">
                    {score}分
                  </span>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
