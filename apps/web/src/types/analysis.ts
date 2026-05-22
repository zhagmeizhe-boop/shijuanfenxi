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
  score?: number;
  level_code?: string;
  difficulty_label?: string;
  knowledge_source_text?: string;
  knowledge_point_text?: string;
  knowledge_track?: string;
  knowledge_track_label?: string;
  knowledge_grade?: string;
  knowledge_grade_label?: string;
  knowledge_semester?: string;
  knowledge_display_name?: string;
  dim5_key_difficulty_explanation?: string;
  practice_level_text?: string;
  score_reason?: string;
  reason: string;
  full_reason?: string;
}

export interface DimensionScore {
  code: string;
  name: string;
  score: number;
  level: number;
  level_label: string;
  score_status?: 'scored' | 'not_covered';
  evidence: string;
  warning?: boolean;
  counted_questions?: CountedQuestion[];
  score_breakdown?: Record<string, unknown>;
}

export interface QuestionDifficultyItem {
  page_no?: number;
  question_no: string;
  question_label_raw?: string;
  section_index_raw?: string;
  question_display_label?: string;
  question_short_label?: string;
  average_score: number;
}

export interface QuestionDifficultyBucket {
  key: string;
  label: string;
  description?: string;
  count: number;
  percentage: number;
  questions: QuestionDifficultyItem[];
}

export interface QuestionDifficultyDistribution {
  basis: string;
  classification: string;
  total_count: number;
  classified_count: number;
  unclassified_count: number;
  buckets: QuestionDifficultyBucket[];
}

export interface DifficultyPosition {
  level: number;
  label: string;
  overall_score: number;
  position_summary?: string;
  target_students: string;
  description: string;
  parent_summary?: string[];
  question_distribution?: QuestionDifficultyDistribution;
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
