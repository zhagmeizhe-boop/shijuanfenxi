import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import {
  formatScore,
  getRadarValues,
  REPORT_DIMENSIONS,
} from '@/components/report/reportMeta';

interface SixDimensionsRadarProps {
  dimensions: {
    computation: number;
    concept: number;
    logic: number;
    spatial: number;
    application: number;
    innovation: number;
  };
}

export function SixDimensionsRadar({ dimensions }: SixDimensionsRadarProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) {
      return;
    }

    const radarValues = getRadarValues(dimensions);

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, undefined, { renderer: 'svg' });
    }

    const option: echarts.EChartsOption = {
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(255, 255, 255, 0.96)',
        borderColor: '#cfd6dc',
        textStyle: {
          color: '#1f2933',
        },
        formatter: () =>
          REPORT_DIMENSIONS.map(
            (item, index) => `${item.name}: ${formatScore(radarValues[index], 0)} / 100`,
          ).join('<br/>'),
      },
      radar: {
        indicator: REPORT_DIMENSIONS.map((item) => ({
          name: item.chartName,
          max: 100,
          color: '#43525d',
        })),
        shape: 'polygon',
        splitNumber: 4,
        radius: '67%',
        center: ['50%', '48%'],
        axisName: {
          fontSize: 12,
          fontWeight: 600,
          padding: [0, 0, 8, 0],
        },
        splitLine: {
          lineStyle: {
            color: '#d6dde3',
          },
        },
        splitArea: {
          show: true,
          areaStyle: {
            color: ['rgba(238, 242, 246, 0.72)', 'rgba(248, 250, 252, 0.28)'],
          },
        },
        axisLine: {
          lineStyle: {
            color: '#d6dde3',
          },
        },
      },
      series: [
        {
          name: '六维评价',
          type: 'radar',
          data: [
            {
              value: radarValues,
              name: '当前试卷',
              symbol: 'circle',
              symbolSize: 7,
              lineStyle: {
                width: 2.5,
                color: '#294766',
              },
              areaStyle: {
                color: 'rgba(41, 71, 102, 0.16)',
              },
              itemStyle: {
                color: '#294766',
                borderColor: '#fff',
                borderWidth: 2,
              },
            },
          ],
        },
      ],
    };

    chartInstance.current.setOption(option);

    const handleResize = () => {
      chartInstance.current?.resize();
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, [dimensions]);

  return (
    <div className="report-radar-card">
      <div className="report-card-heading">
        <span className="report-card-eyebrow">六维结构</span>
        <h3>六维分布</h3>
        <p>从整卷视角查看六个评价维度的相对强弱，作为难度定位与后续训练建议的辅助依据。</p>
      </div>

      <div className="report-radar-card__body">
        <div ref={chartRef} className="report-radar-chart" />

        <div className="report-radar-metrics">
          {REPORT_DIMENSIONS.map((item) => (
            <div key={item.code} className="report-radar-metric">
              <strong>{item.name}</strong>
              <span>{formatScore(dimensions[item.field], 0)} / 100</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
