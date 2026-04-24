"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { SixDimensions } from "@/types/analysis";

interface SixDimensionsRadarProps {
  dimensions: SixDimensions;
}

export function SixDimensionsRadar({ dimensions }: SixDimensionsRadarProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;

    // 初始化图表
    chartInstance.current = echarts.init(chartRef.current);

    const option: echarts.EChartsOption = {
      title: {
        text: "六维能力分析",
        left: "center",
        top: 10,
        textStyle: {
          fontSize: 18,
          fontWeight: "bold",
          color: "#1f2937",
        },
      },
      tooltip: {
        trigger: "item",
        formatter: function (params: any) {
          const data = params.data;
          let html = `<div style="padding: 10px;">`;
          html += `<div style="font-weight: bold; margin-bottom: 5px;">${params.name}</div>`;
          dimensions && Object.entries(dimensions).forEach(([key, value], index) => {
            const colors = ["#3B82F6", "#8B5CF6", "#EC4899", "#10B981", "#F59E0B", "#EF4444"];
            html += `<div style="display: flex; align-items: center; margin: 3px 0;">`;
            html += `<span style="display: inline-block; width: 10px; height: 10px; background: ${colors[index]}; border-radius: 50%; margin-right: 8px;"></span>`;
            html += `<span style="flex: 1;">${key}</span>`;
            html += `<span style="font-weight: bold;">${value}分</span>`;
            html += `</div>`;
          });
          html += `</div>`;
          return html;
        },
      },
      radar: {
        indicator: [
          { name: "计算\n熟练度", max: 100, color: "#3B82F6" },
          { name: "概念\n清晰度", max: 100, color: "#8B5CF6" },
          { name: "逻辑\n推理力", max: 100, color: "#EC4899" },
          { name: "空间\n想象力", max: 100, color: "#10B981" },
          { name: "应用\n实践力", max: 100, color: "#F59E0B" },
          { name: "创新\n思维力", max: 100, color: "#EF4444" },
        ],
        shape: "polygon",
        splitNumber: 4,
        axisName: {
          fontSize: 12,
          fontWeight: "bold",
        },
        splitLine: {
          lineStyle: {
            color: ["#E5E7EB"],
          },
        },
        splitArea: {
          show: true,
          areaStyle: {
            color: ["rgba(59, 130, 246, 0.02)", "rgba(59, 130, 246, 0.05)"],
          },
        },
        axisLine: {
          lineStyle: {
            color: "#E5E7EB",
          },
        },
      },
      series: [
        {
          name: "能力评估",
          type: "radar",
          data: [
            {
              value: [
                dimensions.computation,
                dimensions.concept,
                dimensions.logic,
                dimensions.spatial,
                dimensions.application,
                dimensions.innovation,
              ],
              name: "当前试卷",
              symbol: "circle",
              symbolSize: 8,
              lineStyle: {
                width: 3,
                color: {
                  type: "linear",
                  x: 0,
                  y: 0,
                  x2: 1,
                  y2: 1,
                  colorStops: [
                    { offset: 0, color: "#3B82F6" },
                    { offset: 0.2, color: "#8B5CF6" },
                    { offset: 0.4, color: "#EC4899" },
                    { offset: 0.6, color: "#10B981" },
                    { offset: 0.8, color: "#F59E0B" },
                    { offset: 1, color: "#EF4444" },
                  ],
                },
              },
              areaStyle: {
                color: {
                  type: "radial",
                  x: 0.5,
                  y: 0.5,
                  r: 0.5,
                  colorStops: [
                    { offset: 0, color: "rgba(59, 130, 246, 0.3)" },
                    { offset: 1, color: "rgba(59, 130, 246, 0.05)" },
                  ],
                },
              },
              itemStyle: {
                color: "#3B82F6",
                borderColor: "#fff",
                borderWidth: 2,
              },
            },
          ],
        },
      ],
    };

    chartInstance.current.setOption(option);

    // 响应式
    const handleResize = () => {
      chartInstance.current?.resize();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chartInstance.current?.dispose();
    };
  }, [dimensions]);

  return (
    <div
      ref={chartRef}
      style={{ width: "100%", height: "500px" }}
    />
  );
}
