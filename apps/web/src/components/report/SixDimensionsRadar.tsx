import { useMemo } from 'react';
import {
  formatScore,
  getRadarValues,
  REPORT_DIMENSIONS,
} from '@/components/report/reportMeta';
import type { DimensionScore } from '@/types/analysis';

interface SixDimensionsRadarProps {
  dimensions: {
    computation: number;
    concept: number;
    logic: number;
    spatial: number;
    application: number;
    innovation: number;
  };
  dimensionDetails?: DimensionScore[];
}

interface RadarPoint {
  x: number;
  y: number;
}

const VIEW_BOX_WIDTH = 360;
const VIEW_BOX_HEIGHT = 340;
const RADAR_CENTER: RadarPoint = { x: 180, y: 168 };
const RADAR_RADIUS = 108;
const RADAR_LABEL_RADIUS = 142;
const RADAR_LEVELS = [0.25, 0.5, 0.75, 1];

function clampRadarValue(value: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function getRadarPoint(index: number, radius: number): RadarPoint {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / REPORT_DIMENSIONS.length;
  return {
    x: RADAR_CENTER.x + Math.cos(angle) * radius,
    y: RADAR_CENTER.y + Math.sin(angle) * radius,
  };
}

function formatPoint(point: RadarPoint): string {
  return `${point.x.toFixed(2)},${point.y.toFixed(2)}`;
}

function formatPoints(points: RadarPoint[]): string {
  return points.map(formatPoint).join(' ');
}

function getTextAnchor(x: number): 'start' | 'middle' | 'end' {
  if (x < RADAR_CENTER.x - 12) {
    return 'end';
  }
  if (x > RADAR_CENTER.x + 12) {
    return 'start';
  }
  return 'middle';
}

export function SixDimensionsRadar({ dimensions, dimensionDetails = [] }: SixDimensionsRadarProps) {
  const notCoveredCodes = useMemo(
    () =>
      new Set(
        dimensionDetails
          .filter((item) => item.score_status === 'not_covered')
          .map((item) => item.code),
      ),
    [dimensionDetails],
  );
  const radarValues = useMemo(
    () => getRadarValues(dimensions, notCoveredCodes),
    [dimensions, notCoveredCodes],
  );
  const hasDrawableValues = radarValues.some((value) => value !== null);

  const chartValues = useMemo(
    () => radarValues.map((value) => clampRadarValue(value ?? 0)),
    [radarValues],
  );
  const dataPoints = useMemo(
    () =>
      chartValues.map((value, index) =>
        getRadarPoint(index, RADAR_RADIUS * (value / 100)),
      ),
    [chartValues],
  );
  const dataPointsString = formatPoints(dataPoints);

  return (
    <div className="report-radar-card">
      <div className="report-card-heading">
        <span className="report-card-eyebrow">六维结构</span>
        <h3>六维分布</h3>
        <p>从整卷视角查看六个评价维度的相对强弱，作为难度定位与能力结构判断的辅助依据。</p>
      </div>

      <div className="report-radar-card__body">
        <div className={`report-radar-chart${hasDrawableValues ? '' : ' is-empty'}`}>
          {!hasDrawableValues ? (
            <span>暂无可绘制维度</span>
          ) : (
            <svg
              className="report-radar-svg"
              data-testid="radar-svg"
              viewBox={`0 0 ${VIEW_BOX_WIDTH} ${VIEW_BOX_HEIGHT}`}
              role="img"
              aria-label="六维评价雷达图"
            >
              <title>六维评价雷达图</title>
              {RADAR_LEVELS.map((level, index) => {
                const gridPoints = REPORT_DIMENSIONS.map((_, dimIndex) =>
                  getRadarPoint(dimIndex, RADAR_RADIUS * level),
                );
                return (
                  <polygon
                    key={level}
                    points={formatPoints(gridPoints)}
                    fill={index % 2 === 0 ? 'rgba(238, 242, 246, 0.72)' : 'rgba(248, 250, 252, 0.28)'}
                    stroke="#d6dde3"
                    strokeWidth="1"
                    vectorEffect="non-scaling-stroke"
                  />
                );
              })}
              {REPORT_DIMENSIONS.map((item, index) => {
                const outerPoint = getRadarPoint(index, RADAR_RADIUS);
                const labelPoint = getRadarPoint(index, RADAR_LABEL_RADIUS);
                const lines = item.chartName.split('\n');
                const firstLineDy = lines.length === 1 ? 0 : -0.45 * (lines.length - 1);
                return (
                  <g key={item.code}>
                    <line
                      x1={RADAR_CENTER.x}
                      y1={RADAR_CENTER.y}
                      x2={outerPoint.x.toFixed(2)}
                      y2={outerPoint.y.toFixed(2)}
                      stroke="#d6dde3"
                      strokeWidth="1"
                      vectorEffect="non-scaling-stroke"
                    />
                    <text
                      x={labelPoint.x.toFixed(2)}
                      y={labelPoint.y.toFixed(2)}
                      textAnchor={getTextAnchor(labelPoint.x)}
                      dominantBaseline="middle"
                      fill="#43525d"
                      fontSize="12"
                      fontWeight="600"
                    >
                      {lines.map((line, lineIndex) => (
                        <tspan
                          key={`${item.code}-${lineIndex}`}
                          x={labelPoint.x.toFixed(2)}
                          dy={lineIndex === 0 ? `${firstLineDy}em` : '1.15em'}
                        >
                          {line}
                        </tspan>
                      ))}
                    </text>
                  </g>
                );
              })}
              <polygon
                data-testid="radar-data-area"
                points={dataPointsString}
                fill="rgba(41, 71, 102, 0.16)"
                stroke="none"
              />
              <polyline
                data-testid="radar-data-line"
                points={`${dataPointsString} ${formatPoint(dataPoints[0])}`}
                fill="none"
                stroke="#294766"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
              {dataPoints.map((point, index) => (
                <circle
                  key={REPORT_DIMENSIONS[index].code}
                  data-testid="radar-data-point"
                  cx={point.x.toFixed(2)}
                  cy={point.y.toFixed(2)}
                  r="4"
                  fill="#294766"
                  stroke="#ffffff"
                  strokeWidth="2"
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </svg>
          )}
        </div>

        <div className="report-radar-metrics">
          {REPORT_DIMENSIONS.map((item) => {
            const isNotCovered = dimensionDetails.some(
              (detail) => detail.code === item.code && detail.score_status === 'not_covered',
            );

            return (
              <div key={item.code} className="report-radar-metric">
                <strong>{item.name}</strong>
                <span>{isNotCovered ? '未覆盖' : `${formatScore(dimensions[item.field], 0)} / 100`}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
