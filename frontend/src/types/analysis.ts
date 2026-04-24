export interface SixDimensions {
  computation: number;
  concept: number;
  logic: number;
  spatial: number;
  application: number;
  innovation: number;
}

export interface DifficultyLevel {
  overall: 'very_easy' | 'easy' | 'medium' | 'hard' | 'very_hard';
  score: number;
  description: string;
}

export interface KnowledgePoint {
  name: string;
  category: string;
  count: number;
  difficulty_avg: number;
}

export interface RepresentativeQuestion {
  id: string;
  dimension: keyof SixDimensions;
  content: string;
  difficulty: number;
  score: number;
}

export interface AnalysisResult {
  id: string;
  paper_info: {
    title: string;
    grade: string;
    subject: string;
    total_score: number;
    question_count: number;
    estimated_time: number;
    source?: string;
    created_at: string;
  };
  dimensions: SixDimensions;
  difficulty: DifficultyLevel;
  target_students: string[];
  comparison: {
    avg_score: number;
    percentile: number;
    benchmark: string;
  };
  knowledge_points: KnowledgePoint[];
  representative_questions: RepresentativeQuestion[];
  generated_at: string;
}

export interface UploadResponse {
  task_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  message: string;
  result?: AnalysisResult;
}

export interface UploadFileRequest {
  file: File;
  grade?: string;
  subject?: string;
}
