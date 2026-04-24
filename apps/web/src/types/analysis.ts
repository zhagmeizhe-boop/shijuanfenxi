/**
 * Report data types used by the web app.
 */

export interface SixDimensions {
  computation: number;
  concept: number;
  logic: number;
  spatial: number;
  application: number;
  innovation: number;
}

export interface CountedQuestion {
  page_no?: number;
  question_no: string;
  question_label_raw?: string;
  section_index_raw?: string;
  question_display_label?: string;
  summary: string;
  reason: string;
}

export interface DimensionScore {
  code: string;
  name: string;
  score: number;
  level: number;
  level_label: string;
  evidence: string;
  warning?: boolean;
  counted_questions?: CountedQuestion[];
}

export interface DifficultyPosition {
  level: number;
  label: string;
  overall_score: number;
  target_students: string;
  description: string;
  dimension_distribution: {
    code: string;
    name: string;
    percentage: number;
    color: string;
  }[];
}

export interface BenchmarkComparison {
  name: string;
  score: number;
  comparison: 'higher' | 'lower' | 'equal';
  difference: number;
}

export interface KnowledgePoint {
  id: string;
  name: string;
  level: string;
  count: number;
  related_questions: string[];
}

export interface RepresentativeQuestion {
  id: string;
  question_no: string;
  question_label_raw?: string;
  content: string;
  dimension_code: string;
  dimension_name: string;
  score: number;
  level: number;
  evidence: string;
}

export interface FullReportData {
  report_id: string;
  paper_id: string;
  paper_title: string;
  generated_at: string;
  dimensions: SixDimensions;
  dimension_details: DimensionScore[];
  report_warnings: string[];
  difficulty_position: DifficultyPosition;
  benchmark_comparisons: BenchmarkComparison[];
  knowledge_points: KnowledgePoint[];
  representative_questions: RepresentativeQuestion[];
  overall_summary: string;
  recommendations: string[];
}

export interface ReportGenerationStatus {
  status: 'pending' | 'processing' | 'completed' | 'failed';
  progress: number;
  message: string;
  error?: string;
}

export interface PDFExportOptions {
  paper_id: string;
  report_id: string;
  include_charts: boolean;
  include_evidence: boolean;
  include_questions: boolean;
  language: 'zh' | 'en';
}
